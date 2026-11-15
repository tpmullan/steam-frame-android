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
import re
import shlex
import subprocess
import sys
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


def wolvic(frame: Frame, soak: float) -> Check:
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
    ok = alive and worst < 8
    return Check(
        "wolvic 360 video",
        ok,
        f"alive={alive}; longest gap in frame logs {worst:.0f} s over {soak:.0f} s",
    )


def run_checks(frame: Frame, soak: float) -> list[Check]:
    checks = []
    renderer = frame.android("dumpsys SurfaceFlinger | grep -m1 '^GLES'")
    checks.append(Check("boot and GLES driver", bool(renderer), renderer or "no GLES line"))
    before = newest_tombstone(frame)
    stop_apps(frame)
    checks.append(draws(frame, "settings draws", "com.android.settings/.Settings"))
    checks.append(
        draws(frame, "chrome draws", "com.android.chrome/com.google.android.apps.chrome.Main")
    )
    checks.append(draws(frame, "plex draws", "com.plexapp.android/tv.plex.app.MainActivity"))
    stop_apps(frame)
    checks.append(hello_xr(frame, "hello_xr OpenGL ES", HELLO_GLES))
    checks.append(hello_xr(frame, "hello_xr Vulkan", HELLO_VULKAN))
    checks.append(wolvic(frame, soak))
    stop_apps(frame)
    after = newest_tombstone(frame)
    checks.append(
        Check("no new native crash", after == before, f"newest tombstone {before} -> {after}")
    )
    return checks


def trial(frame: Frame, name: str, soak: float) -> list[Check]:
    log(f"== {name}: applying and restarting Android")
    apply_config(frame, name)
    if not restart_android(frame):
        return [Check("boot and GLES driver", False, "Android did not boot")]
    return run_checks(frame, soak)


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
    parser.add_argument("--keep", action="store_true", help="leave the last configuration applied")
    parser.add_argument("--report", help="write the results as JSON to this file")
    args = parser.parse_args(argv)
    frame = Frame(args.host)
    results: dict[str, list[Check]] = {}
    try:
        for name in args.configs:
            results[name] = trial(frame, name, args.soak)
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
