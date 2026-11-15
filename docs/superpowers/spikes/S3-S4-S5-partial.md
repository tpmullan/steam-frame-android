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
