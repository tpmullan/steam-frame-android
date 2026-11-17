#!/usr/bin/env python3
"""Try a GPU/Android configuration on the Frame and run a checklist against it.

Runs on the Mac (or any machine that can ssh to the Frame). For each configuration it applies the
settings, restarts Android through its Steam entry, waits for the boot, runs the checks and, however
that ends, puts the baseline back (use --keep to leave the trial configuration in place).

Configurations (name: what changes):
  baseline   nothing
  ccodec0    device.prop gets debug.stagefright.ccodec=0 (Lepton's video setting)
  angle      `wgapps gpu egl angle` (ANGLE instead of Mesa's EGL/GLES)

Checks: the boot finishes and the GLES driver is named, no new native crash (tombstone), Settings,
Chrome and Plex each draw something, hello_xr (OpenGL ES and Vulkan) reaches FOCUSED and keeps
presenting frames, Wolvic opens a 360 video page, reaches FOCUSED and keeps logging frames for
--soak seconds (the freeze we are chasing stops them; the fullscreen toggle that triggered it by
hand cannot be sent from here, so a pass is weaker than a person's repro).

Usage: tools/gpu-trial.py [--host USER@FRAME] [--soak 60] [--keep]
                          [--report FILE] CONFIG [CONFIG...]
Needs the headset worn or tracked (SteamVR must reach FOCUSED) and Steam running on the Frame.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

BASE = ".local/share/waydroid-gapps"
WGAPPS = f"$HOME/{BASE}/bin/wgapps"
VRCMD = "/opt/steamvr/bin/linuxarm64/vrcmd"
CONTAINER = "waydroid-gapps"
WOLVIC = "com.igalia.wolvic.vanilla"
WOLVIC_ACTIVITY = f"{WOLVIC}/com.igalia.wolvic.VRBrowserActivity"
VIDEO_360 = "https://www.youtube.com/watch?v=Z4QV22VGfGs&mozVideoProjection=360_auto"
HELLO_GLES = "org.khronos.openxr.hello_xr.opengles"
HELLO_VULKAN = "org.khronos.openxr.hello_xr.vulkan"
CONFIGS = {
    "baseline": {"device_prop": [], "egl": "mesa"},
    "ccodec0": {"device_prop": ["debug.stagefright.ccodec=0"], "egl": "mesa"},
    "angle": {"device_prop": [], "egl": "angle"},
}

# Remote Python, run on the Frame: the game id of the Android Steam entry (the shortcut that runs
# `wgapps steam` with no package), optionally ending it through Steam's own client API.
REMOTE_STEAM = """
import importlib.machinery, importlib.util, pathlib, shlex, sys
path = str(pathlib.Path.home() / ".local/share/waydroid-gapps/bin/steam-shortcuts.py")
loader = importlib.machinery.SourceFileLoader("sc", path)
sc = importlib.util.module_from_spec(importlib.util.spec_from_loader("sc", loader))
loader.exec_module(sc)
ours = [s for s in sc.load(sc.shortcuts_path()).values()
        if shlex.split(str(s.get("Exe", ""))) == [str(sc.WGAPPS)]
        and str(s.get("LaunchOptions", "")).strip() == "steam"]
if not ours:
    sys.exit("no Android entry in Steam")
game = ((ours[0]["appid"] & 0xFFFFFFFF) << 32) | 0x02000000
if sys.argv[1] == "terminate":
    cef = sc.Cef(8080)
    cef.evaluate('SteamClient.Apps.TerminateApp("%d", false)' % game)
    cef.close()
print(game)
"""


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    diagnostics: str = ""


class Frame:
    def __init__(self, host: str):
        self.host = host
        self.env = {**os.environ, "PATH": f"/usr/bin:{os.environ.get('PATH', '')}"}

    def run(self, command: str, timeout: float = 120, stdin: str | None = None) -> str:
        done = subprocess.run(
            ["/usr/bin/ssh", "-o", "BatchMode=yes", self.host, command],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=self.env,
            check=False,
        )
        return (done.stdout + done.stderr).strip() if done.returncode else done.stdout.strip()

    def android(self, command: str, timeout: float = 60) -> str:
        return self.run(
            f"podman exec {CONTAINER} /system/bin/sh -c {shlex.quote(command)}", timeout
        )

    def steam(self, action: str) -> str:
        return self.run("python3 - " + action, timeout=40, stdin=REMOTE_STEAM)


def log(message: str) -> None:
    print(time.strftime("%T"), message, flush=True)


def wait_for(predicate, seconds: float, step: float = 2.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def container_running(frame: Frame) -> bool:
    return (
        frame.run(f"podman inspect -f '{{{{.State.Running}}}}' {CONTAINER} 2>/dev/null") == "true"
    )


def restart_android(frame: Frame) -> bool:
    """End the Android Steam entry, start it again and wait for the boot. True if it booted."""
    game = frame.steam("game")
    if not game.isdigit():
        log(f"cannot find the Android Steam entry: {game}")
        return False
    if container_running(frame):
        frame.steam("terminate")
        if not wait_for(lambda: not container_running(frame), 60):
            log("Android did not stop")
            return False
    frame.run(f"(steam -ifrunning steam://rungameid/{game} >/dev/null 2>&1 &)")
    return wait_for(lambda: "boot_completed=1" in frame.run(f"{WGAPPS} status"), 240, 5)


def apply_config(frame: Frame, name: str) -> None:
    config = CONFIGS[name]
    props = "\\n".join(config["device_prop"])
    path = f"$HOME/{BASE}/device.prop"
    if props:
        frame.run(f"printf '{props}\\n' > {path}")
    else:
        frame.run(f"rm -f {path}")
    frame.run(f"{WGAPPS} gpu egl {config['egl']}")


def newest_tombstone(frame: Frame) -> str:
    """Name of the newest tombstone. Android keeps at most 50 and drops the oldest, so a count
    never changes once the folder is full; the newest name does."""
    return frame.android("ls -t /data/tombstones 2>/dev/null | grep -v '\\.pb$' | head -1")


def stop_apps(frame: Frame) -> None:
    packages = ("com.android.chrome", "com.plexapp.android", "com.android.settings", WOLVIC)
    for package in (*packages, HELLO_GLES, HELLO_VULKAN):
        frame.android(f"am force-stop {package}")


def draws(frame: Frame, name: str, component: str) -> Check:
    """The app starts and the screen is not a blank frame (a screenshot of some size)."""
    frame.android(f"am force-stop {component.split('/')[0]}; am start -n {component} >/dev/null")
    time.sleep(8)
    size = frame.android("screencap -p | wc -c")
    top = frame.android("dumpsys activity activities | grep -m1 topResumedActivity")
    ok = size.isdigit() and int(size) > 60_000 and component.split("/")[0] in top
    return Check(name, ok, f"screenshot {size} bytes; top: {top[-70:] or 'none'}")


def diagnostics(frame: Frame) -> str:
    """What the log says about a failed app: our layer, the session, EGL/ANGLE errors, crashes."""
    return frame.android(
        "logcat -d | grep -E 'hello_xr|wgapps-xr|XrEventData|XR_ERROR|ANGLE|EGL_|eglCreate|"
        "Fatal signal|FATAL|VRB.*[Ee]rror' | tail -60 | cut -c1-230",
        timeout=60,
    )


def focused(frame: Frame, seconds: float = 45) -> bool:
    def poll() -> bool:
        frame.run(f"{VRCMD} --hidedashboard >/dev/null 2>&1")
        return "XR_SESSION_STATE_FOCUSED" in frame.android(
            "logcat -d | grep XrEventDataSessionStateChanged | tail -3"
        )

    return wait_for(poll, seconds, 3)


def presents(frame: Frame) -> int:
    match = re.search(r'"frame_presents"\s*:\s*(\d+)', frame.run(f"{VRCMD} --stats 2>&1"))
    return int(match.group(1)) if match else -1


def hello_xr(frame: Frame, name: str, package: str) -> Check:
    frame.android(
        f"am force-stop {package}; logcat -c; "
        f"am start -n {package}/android.app.NativeActivity >/dev/null"
    )
    if not focused(frame):
        info = diagnostics(frame)
        frame.android(f"am force-stop {package}")
        return Check(name, False, "never reached FOCUSED", info)
    before = presents(frame)
    time.sleep(4)
    after = presents(frame)
    frame.android(f"am force-stop {package}")
    return Check(name, after - before > 100, f"frames presented in 4 s: {after - before}")


def last_frame_age(frame: Frame) -> float:
    out = frame.android(
        "now=$(date +%s); t=$(logcat -d -v epoch | grep 'Average Frame Rate' | tail -1 | "
        "cut -d. -f1 | tr -d ' '); echo $((now - ${t:-0}))"
    )
    return float(out) if re.fullmatch(r"-?\d+", out) else 9999.0


SIM_FILES = {"right": "/tmp/xr-sim-input", "left": "/tmp/xr-sim-input-left"}


def play_toggle_script(frame: Frame, steps: list[dict]) -> None:
    """Drive the simulated SteamVR controllers (runtime-rust/xr-sim's driver) through `steps`.

    Each step is {"right": [x, y, z, yaw, pitch, trigger, grip, stick, buttons], "left": [...],
    "keys": ["KEYCODE_F"], "wait": seconds}; a hand left out keeps its last pose (add a tenth number,
    2, to make a hand ride rigidly with the headset, whatever the headset is doing), and "keys" are sent to
    Android as key events (YouTube's player toggles fullscreen on F and leaves it on Escape). This is how a person's fullscreen toggle in
    Wolvic is repeated without one (poses are recorded once on a headset, see the runbook).
    """
    for step in steps:
        for hand, path in SIM_FILES.items():
            if hand in step:
                line = " ".join(str(v) for v in step[hand])
                frame.run(f"echo '{line}' > {path}; chmod 666 {path}")
        for key in step.get("keys", []):
            frame.android(f"input keyevent {shlex.quote(key)}")
        time.sleep(float(step.get("wait", 1.0)))


def fullscreen_events(frame: Frame) -> tuple[int, int]:
    """(entered, exited) counts of Wolvic's page fullscreen events since logcat was cleared."""
    log = frame.android("logcat -d | grep -E 'GeckoView:DOMFullscreen(Entered|Exited)'")
    return log.count("DOMFullscreenEntered"), log.count("DOMFullscreenExited")


def recentre(frame: Frame) -> None:
    """Make SteamVR re-set the play space on the headset's current pose (the dashboard's Quick
    Calibrate, as an API). Wolvic then re-places its windows in front of the headset, so a scripted
    pose aims at the same spot on any run, whatever the headset is lying on. Only works on a window
    Wolvic has not yet moved itself, so do it right after a launch (leaving fullscreen moves it)."""
    frame.run(
        f"{VRCMD} --resetroomsetup >/dev/null 2>&1; sleep 4; "
        f"for i in 1 2 3 4; do {VRCMD} --hidedashboard >/dev/null 2>&1; sleep 3; done"  # it opens SteamVR's menu
    )


def max_gap(times: list[float], start: float, end: float) -> float:
    """Longest silence between log lines inside [start, end], counting from start and up to end."""
    inside = [t for t in times if start <= t <= end]
    points = [start, *inside, end]
    return max(b - a for a, b in zip(points, points[1:], strict=False))


def epochs(log: str, marker: str) -> list[float]:
    """Epoch seconds of the `logcat -v epoch` lines containing `marker`."""
    found = []
    for line in log.splitlines():
        match = re.match(r"\s*(\d+\.\d+)", line)
        if match and marker in line:
            found.append(float(match.group(1)))
    return found


def hmd_pose(frame: Frame) -> tuple[float, ...] | None:
    """The headset's tracked pose (x y z and three angles, as `vrcmd --pollposes` prints), or None."""
    line = frame.run(f"timeout 5 {VRCMD} --pollposes 2>&1 | head -1").strip()
    parts = line.split(",")
    try:
        return tuple(float(v) for v in parts[1:7]) if len(parts) >= 7 and parts[0] == "0" else None
    except ValueError:
        return None


def pose_moved(a: tuple[float, ...] | None, b: tuple[float, ...] | None) -> bool:
    """True when the two readings differ by more than 1 cm or about 2 degrees (or one is missing)."""
    if a is None or b is None:
        return True
    return any(abs(x - y) > 0.01 for x, y in zip(a[:3], b[:3], strict=False)) or any(
        min(abs(x - y), 6.2832 - abs(x - y)) > 0.035 for x, y in zip(a[3:], b[3:], strict=False)
    )


def wait_still(frame: Frame, seconds: float = 90) -> bool:
    """Wait until the headset has not moved for two readings 4 s apart. The scripted aim assumes a
    headset that stays put: Wolvic places its window from the headset's pose at launch."""

    def still() -> bool:
        first = hmd_pose(frame)
        time.sleep(4)
        return first is not None and not pose_moved(first, hmd_pose(frame))

    return wait_for(still, seconds, 1)


HOVER_PORT = 8099
HOVER_URL = (
    f"http://172.20.0.1:{HOVER_PORT}/hover.html"  # the Frame, as the Android container sees it
)


def calibrate_aim(frame: Frame, start: list[float] | None) -> list[float] | None:
    """[yaw, pitch] that points the simulated hand at the middle of Wolvic's player, measured on the
    live window with tools/frame-hover.html (see tools/frame-aim-sweep.py), or None. Wolvic places its
    window from the headset's pose when it launches, so the aim has to be measured for each pose."""
    here = pathlib.Path(__file__).resolve().parent
    frame.run("mkdir -p /tmp/hover")
    subprocess.run(
        ["scp", "-q", str(here / "frame-hover.html"), f"{frame.host}:/tmp/hover/hover.html"],
        check=True,
    )
    frame.run(
        f"ss -ltn | grep -q ':{HOVER_PORT} ' || (cd /tmp/hover && exec setsid python3 -m http.server "
        f"{HOVER_PORT} --bind 0.0.0.0) >/tmp/hover/log.txt 2>&1 </dev/null & sleep 1"
    )
    frame.android(f"am force-stop {WOLVIC}")
    frame.android(
        f"am start -a android.intent.action.VIEW -d '{HOVER_URL}' -n {WOLVIC_ACTIVITY} >/dev/null"
    )
    if not focused(frame, 60):
        return None
    time.sleep(10)
    recentre(frame)
    args = f" {start[0]} {start[1]}" if start else ""
    out = frame.run(
        f"python3 - {args}", stdin=(here / "frame-aim-sweep.py").read_text(), timeout=600
    ).strip()
    try:
        return json.loads(out.splitlines()[-1]).get("aim")
    except (ValueError, IndexError):
        return None


def fullscreen_round(
    frame: Frame,
    aim: list[float],
    dwell: float,
    after: float,
    cycles: int,
    known: list[float],
    stress: int = 0,
) -> dict:
    """One Wolvic launch: play the 360 video, then `cycles` times double-click it with the simulated
    hand (rigid with the headset at `aim` = x y z yaw pitch) into fullscreen, stay `dwell` s, leave
    with B and watch `after` s of Wolvic's frame logs for a freeze. Leaving fullscreen moves the
    window, so the play space is re-centred after each exit to bring it back in front."""
    if not wait_still(frame):
        return {"launched": False, "moved": True}
    start_pose = hmd_pose(frame)
    measured = calibrate_aim(frame, known or aim[3:5])
    if not measured:
        return {"launched": False, "calibrated": False}
    known[:] = measured
    aim = [*aim[:3], *measured]
    frame.android("logcat -c")
    frame.android(
        f"am start -a android.intent.action.VIEW -d '{VIDEO_360}' -n {WOLVIC_ACTIVITY} >/dev/null"
    )
    time.sleep(25)  # the page and video load in the window that was just measured

    def hand(trigger: int = 0, buttons: int = 0, shift: tuple[float, float] = (0, 0)) -> list:
        x, y, z, yaw, pitch = aim
        return [x, y, z, yaw + shift[0], pitch + shift[1], trigger, 0, 0, buttons, 2]

    play_toggle_script(
        frame,
        [
            {"left": [0] * 10, "right": hand(), "wait": 1.5},
            {"right": hand(1), "wait": 0.15},  # one click starts playback
            {"right": hand(), "wait": 4},
        ],
    )
    # The window lands a few degrees differently on each launch. The player is about 40 degrees wide,
    # so double clicks a few degrees around the aim all stay on it; stop at the first that enters fullscreen.
    shifts = [(0, 0), (6, 0), (-6, 0), (0, 6), (0, -6), (6, 6), (-6, -6), (6, -6), (-6, 6)]
    entered, used, tried = 0, None, []
    if fullscreen_events(frame)[
        0
    ]:  # Wolvic goes fullscreen by itself when a 360 video starts playing
        entered, used, shifts = 1, (0, 0), []
    for shift in shifts:
        before, _ = fullscreen_events(frame)
        play_toggle_script(
            frame,
            [
                {"right": hand(0, 0, shift), "wait": 0.6},
                {
                    "right": hand(1, 0, shift),
                    "wait": 0.12,
                },  # a double click on the player enters fullscreen if playing it did not
                {"right": hand(0, 0, shift), "wait": 0.12},
                {"right": hand(1, 0, shift), "wait": 0.12},
                {"right": hand(0, 0, shift), "wait": 2.5},
            ],
        )
        tried.append((shift, before, fullscreen_events(frame)[0]))
        if tried[-1][2] > before:
            entered, used = 1, shift
            break
    moved = pose_moved(start_pose, hmd_pose(frame))
    measured_aim = list(aim[3:5])
    if entered:  # B pressed outside fullscreen would navigate Wolvic back
        if stress:  # busy loops slow every thread down, which widens the window for a lock race
            frame.android(
                f"for i in $(seq {stress}); do (timeout {int(dwell + after + 10)} sh -c 'while :; do :; done' "
                ">/dev/null 2>&1 &) ; done"
            )
        play_toggle_script(
            frame, [{"right": hand(), "wait": dwell}, {"right": hand(0, 16), "wait": 0.3}]
        )
        play_toggle_script(frame, [{"right": hand(), "wait": after}])
    return {
        "launched": True,
        "cycles": cycles,
        "entered": entered,
        "moved": moved,
        "aim": measured_aim,
        "shift": used,
        "tried": tried,
        "gaps": gaps_after_exits(frame, after),
    }


FREEZE_GAP = 8.0  # s of silence in Wolvic's frame logs that counts as a freeze


def dump_freeze(frame: Frame, directory: pathlib.Path) -> str:
    """Save a native stack dump of the frozen Wolvic (debuggerd -b) and the end of its log, so a
    freeze that happens can be read afterwards; returns the file's path."""
    stacks = frame.android(f"debuggerd -b $(pidof {WOLVIC}) 2>&1 | head -400", timeout=120)
    log = frame.android("logcat -d -v epoch | tail -120")
    path = directory / f"wolvic-freeze-{time.strftime('%Y%m%d-%H%M%S')}.txt"
    path.write_text(f"# native stacks (debuggerd -b)\n{stacks}\n\n# end of logcat\n{log}\n")
    return str(path)


def gaps_after_exits(frame: Frame, after: float) -> list[float]:
    """Longest silence in Wolvic's frame logs in the `after` s following each fullscreen exit."""
    log = frame.android("logcat -d -v epoch | grep -E 'DOMFullscreenExited|Average Frame Rate'")
    frames = epochs(log, "Average Frame Rate")
    return [max_gap(frames, t, t + after) for t in epochs(log, "GeckoView:DOMFullscreenExited")]


def wolvic(frame: Frame, soak: float, toggle: dict | None = None) -> Check:
    """Wolvic's 360 video. Without `toggle`: play it for `soak` s and look for a frozen render loop.
    With `toggle` ({"aim": [x, y, z, yaw, pitch], "dwell": s, "after": s, "cycles": n}): run fullscreen_round on a fresh
    Wolvic launch `cycles` times (once in fullscreen per launch: leaving it moves the window away, and
    only a launch followed by a re-centre puts it back where the aim expects) and fail if the page never entered fullscreen (a broken input path
    must not look like a pass) or if Wolvic's frame logs went quiet after leaving fullscreen."""
    if toggle:
        known: list[float] = []
        results = []
        dumps: list[str] = []
        for _ in range(toggle.get("cycles", 10)):
            result = fullscreen_round(
                frame,
                toggle["aim"],
                toggle.get("dwell", 12),
                toggle.get("after", 12),
                1,
                known,
                toggle.get("stress", 0),
            )
            results.append(result)
            if not result.get("moved") and max(result.get("gaps", []), default=0.0) >= FREEZE_GAP:
                dumps.append(dump_freeze(frame, pathlib.Path(tempfile.gettempdir())))
        alive = bool(frame.android(f"pidof {WOLVIC}"))
        frame.android(f"am force-stop {WOLVIC}")
        moved = sum(1 for r in results if r.get("moved"))
        results = [
            r for r in results if not r.get("moved")
        ]  # a headset that moved says nothing about the aim
        wanted = sum(r.get("cycles", 0) for r in results)
        entered = sum(r.get("entered", 0) for r in results)
        gaps = [g for r in results for g in r.get("gaps", [])]
        worst = max(gaps, default=0.0)
        frozen = sum(1 for g in gaps if g >= FREEZE_GAP)
        detail = (
            f"alive={alive}; {len(results)} fresh launches, fullscreen entered {entered} of {wanted} times, "
            f"{frozen} freezes after leaving it, longest gap in frame logs {worst:.1f} s; "
            f"{moved} rounds discarded because the headset moved"
            + (f"; stack dumps of the frozen process: {dumps}" if dumps else "")
        )
        if not results:
            return Check("wolvic 360 video", False, "the headset never kept still: " + detail)
        if frozen:
            return Check("wolvic 360 video", False, "FROZE: " + detail)
        if entered < wanted:
            return Check("wolvic 360 video", False, "input path broken: " + detail)
        return Check("wolvic 360 video", alive, detail)
    frame.android(f"am force-stop {WOLVIC}; logcat -c")
    frame.android(
        f"am start -a android.intent.action.VIEW -d '{VIDEO_360}' -n {WOLVIC_ACTIVITY} >/dev/null"
    )
    if not focused(frame, 60):
        info = diagnostics(frame)
        frame.android(f"am force-stop {WOLVIC}")
        return Check("wolvic 360 video", False, "never reached FOCUSED", info)
    worst = 0.0
    end = time.monotonic() + soak
    while time.monotonic() < end:
        time.sleep(5)
        worst = max(worst, last_frame_age(frame))
    alive = bool(frame.android(f"pidof {WOLVIC}"))
    frame.android(f"am force-stop {WOLVIC}")
    detail = f"alive={alive}; longest gap in frame logs {worst:.0f} s over {soak:.0f} s; no fullscreen toggle sent"
    return Check("wolvic 360 video", alive and worst < 8, detail)


POINTER_INPUT = (
    "input mouse tap 400 300; input mouse swipe 300 300 900 500 150; "
    "input mouse scroll 600 400 --axis VSCROLL,-1; input tap 500 400"
)
SYSTEM_SERVICES = ("surfaceflinger", "android.hardware.graphics.composer@2.1-service")


def system_pids(frame: Frame) -> dict[str, str]:
    """Process IDs of the display services. A crash restarts them (new pid), which the user
    sees as Android rebooting."""
    return {name: frame.android(f"pidof {name}").strip() for name in SYSTEM_SERVICES}


def pids_changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Names of services missing or restarted between two readings."""
    return [name for name in before if not after.get(name) or after[name] != before[name]]


def known_crash(tombstone: str) -> str | None:
    """Name a tombstone we have root-caused (docs/bugs/), or None.

    The ANGLE display crash: the composer HAL (hwcomposer.waydroid.so) calls eglCreateImageKHR
    and ANGLE dereferences a null pointer in egl::Image::onDestroy. Android's display restarts,
    which looks like Android rebooting; it happens as soon as the pointer is used on the panel.
    """
    if (
        "android.hardware.graphics.composer" in tombstone
        and "libGLESv2_angle.so" in tombstone
        and "eglCreateImageKHR" in tombstone
        and "egl::Image::onDestroy" in tombstone
    ):
        return "composer-angle-createimage (docs/bugs/2026-11-15-angle-composer-crash.md)"
    if "hello_xr.opengles" in tombstone and "pc 0000000000000000" in tombstone:
        return "hello_xr-null-gl-function (ANGLE reports ES 3.1; see docs/bugs/)"
    return None


def pointer(frame: Frame) -> Check:
    """Use the panel with pointer input and see that the display services stay up."""
    before = system_pids(frame)
    tomb = newest_tombstone(frame)
    for _ in range(10):
        frame.android(POINTER_INPUT)
    time.sleep(3)
    gone = pids_changed(before, system_pids(frame))
    crashed = newest_tombstone(frame) != tomb
    detail = f"restarted: {', '.join(gone)}" if gone else "display services stayed up"
    if crashed:
        name = newest_tombstone(frame)
        body = frame.android(f"cat /data/tombstones/{name} 2>/dev/null | head -60")
        detail += f"; new tombstone {name}: {known_crash(body) or 'unknown crash'}"
    return Check("pointer input keeps the display services up", not gone and not crashed, detail)


def run_checks(frame: Frame, soak: float, toggle: dict | None = None) -> list[Check]:
    checks = []
    renderer = frame.android("dumpsys SurfaceFlinger | grep -m1 '^GLES'")
    checks.append(Check("boot and GLES driver", bool(renderer), renderer or "no GLES line"))
    before = newest_tombstone(frame)
    stop_apps(frame)
    checks.append(pointer(frame))
    checks.append(draws(frame, "settings draws", "com.android.settings/.Settings"))
    checks.append(
        draws(frame, "chrome draws", "com.android.chrome/com.google.android.apps.chrome.Main")
    )
    checks.append(draws(frame, "plex draws", "com.plexapp.android/tv.plex.app.MainActivity"))
    stop_apps(frame)
    checks.append(hello_xr(frame, "hello_xr OpenGL ES", HELLO_GLES))
    checks.append(hello_xr(frame, "hello_xr Vulkan", HELLO_VULKAN))
    checks.append(wolvic(frame, soak, toggle))
    stop_apps(frame)
    after = newest_tombstone(frame)
    checks.append(
        Check("no new native crash", after == before, f"newest tombstone {before} -> {after}")
    )
    return checks


def trial(frame: Frame, name: str, soak: float, toggle: dict | None = None) -> list[Check]:
    log(f"== {name}: applying and restarting Android")
    apply_config(frame, name)
    if not restart_android(frame):
        return [Check("boot and GLES driver", False, "Android did not boot")]
    return run_checks(frame, soak, toggle)


def restore(frame: Frame) -> bool:
    log("== restoring the baseline")
    apply_config(frame, "baseline")
    return restart_android(frame)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Trial GPU configurations on the Frame")
    parser.add_argument("configs", nargs="+", choices=sorted(CONFIGS))
    parser.add_argument(
        "--host",
        default=os.environ.get("FRAME_HOST"),
        required="FRAME_HOST" not in os.environ,
        help="USER@FRAME (default: $FRAME_HOST)",
    )
    parser.add_argument("--soak", type=float, default=60.0)
    parser.add_argument(
        "--toggle-script",
        help="JSON {aim, dwell, after, cycles} for the scripted Wolvic fullscreen rounds (see wolvic())",
    )
    parser.add_argument("--keep", action="store_true", help="leave the last configuration applied")
    parser.add_argument("--report", help="write the results as JSON to this file")
    args = parser.parse_args(argv)
    toggle = json.load(open(args.toggle_script)) if args.toggle_script else None
    frame = Frame(args.host)
    results: dict[str, list[Check]] = {}
    try:
        for name in args.configs:
            results[name] = trial(frame, name, args.soak, toggle)
    finally:
        if not args.keep and not restore(frame):
            print("WARNING: could not confirm Android booted on the baseline", file=sys.stderr)
    print()
    failed = False
    for name, checks in results.items():
        print(f"[{name}]")
        for check in checks:
            failed |= not check.ok
            print(f"  {'PASS' if check.ok else 'FAIL'}  {check.name}: {check.detail}")
            if check.diagnostics:
                print("    " + check.diagnostics.replace("\n", "\n    ")[:6000])
    if args.report:
        with open(args.report, "w") as out:
            json.dump({n: [c.__dict__ for c in cs] for n, cs in results.items()}, out, indent=1)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
