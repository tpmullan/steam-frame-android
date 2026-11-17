# Debugging on the Frame (for agents)

Read this before you ask the user to do anything on the device.

## Rules of engagement

- You have the device. `ssh "$FRAME_HOST"` works (`FRAME_HOST=USER@FRAME`, the Frame account the harness uses), Android is a
  rootless podman container (`waydroid-gapps`), and you may restart SteamVR and
  Android whenever you need to. The user said so and does not want to be asked.
- Do not stop and wait for the user to move, hold, stand or reposition the headset.
  Work around it in software: simulated controllers, head-relative aiming,
  SteamVR's own reset and calibrate functions, Wolvic intents, logs.
- If you are blocked, search the web and the upstream source (GitHub) first. Ask the
  user only after research and several different approaches have failed, and say what
  you tried.
- Prove things with automation that runs unattended and reports pass/fail, including
  a positive control (the test must fail when the bug is present).

## Reaching things

| Need | Command |
|---|---|
| Host shell | `ssh "$FRAME_HOST"` |
| Android shell | `podman exec waydroid-gapps sh -c '...'` (the `Frame.android()` helper in `tools/gpu-trial.py`) |
| Logs | `logcat -d \| grep ...` in Android; `journalctl --user` on the host |
| SteamVR CLI | `/opt/steamvr/bin/linuxarm64/vrcmd` (use `timeout` with `--showevents`) |
| Start Android | through its Steam entry (`steam://rungameid/<id from Frame.steam("game")>`) |

## SteamVR facts that cost hours

- A scene app stays VISIBLE, not FOCUSED, while a game-theater "Resume Game" menu or a
  stale second scene app holds it. Set `dashboard.autoShowGameTheater 0` with
  `vrcmd --set-settings-bool` and force-stop leftover apps (`hello_xr`).
- LG+RG (both grips) toggles the laser mouse; the system button toggles the dashboard.
- **Set the play space first.** Symptom: passthrough camera with "Camera enabled outside
  playspace" and no app visible. There is a button (SteamVR dashboard, Settings, Quick
  Calibrate) and an API: `vrcmd --resetroomsetup` (and `vrcmd --resetroomheight`,
  `vrcmd --recenter`) on the host, no human needed. Verified 2026-11-16: it brought
  Wolvic into view with the headset lying face down. The mailbox
  `quick_reset_room_setup` message did not.
- (older note) "Camera enabled outside playspace": Quick Calibrate through the mailbox websocket
  (`quick_reset_room_setup`). Each SteamVR restart makes a new universe, so calibrate
  after the restart and after launching the app.
- The Frame has a real IMU. When it lies face down the HMD roll is about 180 degrees:
  screenshots are upside down and windows placed "in front" land somewhere else.

## Simulated controllers (full-stack input)

Use them. They are real SteamVR devices (`frame_controller`, the same profile as the
Frame's own controllers), so SteamVR, OpenXR apps and Wolvic cannot tell them from
hardware. Source: `runtime-rust/xr-sim/steamvr-driver` in the engine repo, with the
build and register steps in `runtime-rust/xr-sim/README.md`. Registered on the Frame
under `~/xrsim-driver/xrsim` (`vrpathreg.sh adddriver`); SteamVR must be restarted to
load a new build (`scratchpad` helper `restack.py` does it, then starts Android again
through its Steam entry).

Control them by writing one line to a file on the Frame (the driver re-reads it every
8 ms; the last non-empty line wins):

| Hand | File | Serial |
|---|---|---|
| right | `/tmp/xr-sim-input` | XRSIM-0001 |
| left | `/tmp/xr-sim-input-left` | XRSIM-0002 |

    x y z yaw pitch trigger grip stick [buttons [head]]

- `x y z` metres, `yaw pitch` degrees (positive yaw turns left; with the head modes
  below, pitch positive aims down-ish when the headset is rolled, so measure, do not guess).
- `trigger grip` are 0/1 (above 0.5 = pressed), `stick` is the thumbstick Y (-1..1).
- `buttons` is a bitmask: bit0 system, 1 menu, 2 view, 3 a, 4 b, 5 x, 6 y, 7-10 dpad
  up/right/down/left, 11 bumper, 12 thumbstick click.
- `head` (10th number): `0` world space (raw tracking space, 1.6 m above the standing
  floor, so head height is `y = -0.1`), `1` relative to the headset's heading, `2` rigid
  with the headset (offset and aim in the headset's own frame, so a tilted or rolled
  headset does not matter; this is the one to use when the headset is not on a head).
- Clicks: hold `trigger=1` for about 0.15 s. 0.6 s is a long press (Wolvic and YouTube
  open a context menu). Both grips together toggle SteamVR's laser mouse.
- The beam, a hit dot and the controller model show in `r0shot.py` stereo screenshots,
  which is how to see where you are aiming: measure how a yaw and a pitch step move the
  hit dot, then solve for the target (two or three iterations).
- Park the hand you do not use at `0 0 0 0 0 0 0 0 0 0`.

## Driving Wolvic with the simulated controller (the recipe that works)

1. Launch Wolvic, wait for FOCUSED, then run `vrcmd --resetroomsetup`. Wolvic re-places its
   windows in front of the headset, so the pose you measure is the pose you replay. It also
   opens SteamVR's menu over the app, so follow it with `vrcmd --hidedashboard` a few times
   (the window is hidden until you do).
2. Put the hand rigid with the headset (`head=2`) and aim by measurement, not by looking:
   serve `tools/frame-hover.html`, open it in Wolvic, run `tools/frame-aim-sweep.py` on the
   Frame. Measured 2026-11-16 with the hand at `0.2 -0.25 -0.3`: the page is 1024x576,
   x = 535 - 15.6 * yaw and y = 494 - 17.7 * (pitch - 10), about; yaw 12 and pitch 24.6 hit
   the centre of the YouTube player.
3. A double click (trigger 0.12 s down, 0.12 s up, twice) on the player enters fullscreen.
   `B` (buttons = 16) leaves it. Logcat proves both: `GeckoView:DOMFullscreenEntered` and
   `GeckoView:DOMFullscreenExited`. `tools/wolvic-fullscreen-sim.json` is this sequence and
   `tools/gpu-trial.py <config> --toggle-script` fails when the page never entered fullscreen.
4. Fallbacks if you cannot aim: Wolvic intents (`launch_immersive*`), Gecko remote debugging.

## Evidence to collect

`logcat | grep -E 'Average Frame Rate'` gaps (the 360 freeze shows as a gap over ~3 s),
`pidof` for crashes, tombstones under `/data/tombstones`, `window N held:` lines from
`rs.starforge.xrhost` for panel poses, `r0shot.py` stereo screenshots (delete them
afterwards; do not leave user screenshots around).

## Recentring a 360 video

`tools/frame-chaperone.py` (run on the Frame) reads and rotates SteamVR's zero poses through the chaperone
API: `get|yaw DEGREES [seated]`. Rotating the seated pose is a way to change the heading offset of a headset
you cannot move. Wolvic only reorients on a reference-space change while it is in StandAlone render mode;
the equirect layer then follows `reorientMatrix` (`DeviceDelegateOpenXR.cpp`). Check on the Frame
(2026-11-16, `tools/xr-fixtures`): after a 90 degree seated-pose change, and again after the system-button
recentre, Wolvic logged `reference space changed` and the sphere stayed centred on the headset's heading
(cyan|blue edge straight ahead in the SteamVR screenshot). The Frame's screenshots of a YouTube 360 clip in
fullscreen were black with and without the hardware decoder; use the local clip for visual checks.

## Hardware video decode (optional, unstable, in testing)

The SoC's V4L2 decoder (iris, `/dev/video-dec0` = `/dev/video22`: H.264, HEVC, VP9 up to 8192x8192) is usable
from Android through a Codec2 V4L2 service built from AOSP `external/v4l2_codec2` with six patches
(`tools/v4l2-codec2/`, README there). It is an optional add-on in the release: `wgapps hwdec install` (or
`wgapps install --hwdec`) unpacks and checks it into `~/.local/share/waydroid-gapps/lib/v4l2-codec2` and turns it
on; `wgapps hwdec status|on|off|remove` manage it, and `wgapps start` mounts it into the container when it is on and
the decoder node is usable. Without it Android has only Google's software codecs (VP9 capped at 2048x2048), which is
why YouTube stops at 1080p. `tools/decode-check.py` is the acceptance test (host decoder, container node, Android's
codec list, and a 4K clip played in Chrome that must use `c2.v4l2.vp9.decoder` while the iris interrupt counter
climbs). Debugging it: see the README there (strace inside the container, the kernel's `qcom-iris` messages,
`v4l2-ctl` on the host).

**It can crash the machine.** A `qcom-iris ... received system error of type 0x5000003` in `journalctl -k`, followed
by `Unable to handle kernel paging request`, rebooted a Frame about a minute after Android started (2026-11-17). If
the Frame reboots after starting Android, read `journalctl -b -1 -k` and turn the add-on off (`wgapps hwdec off`)
before anything else. Do not start Android on a Frame you are about to leave unattended while this is unexplained.

## Render resolution (why OpenXR apps looked soft)

SteamVR's log (`~/.local/share/Steam/logs/vrcompositor.txt`) says `HMD driver recommended: 2160x2160 90.0Hz`,
`Raw ideal render target scale = 0.64`, then `GetRecommendedRenderTargetSize for current app: 1728x1728`. The 0.64
is SteamVR's stored GPU-speed result for this Adreno (`GpuSpeed.gpuSpeedRenderTargetScale`, horsepower 450).
Setting `steamvr.supersampleManualOverride`/`supersampleScale` or `GpuSpeed.gpuSpeedManualOverride`/`...Scale`
(with `vrcmd --set-settings-*`, and after a SteamVR restart) does not change the recommendation on this build.
Wolvic builds its swapchains from `recommendedImageRectWidth/Height` alone, so the fix is our OpenXR layer:
`debug.xr.render_scale` (`wgapps xr scale`, default 1.25) enlarges the recommendation. Check it with
`logcat | grep wgapps-xr-gles` ("render scale 125%: recommended view width 1728 -> 2160") and the frame rate
with `logcat | grep "Average Frame Rate"`.

## A frozen Wolvic after leaving fullscreen

`tools/gpu-trial.py --toggle-script FILE baseline` repeats fullscreen exits unattended; it prints its verdict
only at the end, so progress shows as Wolvic launches in `logcat -b events` (`am_proc_start`, about 2 minutes
each). When it sees a gap of 8 s or more in Wolvic's frame logs it saves a `debuggerd -b` stack dump and the
log tail as `wolvic-freeze-*.txt` in the temp directory. The known cause is Mesa's buffer-age query
(`libwgapps_egl_layer.so` works around it, see the README); a dump with a thread in `eglQuerySurface` is that
one again, anything else is a new bug.
