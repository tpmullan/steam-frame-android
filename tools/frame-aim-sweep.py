"""Runs ON the Frame (`python3 - [yaw pitch] < tools/frame-aim-sweep.py`). Finds where to aim the
simulated right controller so it points at a given spot on the page Wolvic shows.

Serve tools/frame-hover.html from the Frame (`cd /tmp/hover && python3 -m http.server 8099
--bind 0.0.0.0 > /tmp/hover/log.txt`) and open http://172.20.0.1:8099/hover.html in Wolvic
(172.20.0.1 is the Frame as the Android container sees it). The page reports each pointer position
to the server log. The hand rides rigidly with the headset (tenth number 2) at 0.2 -0.25 -0.3.

With a starting `yaw pitch` it tries that first; otherwise it sweeps the whole sphere in coarse
steps (the window is about 66 x 33 degrees) until the page sees the pointer. It then steers to
TARGET (page pixels, the middle of YouTube's player on a 1024 x 576 page) using the measured
15.6 px per degree of yaw and 17.7 px per degree of pitch. Prints one JSON line:
{"aim": [yaw, pitch], "hit": [x, y]} or {"error": ...}.
"""

import json
import re
import sys
import time

LOG = "/tmp/hover/log.txt"
INPUT = "/tmp/xr-sim-input"
TARGET = (348, 236)
PX_PER_YAW, PX_PER_PITCH = -15.6, -17.7  # page x per degree of yaw, page y per degree of pitch


def probe(yaw, pitch):
    """Point at (yaw, pitch) and return the page position the pointer landed on, or None."""
    with open(INPUT, "w") as f:
        f.write(f"0.2 -0.25 -0.3 {yaw:.2f} {pitch:.2f} 0 0 0 0 2\n")
    time.sleep(0.5)
    seen = len(open(LOG).read().splitlines())
    time.sleep(0.6)
    for line in reversed(open(LOG).read().splitlines()[seen:]):
        m = re.search(r"/m\?x=(\d+)&y=(\d+)", line)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def find(start):
    if start:
        hit = probe(*start)
        if hit:
            return start, hit
    for pitch in range(-90, 91, 20):
        for yaw in range(-180, 180, 30):
            hit = probe(yaw, pitch)
            if hit:
                return (yaw, pitch), hit
    return None, None


def main():
    start = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) >= 3 else None
    (yaw, pitch), hit = find(start)
    if not hit:
        print(json.dumps({"error": "the pointer never landed on the page"}))
        return 1
    for _ in range(5):
        ex, ey = TARGET[0] - hit[0], TARGET[1] - hit[1]
        if abs(ex) < 20 and abs(ey) < 20:
            break
        yaw += ex / PX_PER_YAW
        pitch += ey / PX_PER_PITCH
        again = probe(yaw, pitch)
        if not again:
            print(json.dumps({"error": f"steering left the page at {yaw:.1f} {pitch:.1f}"}))
            return 1
        hit = again
    print(json.dumps({"aim": [round(yaw, 1), round(pitch, 1)], "hit": list(hit)}))
    return 0


sys.exit(main())
