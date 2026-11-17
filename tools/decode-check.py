#!/usr/bin/env python3
"""Hardware video decode checks for the Frame (integration test, runs against the real device).

Three layers, each a check:
  1. host     the SoC's V4L2 decoder (iris, /dev/video-dec0) decodes a generated 4K VP9 clip at real time
  2. container the Android container can open a V4L2 decoder node
  3. android  Android's MediaCodecList (dumpsys media.player) offers a hardware, non-software decoder for
              VP9 at 3840x2160 (and says which decoders it has, so a failure shows what is missing)
  4. playback Chrome in Android plays a generated 4K VP9 clip: the V4L2 decoder is the one chosen, the
              Codec2 service survives, and the iris decoder takes interrupts while the video plays

Layers 2 to 4 fail until a Codec2 V4L2 component store is installed in Android (README "Known limits").
Usage: FRAME_HOST=steamos@frame python3 tools/decode-check.py
Exit status is 1 when any check fails.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import sys
import time
from dataclasses import dataclass

CLIP = "/tmp/wgapps-decode-4k.webm"
CLIP_FRAMES = 60  # 2 s at 30 fps


@dataclass
class Decoder:
    mime: str
    name: str
    software_only: bool = False
    hw_accelerated: bool = False
    max_width: int = 0
    max_height: int = 0

    @property
    def hardware(self) -> bool:
        return self.hw_accelerated or not self.software_only


def parse_decoders(dump: str) -> list[Decoder]:
    """The decoders in `dumpsys media.player` ("Decoder infos by media types" up to the encoders)."""
    decoders: list[Decoder] = []
    mime = ""
    current: Decoder | None = None
    for line in dump.split("Encoder infos by media types")[0].splitlines():
        if match := re.match(r"Media type '([^']+)':", line):
            mime, current = match.group(1), None
        elif match := re.match(r'\s+Decoder "([^"]+)" supports', line):
            current = Decoder(mime, match.group(1))
            decoders.append(current)
        elif current is None:
            continue
        elif match := re.match(r"\s+software-only: (\d)", line):
            current.software_only = match.group(1) == "1"
        elif match := re.match(r"\s+hw-accelerated: (\d)", line):
            current.hw_accelerated = match.group(1) == "1"
        elif match := re.search(r'size-range = "\d+x\d+-(\d+)x(\d+)"', line):
            current.max_width, current.max_height = int(match.group(1)), int(match.group(2))
    return decoders


def hardware_decoders(decoders: list[Decoder], mime: str, width: int, height: int) -> list[Decoder]:
    return [
        d
        for d in decoders
        if d.mime == mime and d.hardware and d.max_width >= width and d.max_height >= height
    ]


def describe(decoders: list[Decoder], mime: str) -> str:
    found = [
        f"{d.name} ({'software' if not d.hardware else 'hardware'}, up to {d.max_width}x{d.max_height})"
        for d in decoders
        if d.mime == mime
    ]
    return "; ".join(found) or "none"


def iris_interrupts(proc_interrupts: str) -> int | None:
    """Total interrupts of the iris video codec in /proc/interrupts (summed over CPUs), or None.

    A line is "<irq>: <count per CPU>... <controller> <hwirq> <trigger> <name>": only the run of
    integers right after the colon are counts."""
    for line in proc_interrupts.splitlines():
        if "iris" not in line or ":" not in line:
            continue
        total, seen = 0, False
        for token in line.split(":", 1)[1].split():
            if not token.isdigit():
                break
            total += int(token)
            seen = True
        return total if seen else None
    return None


def codec_chosen(log: str, name: str = "c2.v4l2.vp9.decoder") -> bool:
    """Chrome's MediaCodec bridge logged creating the decoder `name` for VP9."""
    return any(
        "create MediaCodec video decoder" in line and f"decoder name {name}" in line
        for line in log.splitlines()
    )


def component_died(log: str) -> bool:
    return bool(re.search(r"Codec2 component .* died|Fatal signal", log))


def decode_result(output: str, want_frames: int) -> tuple[bool, str]:
    """Judge ffmpeg's final progress line: all frames decoded at least as fast as real time."""
    frames = [int(n) for n in re.findall(r"frame=\s*(\d+)", output)]
    speeds = re.findall(r"speed=\s*([\d.]+)x", output)
    if not frames or not speeds:
        last = output.strip().splitlines()[-1][:200] if output.strip() else "no output"
        return False, "ffmpeg printed no progress: " + last
    speed = float(speeds[-1])
    ok = frames[-1] >= want_frames and speed >= 1.0
    return ok, f"decoded {frames[-1]} frames (needs {want_frames}) at {speed:.1f}x real time"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def load_frame_class():
    here = pathlib.Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("gpu_trial", here / "gpu-trial.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gpu_trial"] = module
    spec.loader.exec_module(module)
    return module


def host_decode(frame) -> Check:
    node = frame.run("readlink -f /dev/video-dec0 2>/dev/null").strip()
    if not node:
        return Check("host hardware decoder", False, "no /dev/video-dec0 (iris driver not loaded)")
    made = frame.run(
        f"ffmpeg -y -hide_banner -loglevel error -f lavfi -i testsrc2=size=3840x2160:rate=30 -t 2 "
        f"-c:v libvpx-vp9 -b:v 8M -deadline realtime -cpu-used 8 {CLIP} && echo made"
    )
    if "made" not in made:
        return Check(
            "host hardware decoder",
            False,
            "could not make the 4K VP9 test clip: " + made.strip()[-200:],
        )
    # -progress prints plain "frame=N" and "speed=Nx" lines; ffmpeg's V4L2 wrapper can trip an assertion
    # while shutting down, after every frame was decoded, so the exit status says nothing.
    out = frame.run(
        f"ffmpeg -hide_banner -nostats -progress pipe:1 -c:v vp9_v4l2m2m -i {CLIP} -f null - 2>/dev/null; "
        f"rm -f {CLIP}",
        timeout=180,
    )
    ok, detail = decode_result(out, CLIP_FRAMES)
    return Check("host hardware decoder", ok, f"{node}: 4K VP9, {detail}")


def container_node(frame, container: str = "waydroid-gapps") -> Check:
    out = frame.run(f"podman exec {container} sh -c 'ls /dev/video* 2>/dev/null' || true").strip()
    return Check(
        "android container sees a V4L2 node",
        bool(out),
        out.replace("\n", " ") if out else "no /dev/video* inside the container",
    )


def android_decoder(frame) -> Check:
    dump = frame.android("dumpsys media.player")
    decoders = parse_decoders(dump)
    hardware = hardware_decoders(decoders, "video/x-vnd.on2.vp9", 3840, 2160)
    if hardware:
        return Check(
            "android offers a hardware 4K VP9 decoder", True, ", ".join(d.name for d in hardware)
        )
    return Check(
        "android offers a hardware 4K VP9 decoder",
        False,
        "VP9 decoders: " + describe(decoders, "video/x-vnd.on2.vp9"),
    )


PLAY_DIR = "/tmp/wgapps-decode-play"
PLAY_PORT = 8101
PLAY_SECONDS = 4
MIN_INTERRUPTS = (
    100  # a playing 4K clip gave about 280 in 4 s; a started but idle decoder gives a few
)


def android_playback(frame, container: str = "waydroid-gapps") -> Check:
    """Play a generated 4K VP9 clip in Chrome inside Android and watch the decoder work."""
    name = "android decodes 4K VP9 on the hardware"
    made = frame.run(
        f"mkdir -p {PLAY_DIR} && cd {PLAY_DIR} && ffmpeg -y -hide_banner -loglevel error -f lavfi "
        "-i testsrc2=size=3840x2160:rate=30 -t 8 -c:v libvpx-vp9 -b:v 10M -deadline realtime "
        "-cpu-used 8 -pix_fmt yuv420p t4k.webm && echo made"
    )
    if "made" not in made:
        return Check(name, False, "could not make the test clip: " + made.strip()[-160:])
    frame.run(
        f"ss -ltn | grep -q ':{PLAY_PORT} ' || (cd {PLAY_DIR} && exec setsid python3 -m http.server "
        f"{PLAY_PORT} --bind 0.0.0.0) >/dev/null 2>&1 </dev/null & sleep 1"
    )
    url = f"http://172.20.0.1:{PLAY_PORT}/t4k.webm"  # the Frame, as the container sees it
    size = re.search(r"(\d+)x(\d+)", frame.android("wm size"))
    width, height = (int(size.group(1)), int(size.group(2))) if size else (1920, 1080)
    frame.android(
        f"logcat -c; am force-stop com.android.chrome; am start -a android.intent.action.VIEW -d {url} "
        "-n com.android.chrome/com.google.android.apps.chrome.Main >/dev/null"
    )
    time.sleep(8)  # the page loads; the first frame is decoded and the player waits paused
    service = frame.android("pidof android.hardware.media.c2@1.0-service-v4l2-64").strip()
    before = iris_interrupts(frame.run("cat /proc/interrupts"))
    frame.android(f"input tap {width // 2} {height * 8 // 15}")  # the player's play button
    time.sleep(PLAY_SECONDS)
    after = iris_interrupts(frame.run("cat /proc/interrupts"))
    log = frame.android("logcat -d")
    alive = frame.android("pidof android.hardware.media.c2@1.0-service-v4l2-64").strip()
    frame.android("am force-stop com.android.chrome")
    delta = None if before is None or after is None else after - before
    detail = f"interrupts during {PLAY_SECONDS} s of playback: {delta}; service {'kept' if alive == service else 'restarted'}"
    if not codec_chosen(log):
        return Check(name, False, "Chrome did not use c2.v4l2.vp9.decoder; " + detail)
    if component_died(log) or not alive or alive != service:
        return Check(name, False, "the codec service died; " + detail)
    if delta is None or delta < MIN_INTERRUPTS:
        return Check(name, False, "the iris decoder did not work; " + detail)
    return Check(name, True, detail)


def main() -> int:
    host = os.environ.get("FRAME_HOST")
    if not host:
        print("set FRAME_HOST=USER@FRAME", file=sys.stderr)
        return 2
    frame = load_frame_class().Frame(host)
    checks = [host_decode(frame), container_node(frame), android_decoder(frame)]
    if all(c.ok for c in checks):  # playback needs the first three
        checks.append(android_playback(frame))
    for check in checks:
        print(f"  {'PASS' if check.ok else 'FAIL'}  {check.name}: {check.detail}")
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
