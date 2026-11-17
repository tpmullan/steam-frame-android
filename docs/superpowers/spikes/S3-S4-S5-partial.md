# S3, S4, S5: what was measured on 2026-11-14, and what is still open

Frame state after the runs: no overlay display, no test props, no temp files, container untouched
(same start time as before). The fake-worn shim was left as it was.

## S3: session handoff and panel coexistence (partly answered)

- hello_xr (Vulkan) started with `am start` while the Android panel was up. Session states in
  logcat: UNKNOWN > IDLE > READY (about 2.5 s after `am start`) > SYNCHRONIZED > VISIBLE (0.4 s
  later). It stays VISIBLE, not FOCUSED, while SteamVR's dashboard is open (known: `vrcmd
  --hidedashboard`).
- Stereo screenshot while hello_xr ran: the **Android panel is a separate SteamVR overlay that stays
  visible next to a running OpenXR app**, with the dashboard and window controls on top. So a flat
  panel can coexist with a scene app at the SteamVR level.
- Not answered: hello_xr's own scene was hidden because SteamVR forced the room view ("Camera enabled
  outside playspace"; the saved play space does not match where the headset lay). Showing both
  together, input routing, and the end-one/start-another timing (steps 1-2) need a Quick Calibrate
  (it rewrites `chaperone_info.vrchap`) and a person in or at the headset; not done without asking.
- Decision so far: design the shell as one OpenXR session that ends when it launches an XR app, and
  keep the flat panel available beside it. Confirm with the steps above before Task V1.

## S4: 2D app into a 3D quad (Android side answered, pixel path open)

- Android in this container supports a second display: `settings put global
  overlay_display_devices "1280x720/240"` creates display 2 (`type OVERLAY`, a SurfaceFlinger virtual
  display, layerStack 2), and `am start --display 2 -n com.android.settings/.Settings` runs Settings
  there (`topResumedActivity` on Display #2). The setting was deleted again.
- `screencap -d` of that display wrote an empty file, so overlay displays cannot be read this way.
  Getting pixels needs the real route: an app creating a `VirtualDisplay` onto its own `Surface`
  (`ImageReader` or `SurfaceTexture`), not tested (needs a native or Java test app, `spikes/quad2d/`).
- The runtime's extension list (read from `vrclient.so`) has no cylinder, equirect or other layer
  extensions. A quad is a core OpenXR layer and not tested here; the plan must not assume it
  until the test app tries it. Fallback that needs nothing new: the shell draws each window as a
  textured quad inside its own projection layer.
- Decision so far: V2 stays gated on the test app; no V2 work should start before it shows pixels.

## S5: passthrough (answered as far as the runtime goes)

- `xrEnumerateEnvironmentBlendModes` from SteamVR on the Frame: **OPAQUE and ALPHA_BLEND** (hello_xr
  logs "count 2").
- The runtime's extension strings include no passthrough extension (no `XR_FB_passthrough`, no
  `XR_HTC_passthrough`, no `XR_META_*passthrough*`); it does list `XR_EXT_user_presence`,
  `XR_FB_display_refresh_rate`, `XR_FB_foveation*`, hand tracking and eye gaze.
- Whether ALPHA_BLEND with a transparent clear shows the cameras was **not** tested: hello_xr on
  Android ignores `debug.xr.blend_mode` and `debug.xr.blendmode` (it stayed OPAQUE), and the room
  view that was up in the screenshot is SteamVR's own, not an app's.
- Decision for V4: first try an override in `xr-layer/` that sets `environmentBlendMode` to
  `ALPHA_BLEND` in `xrEndFrame` (a property-gated change of about 25 lines, host-testable), with a
  transparent clear; if the compositor does not blend, advertise `XR_FB_passthrough` in the layer and
  draw the camera feed (`/dev/video99`) ourselves. Costs: the first is small and needs no new
  surface; the second is a new extension implementation plus a camera path.

## Update: S3 run after Quick Calibrate (2026-11-14, later)

- The play space was reset with Quick Calibrate once the headset was lifted off fabric (the old
  chaperone file was copied first and the copy was deleted afterwards). SteamVR restarted around it and
  the Android container stopped; relaunching the Android entry brought it back.
- hello_xr (Vulkan): UNKNOWN > IDLE > READY > SYNCHRONIZED > VISIBLE > FOCUSED; the stereo screenshot
  shows its cube scene (background and cube colours as before). With the app focused the Android
  panel is not in the scene screenshot.
- After `am force-stop` of hello_xr, the screenshot shows the Android home panel in the room view
  again, no black frames or stuck dashboard.
- Wolvic after hello_xr: READY 0.2 s after `am start`, VISIBLE immediately, FOCUSED 7.6 s later
  (its own start-up). About 3 s passed between ending one app and the next session being READY.
- S3 decision: the shell can be one session that ends when it launches an XR app and is started again
  afterwards; the flat panel returns on its own when no scene app runs, so it needs no hiding for that
  case. Still untested: the panel beside a running scene app (the screenshot tool shows only the app).
- S4 evidence: Wolvic itself creates an Android virtual display ("OffscreenViews Overlay", logged by
  DisplayDeviceRepository) in this container, so Android `VirtualDisplay` creation works here.
- User report, same day: Wolvic works as a browser in VR but looks grainy, and a 3D video crashed it.
  Grain is not SteamVR's scale: `steamvr.supersampleScale` is 1.0 and Wolvic's swapchain is 1728x1728
  per eye either way (measured with the override on and off; the override is off again). The crash
  has no log yet (an old tombstone is the graphics composer's, from the SteamVR restart); it needs a
  reproduction with `logcat` running.

## Wolvic 360-video freeze (user repro, 2026-11-14 11:39-11:41)

Not a crash: Wolvic's process stayed alive, its frames stopped (SteamVR showed "Waiting...", last
"Average Frame Rate" log 11:39:42, a few seconds after leaving fullscreen of a YouTube 360 video).
A native stack dump (`debuggerd -b`) of the frozen process shows a lock cycle inside Mesa's EGL
(`libEGL_mesa.so`, the Waydroid image's):
- "Renderer" (Gecko compositor) is in `eglQuerySurface` > `ANativeWindow_dequeueBuffer` >
  `BufferQueueProducer::waitForFreeSlotThenRelock`: it waits for a free buffer while Mesa still holds
  its EGL display lock.
- "VRB Render" (Wolvic's render thread, the consumer that would release the buffer) is in
  `SurfaceTexture.updateTexImage` > `eglCreateSyncKHR` (Mesa), and "RenderThread" and a Gecko thread
  (`eglChooseConfig`) wait on the same lock.
So the buffer is only released by a thread that needs the lock held by the thread waiting for the
buffer: a deadlock. This matches a known shape of Mesa's Android EGL: `eglQuerySurface` (buffer age)
dequeues a buffer while holding the display mutex. It is in the image's Mesa, not in this repo, and
not in Wolvic. Candidates: patch Mesa's `droid_query_buffer_age` not to block, hide
`EGL_EXT_buffer_age` from Wolvic's Gecko through a per-app preload (the `wrap.<package>` mechanism
that carries `libwgapps_props.so`), or raise the surface's buffer count. None built yet. The raw
log is kept in the session scratchpad (`wolvic-repro.log`). Grain: see above; not the SteamVR scale.

### Follow-up checks on the freeze (same day)
- The image's Mesa is 26.0.8 (read from `vulkan.freedreno.so`). The GLES driver in use is native
  freedreno ("GLES: freedreno, FD750, OpenGL ES 3.2 Mesa 26.0.8"), and `EGL_EXT_buffer_age` is
  advertised. Lepton's default adds `mesa.loader.driver.override=zink` and
  `mesa.libgl.kopper.disable=true`; this image's `libgallium_dri.so` contains Zink.
- Setting those two as Android properties (device.prop) makes SurfaceFlinger crash-loop and Android
  never finishes booting (bootanimation segfault in `SurfaceControl`). Reverted, Android boots normally
  again. So Lepton's Zink route does not work here as a global switch (it needs Lepton's own image).
- The Waydroid Mesa fork has branches only up to 25.3, so the 26.0.8 code was not read; the 25.x code
  has the behaviour described above.
- Not yet tried: `debug.stagefright.ccodec=0`, ANGLE as the EGL (`ro.hardware.egl=angle`,
  `ro.hardware.vulkan=freedreno`), and a preload hiding `EGL_EXT_buffer_age` from Wolvic.

### Automated GPU trial (tools/gpu-trial.py, 2026-11-14)
`tools/gpu-trial.py CONFIG...` applies a configuration (`baseline`, `ccodec0`, `angle`), restarts Android
through its Steam entry, runs a checklist (boot and GLES driver, Settings/Chrome/Plex draw, hello_xr GLES
and Vulkan reach FOCUSED and keep presenting, Wolvic on the 360 video page stays alive and logging
frames for `--soak` seconds, no new tombstone), and restores the baseline. A new launcher switch,
`wgapps gpu egl mesa|angle` (`$BASE/gpu-egl`), exists because an `ro.hardware.egl` line in
device.prop cannot override the one `write_props` already sets.
- baseline: all 8 checks pass (about 1.5 min).
- angle (`ro.hardware.egl=angle`): boots, GLES is "ANGLE (Qualcomm, Vulkan 1.4.335 (Turnip Adreno 750),
  turnip Mesa driver-26.0.8), OpenGL ES 3.1"; Settings, Chrome, Plex draw; hello_xr Vulkan passes;
  **hello_xr OpenGL ES never reaches FOCUSED**; Wolvic stayed alive for 45 s with at most 1 s between
  frame logs; no new tombstone. The soak does not send the fullscreen toggle that triggered the freeze,
  so that pass proves less than a person's repro. Reason for the hello_xr GLES failure not yet
  looked into (our xr-layer assumes Mesa's GLES formats; ANGLE's swapchain/format path differs).
- ccodec0 not run yet. The baseline was restored after each run.

### Trial data, 2026-11-14 (three runs, raw output in the session scratchpad: trial-*.txt/json)
| check | baseline | ccodec0 | angle |
|---|---|---|---|
| boot, GLES driver | Mesa freedreno FD750, GLES 3.2 | same | ANGLE on Turnip, GLES 3.1 |
| Settings, Chrome, Plex draw | pass | pass | pass |
| hello_xr OpenGL ES | pass (293 frames/4 s) | pass (293) | **fail: app crashes** |
| hello_xr Vulkan | pass (291) | pass (292) | pass (293) |
| Wolvic 360 page, frame logs 20-60 s | alive, gap 1 s | alive, gap 1 s | alive, gap 1 s |
| new tombstone | none | none | yes (hello_xr) |
- The soak does not trigger the freeze (that needs the fullscreen toggle by hand), so none of the three
  runs says whether `ccodec0` or ANGLE removes it. A person's repro on each is still needed.
- angle, hello_xr OpenGL ES: SIGSEGV (null fault address 0x0, thread "Thread-2", in the app's own
  code under `android_main`) 13 ms after ANGLE reports "Version 2.1.20440 ... Renderer (Vulkan 1.4.335
  (Turnip Adreno 750))"; just before it, libEGL logs `validate_display:568 error 3001
  (EGL_NOT_INITIALIZED)`. hello_xr's OpenGL ES plugin gets an EGL display or context the ANGLE EGL did
  not initialise (the OpenXR runtime or our layer touches EGL first). Not investigated further.
- Harness bug found and fixed: the "no new native crash" check counted tombstones, but Android keeps
  at most 50, so the count never changes; it now compares the newest tombstone name, and caught
  the angle crash.
- ccodec0 changes nothing the harness measures; its effect on video decoding is untested.

## 360 video freeze on ANGLE (user repro, 2026-11-15)

Config `angle` (`wgapps gpu egl angle`, GLES via ANGLE on Turnip). Wolvic opened the
360 test video, the user played it, went fullscreen and left fullscreen. Result per
the user: working, no freeze. The frame log's longest gap over an 8 minute watch was
1 s (baseline froze about 3 s after leaving fullscreen every time).

One run by one person. Not yet tried: `ccodec0` alone. The remaining cost of ANGLE is
the hello_xr OpenGL ES crash (above); Wolvic, Chrome, Settings, Plex and hello_xr Vulkan
pass on it.

## Why hello_xr OpenGL ES crashes on ANGLE

Symbolized the tombstone (`llvm-symbolizer` on the APK's `libhello_xr.so`, pc 0x98c08):
the app calls `glad_glDebugMessageCallback`, a GLAD-loaded function pointer that is NULL,
right after `glEnable(GL_DEBUG_OUTPUT)`. It is core in OpenGL ES 3.2; ANGLE on Turnip
reports ES 3.1 and only exposes `glDebugMessageCallbackKHR`. The sample assumes 3.2 and does
not check. Mesa freedreno reports 3.2, so it works there.

Forcing ANGLE to expose 3.2 (`setprop debug.angle.feature_overrides_enabled
exposeNonConformantExtensionsAndVersions`, a testing feature in ANGLE) removes the crash,
but the run then stops at `xrCreateSwapchain` for the depth swapchain with
`XR_ERROR_RUNTIME_FAILURE`: SteamVR's runtime fails to share the depth image with ANGLE's
EGL/GL. Color-only swapchains work (Wolvic runs). So on ANGLE, OpenGL ES OpenXR apps that
use depth swapchains do not run; OpenXR apps on Vulkan do.

## S5 step 2: the shape of the passthrough extension (decision)

What the runtime gives an OpenXR app: `OPAQUE` and `ALPHA_BLEND` blend modes, no passthrough
extension (no `XR_FB_passthrough`), and the compositor's own room view when SteamVR forces it.

| Route | Cost | Verdict |
|---|---|---|
| Advertise `XR_FB_passthrough` from the layer | needs a camera image path we do not have; the layer would answer calls with nothing behind them | no |
| Draw the camera feed ourselves (`/dev/video99`) | a V4L2 reader, colour conversion and a quad in the shell; latency and distortion are ours | later, if blend mode is not enough |
| Submit `ALPHA_BLEND` and let SteamVR composite over its view | one property-gated line in the layer; works only if SteamVR composites alpha over the room view | **first**: built, see below, not yet measured |

Built: `xr-layer/gles_layer.c` hooks `xrEndFrame`; with `debug.xr.blend_mode` set to `opaque`,
`additive` or `alpha_blend` it submits that mode whatever the app asked for (host-tested; unset it
does nothing). To measure on the Frame: deploy `libwgapps_xr_gles.so`, restart Android, run
hello_xr, `setprop debug.xr.blend_mode alpha_blend`, and take a stereo screenshot with the
camera enabled. If the room shows through, V4 uses blend mode; if not, V4 draws the feed itself.

## ANGLE: the display composer crash and its fix (2026-11-15)

First ANGLE trials passed every check, but Android's display restarted as soon as the user pointed at
the panel (tombstones: `android.hardware.graphics.composer@2.1-service`, SIGSEGV in
`egl::Image::onDestroy` under `eglCreateImageKHR`; the composer imports Android's native
buffers, which ANGLE's Vulkan backend cannot on this driver, and its failure path dereferences a
null). The trial missed it because it only drove apps; it now injects pointer input and checks the
display services' pids and tombstones.

Fix: the composer keeps Mesa's EGL. `wgapps` adds `setenv LD_PRELOAD libwgapps_props.so` and
`setenv WGP wgapps.composer` to every rc that defines `vendor.hwcomposer-2-1` (the vendor's,
init.waydroid.rc and our z_wgapps.rc, which wins by `override`), once per mount destination, and
`props.d/wgapps.composer` says `ro.hardware.egl=mesa`. Three things went wrong before it worked,
each now covered by a test: the override file in z_wgapps.rc was missed, podman refused a second
mount on the same destination, and the preload silently ignores a file name with a hyphen.

Verified on the Frame: composer maps Mesa's `libEGL_mesa.so`, SurfaceFlinger maps ANGLE; no
composer tombstone on boot; the user pointed at the panel and used Wolvic (including the 360 page)
without a crash. Simulated input (`input` inside Android, libei into gamescope) cannot reach the
real path: Steam's tooling (vrcmd, overlay_viewer, the community devkit) has no public way to
inject overlay pointer events, so the real check is a person pointing.

## S4 pixel path (measured 2026-11-15, `spikes/quad2d/`, `tools/build-quad2d.sh`)

A 150-line Java app creates a `VirtualDisplay` (1280x720, 240 dpi, flags PUBLIC | OWN_CONTENT_ONLY)
drawing into an `ImageReader` (RGBA_8888), installed into the running Android with `pm install`
(no restart). The shell started Settings on that display (`am start --display <id>`).

- **Pixels arrive.** The reader got frames of the real Settings UI (mean luma 33-36, not blank):
  195 frames in 8.4 s while the UI changed (about 23 frames/s with an idle screen; it is
  damage-driven, so a still screen gives few).
- **Input reaches the app.** `input -d <id> tap` and `swipe` changed the frame hash right away
  (scroll and tap response visible in the next frames). Latency was not measured to the millisecond.
- **Blocked from the app itself:** starting another app's activity on the app's own display failed
  with a `SecurityException` (the display is untrusted and Settings does not allow embedding). The
  real shell must be a system app that holds `ADD_TRUSTED_DISPLAY` (a priv-app, like the Settings
  APK, with the permission allow-listed in `/system/etc/permissions`) or launch through the shell
  user. Both are ours to bind into the container.
- **Not tested:** getting the `ImageReader`'s buffer into an OpenXR quad layer (a GL/Vulkan
  upload from the `HardwareBuffer` into a swapchain image), and its cost per window.

Decision: V2 goes ahead by this route (virtual display per window, pixels to an OpenXR quad,
pointer mapped back with injected `MotionEvent`s on the display). The first V1/V2 step is the
buffer-to-swapchain upload; if it is too slow, fall back to showing the flat panel beside the
shell, which S3 showed coexists.

## S5 measurement attempt (2026-11-15): inconclusive, needs the headset worn in the play space

Test without a custom app: `xr-layer/gles_layer.c` also has `debug.xr.drop_layers=1` (the frame is
submitted with no layers), so `hello_xr` Vulkan plus `debug.xr.blend_mode=alpha_blend` is an empty
ALPHA_BLEND frame: if SteamVR composites over the room it shows, if it treats the frame as opaque it
is black (`opaque` + dropped layers is the control). Stereo screenshots through SteamVR
(IVRScreenshots, run over ssh as `frame_vrshot.py` from the open-source frame-control project)
of three scenes: normal `hello_xr`; empty + opaque; empty + alpha_blend.

Result: all three show SteamVR's own room view (camera) because the headset was not in the saved
play space ("camera enabled outside playspace"), which hides any scene. In the empty + opaque
capture the Android panel and dashboard bar are visible over it; in the other two the panel is
not. So nothing can be concluded about whether `ALPHA_BLEND` is honored: the room view is on in
every case. To measure: wear the headset inside the play space (room view off), then rerun the
same three scenes (script: the harness `tools/gpu-trial.py` helpers, `restart_android`, `focused`,
the screenshot call above). Expected if blend mode works: a = the hello_xr scene, b = black,
c = the room. Decision stays as written above (blend mode first, draw the camera feed ourselves
if not).

## S5 second measurement (2026-11-15, headset worn): SteamVR shows its own room view regardless of blend mode

Same three scenes with the headset on, in the living room (screenshots viewed once and deleted):

| Scene | What the headset showed |
|---|---|
| normal `hello_xr` Vulkan (opaque) | the room (camera), the Android panel (black) over it; no `hello_xr` scene |
| empty frame + `opaque` | the room, no panel |
| empty frame + `alpha_blend` | the room, the Android panel (black) over it |

So an empty frame shows the room whether the blend mode is opaque or alpha-blend: SteamVR's room
view (the camera background the dashboard's "Cycle view" button switches) is a system setting of
the compositor, not something an app obtains through `environmentBlendMode`. And with the Android
dashboard panel open, the scene app's own picture was not visible at all, so an app writing
transparent pixels cannot be judged this way either.

Decision for V4 (replaces "blend mode first"): the shell asks for the **room view through SteamVR**
(its camera settings or the dashboard's view cycle, driven by `vrcmd --set-settings-*` /
the mailbox the dashboard uses), as a background choice next to "solid" and "home". The
`debug.xr.blend_mode` / `debug.xr.drop_layers` test modes stay in the layer (property-gated, off by
default) for re-checking with an app that renders alpha 0 with the dashboard closed. Not
established: how to toggle the room view from code; the mailbox websocket on `127.0.0.1:27062`
accepts a handshake only with `Origin: http://localhost:27062` (other origins get 401), and its
message format still has to be recovered (an earlier session had it).


## ccodec0 alone: how to run it (prepared 2026-11-15)

What is left of the freeze question (ANGLE removed it in one user run; `ccodec0` alone is untried)
needs a person for the one step the harness cannot do, the fullscreen toggle in Wolvic.

1. Put the headset on and open Wolvic's 360 video page (the one that froze about 3 s after leaving
   fullscreen on the baseline).
2. From a terminal on the Mac: `FRAME_HOST=steamos@<frame> python3 tools/gpu-trial.py ccodec0`. It sets
   `debug.stagefright.ccodec=0` in the device properties, restarts Android (it asks Steam to end and
   start the Android entry), runs its checks (boot, GLES driver, Settings/Chrome/Plex draw, hello_xr
   reaches FOCUSED, Wolvic frames for the soak time) and restores the baseline afterwards.
3. While its soak runs, in the headset: play the video, go fullscreen, leave fullscreen, repeat a
   few times. On the baseline the picture froze about 3 s after leaving fullscreen every time; the
   soak's frame log shows a gap of that size if it happens again.
4. The result decides whether `ccodec0` alone is enough (stable, GPU stays Mesa) or ANGLE stays the
   fix; ANGLE already worked in the user's run. Do not run it unattended: it restarts Android.

The release is prepared the same way: `tools/sfa_release.py release v0.1.2 --dry-run` is clean (it
would publish `main`, which holds the seccomp, wrong-session and keystore fixes); dropping
`--dry-run` pushes the tag and starts the image build. That is for the owner to run.

## ccodec0 alone: the scripted toggle (2026-11-16)

`tools/gpu-trial.py CONFIG --toggle-script FILE` repeats the fullscreen toggle without a person. FILE is a
JSON list of steps for the simulated SteamVR controllers (`runtime-rust/xr-sim`, registered on the Frame as
`~/xrsim-driver`): `{"right": [x, y, z, yaw, pitch, trigger, grip, stick, buttons], "left": [...],
"wait": seconds}`. One round is run every few seconds during the Wolvic soak, and the soak's frame-log gap
is the result (a gap near 3 s after leaving fullscreen is the freeze). A hand left out of a step keeps its
last pose. Positions are in SteamVR's raw tracking space (a hand at head height is `y = -0.1`).

The poses are specific to where Wolvic puts its window and its fullscreen button, so they are recorded
once with the headset face up and in a calibrated play space (with it face down, SteamVR shows its room
view over the app and the scene cannot be seen):

1. Start Wolvic on the 360 page, then write poses to `/tmp/xr-sim-input` on the Frame (or use
   `xr-sim point`) until a headset screenshot (`IVRScreenshots`, see `tools/`) shows the beam on the
   fullscreen button.
2. A round is: aim at the button, trigger down 0.4 s, trigger up, wait for the video to be fullscreen, aim
   at the exit control (or send the Back button, bit 4 of `buttons`), trigger click, wait 5 s.
3. Save the poses as the JSON file and run `tools/gpu-trial.py ccodec0 --soak 300 --toggle-script FILE`.

Status: the harness side is tested (`tests/test_gpu_trial.py`); the poses for Wolvic's buttons are not
recorded yet, so a scripted run on a headset in the calibrated play space is still to be done.

Tried and rejected (2026-11-16): `"keys"` steps (`tools/wolvic-fullscreen-keys.json`, F then Escape as Android
key events). The events reach Wolvic's native activity, but on the baseline, where a person's toggle froze the
picture about 3 s after leaving fullscreen every time, six scripted rounds left the longest frame-log gap at
1 s. A test that cannot make the known-bad configuration fail proves nothing, so a run with keys says nothing
about `ccodec0`. The positive control (baseline must show the gap) is the acceptance test for any toggle
script, including the pointer one.

Unattended `ccodec0` run, same day (soak only, no toggle): all draw and hello_xr checks passed, Wolvic stayed
alive with a 1 s gap over 420 s. Its "no new native crash" check failed on a `com.android.launcher3`
RenderThread SIGSEGV at the moment the harness restarted Android back to the baseline; a baseline-to-baseline
run with the same restart (above) produced no tombstone, so the crash is tied to leaving `ccodec0`, not to video.

### Scripted pointer toggle: what worked and what did not (2026-11-16)

With the headset's play space calibrated (Quick Calibrate, `vrmail.py quick_reset_room_setup`) and Wolvic
showing the YouTube 360 page, the simulated right hand at `[0.1, -0.1, -0.2, 6, 31.5]` (raw space, yaw and
pitch in degrees) put the cursor on the player's fullscreen button. A trigger click then made Wolvic go
fullscreen with the 360 video playing, and the `b` button (bit 4, value 16) left fullscreen again, both seen
in headset screenshots. `tools/wolvic-fullscreen-sim.json` is that sequence.

What is not proven: those poses are world-space, so they only work while the headset and the Wolvic window
are where they were. A baseline run with the script in the harness (7 rounds, 150 s) showed a 1 s gap, but
a screenshot after the next restart showed the Wolvic window was not in view, so the toggles probably missed
and that run is not a valid positive control. The driver now accepts a 10th number, `1`, meaning "x y z yaw
pitch are relative to the headset's heading" (`driver_xrsim.cpp`), to make the poses repeatable; it builds and
loads but was not yet used to land a click. The headset also reports roll about 180 degrees (face down), which
flips every screenshot. Still needed: a head-relative recording, then the baseline must show the freeze before
`ccodec0` is run.

### Automated fullscreen toggle with a measured aim (2026-11-16, later)

What changed and works:

- `vrcmd --resetroomsetup` is the play-space API (the dashboard's Quick Calibrate button does the same). Run it
  after Wolvic launches, then `vrcmd --hidedashboard` a few times: it opens SteamVR's menu, which hides the
  window.
- The driver's tenth number `2` makes the simulated hand ride rigidly with the headset, so a face-down or
  rolled headset does not matter for the hand itself.
- Where Wolvic puts its window depends on the headset pose at launch, so a fixed aim only works for one pose.
  `tools/gpu-trial.py` now measures the aim on every run: it loads `tools/frame-hover.html` in Wolvic (served
  from the Frame), `tools/frame-aim-sweep.py` finds the window and steers the hand to the middle of the
  player from the page positions the page reports, then the real YouTube 360 page is loaded in the same window.
  Rounds where the headset moved are discarded and counted; a round where the page never entered fullscreen
  fails the check ("input path broken"), so a dead input path can no longer look like a pass.
- Evidence of the input path: `GeckoView:DOMFullscreenEntered` and `DOMFullscreenExited` in logcat. Starting
  playback of a 360 video makes Wolvic go fullscreen by itself; B leaves it. Leaving fullscreen moves the
  window out of view, so each round is a fresh launch.

Result on the baseline (Mesa EGL, no `ccodec0`): 15 fresh launches, fullscreen entered and left 13 times
(2 launches could not be calibrated), longest gap in Wolvic's frame logs after leaving fullscreen 1.0 s, no
freeze. Earlier unattended baseline runs of the same kind: another 11 exits, no freeze. So the freeze seen on
2026-11-14 (fullscreen entered and left after about 13 s, frames stopped 3 s later) does not reproduce in 24
simulated exits. Until the baseline freezes, a `ccodec0` run cannot show that `ccodec0` fixes it; the question
stays open. Open differences from the original repro: the exit was made with a real controller; the headset was
worn; the original run was the first video after a fresh Android boot.

### Baseline against `ccodec0`, 40 stressed fullscreen exits each (2026-11-17)

Same scripted rounds as above (calibrated aim, fresh Wolvic launch per exit, 12 busy loops in Android while
leaving fullscreen so the lock race has room): baseline 36 exits, 0 freezes; `ccodec0` 32 exits (3 rounds
dropped because the headset moved), 0 freezes. Over every stressed baseline run so far the freeze showed up
once in 47 exits (11.9 s gap, round 9 of the first stressed run), and never in 83 unstressed exits. A rate of
about 2% cannot separate `ccodec0` from the baseline with 32 exits: the question is still open. What would
settle it: a trigger that freezes the baseline often (the original repro froze once in one real run), or about
150 exits per config. Next candidates to raise the rate: GPU load in Android during the exit, a real controller
exit, or the first video after a fresh Android boot.

### Freeze after fullscreen exit with the hardware decoder, and the EGL buffer-age layer (2026-11-16/17)

Same scripted rounds (calibrated aim, fresh Wolvic launch per exit, 12 busy loops during the exit), now
on the shipping configuration with the hardware decoder installed (Wolvic's YouTube 360 clip creates
`c2.v4l2.vp9.decoder`):

| Configuration | Exits | Freezes (gap of 8 s or more) | Longest gap |
|---|---|---|---|
| Hardware decoder, no layer | 96 (2 more discarded, headset moved) | 3 | 12.0 s |
| Hardware decoder + `libwgapps_egl_layer.so` | 35 (run stopped early, about 2 min per exit) | 0 | no dump written |

Reading: the freeze still happens with the hardware decoder (3 of 96 is about 3%, similar to the earlier
1 in 47 without it), so the decoder neither removes nor causes it. The cause found on 2026-11-14 is a lock
cycle in Mesa's Android EGL: `eglQuerySurface(EGL_BUFFER_AGE_EXT)` dequeues a buffer with the display lock
held. Current upstream Mesa still has that shape (`droid_query_buffer_age` calls `update_buffers` with the
lock held, `eglapi.c` takes it first); a 2018 mesa-dev patch series proposed dropping the display mutex
around the dequeue and I did not find a merged version. The layer (`egl-layer/`) answers that one query with
0 without entering Mesa. It is confirmed active in SurfaceFlinger, system_server and app processes (its log
line appears), and the decode, regression and per-app screen checks pass with it on. Zero freezes in 35
exits is what a fix predicts, but at a 3% rate 35 clean exits also happen about a third of the time by
chance, so this is **not proof**. A run of about 150 exits would settle it (the harness now saves a native
stack dump and the log tail, `wolvic-freeze-*.txt` in the temp directory, whenever it sees a freeze, so a
freeze that survives the layer can be read). `WGAPPS_EGL_LAYER=0` turns the layer off for a comparison.
