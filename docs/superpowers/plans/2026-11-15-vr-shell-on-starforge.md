# VR shell on the Starforge Drift engine (Rust, native-app-platform branch)

> Status: proposal. Nothing is changed in the engine repo (`~/git/starforge-drift`, branch
> `native-app-platform`); its own rules (plan in `docs/plans/`, ADR in `docs/adrs/`, board card)
> apply when this is picked up there.

**Goal:** the VR shell (library, 2D app panels, optional 3D home) written in Rust on the user's
engine, replacing Meta's Spatial SDK, with OpenXR as the only new integration.

## What exists

- **Engine** (`runtime-rust/engine`): Rust 2D/3D, ECS, `wgpu` renderer with an offscreen scene
  texture, action-oriented input (ADR 0023), data-driven UI (ADR 0022).
- **native-ui** (`runtime-rust/native-ui`, ADRs 0026/0027): a widget set whose **Android backend
  drives real Android framework Views from Rust over JNI** (`android-activity`, `jni`), listeners as
  `java.lang.reflect.Proxy`. Apps are all Rust; no Gradle shells for apps (ADR 0025/0027/0031).
- **No OpenXR anywhere** in the engine yet.
- **This repo's prototype** (`vr-shell/`, C + a little Java) already proved the platform side on the
  Frame, so the Rust version starts from known-good facts:
  - the OpenXR loader builds from the pinned SDK with the NDK and loads in an Android app;
  - an OpenXR GLES session on SteamVR reaches VISIBLE; a 1920x1080 sRGB swapchain (`0x8C43`) takes
    the app's picture (rows flipped: GL's origin is bottom-left); an `XrCompositionLayerQuad`
    (1.8 m wide at 1.7 m) shows it;
  - the picture is an Android `Bitmap` drawn with a `Canvas` and uploaded with `glTexSubImage2D`;
  - hit-testing is a ray (aim pose, -Z) against the quad plane, mapped to pixels;
  - open: the session stays VISIBLE and never reaches FOCUSED while SteamVR's dashboard (the Android
    panel) holds input focus, so controller actions are not delivered yet (see "Risks").

## Architecture

```
native-ui app (Rust)  --JNI-->  Android View tree (offscreen, not attached to a window)
        ^                                  | measure/layout/draw into a Bitmap (1920x1080)
        | UiEvents                         v
xr-host (Rust, new crate)  -- upload -->  OpenXR swapchain (GLES, sRGB)  -->  quad layer
        ^                                                                       |
        '-- controller ray hit -> MotionEvent (down/up/hover) -> dispatchTouchEvent on the root view
```

- A new workspace crate `runtime-rust/xr-host` (ADR 0025 style: a native app crate), entry through
  `android-activity` like `mobile-android`, depending on `native-ui` (Android backend) and the
  `openxr` crate with the `static`/loader feature pointing at the loader we already build.
- **The UI is the existing native-ui widget set**: lists of cards, buttons, text, images. The shell
  is a Rust native-ui app; in VR it is rendered offscreen and presented as a panel. No widget is
  rewritten for VR.
- **Panels**: each panel = one View tree + one swapchain + one quad (position, size, curvature
  later). The 2D Android apps (V2) are panels fed by `VirtualDisplay -> ImageReader` (measured in S4:
  pixels arrive, input via `input -d <id>` / MotionEvents).
- **Input**: OpenXR actions (aim pose, trigger) -> ray vs each panel -> pixel -> `MotionEvent`
  (ACTION_HOVER_MOVE, ACTION_DOWN/UP) into that panel's root view.
- Engine changes needed (to be proposed as an ADR there): none for the UI path. For a 3D home
  (V3) the engine's `wgpu` renderer must be creatable on a Vulkan device chosen by OpenXR
  (`XR_KHR_vulkan_enable2` / `wgpu` `from_hal`); that is a later, separate ADR.

## Milestones

| | What | Proves |
|---|---|---|
| R0 | `xr-host` crate: `android-activity` + `openxr`: session, swapchain, one quad showing a solid colour; built by the engine's Android build (`starforge-bundle build android`) | Rust OpenXR on the Frame, same states as the C prototype |
| R1 | native-ui Android backend rendered offscreen to a Bitmap and shown on the quad (the existing "hello" example) | the UI path |
| R2 | controller ray -> MotionEvent; hover and tap on a button | input path (needs FOCUSED, see Risks) |
| R3 | the shell app (library grid, tabs, dock, launch) in native-ui; `wgapps mode vr` launches the Rust build | replaces `vr-shell/` |
| R4 | 2D app panels (virtual display), move/resize, dock lists running apps | V2 |
| R5 | environment: solid, SteamVR room view, optional 3D home on the engine's renderer | V3/V4 |

## Bridging Linux and Android (user direction, 2026-11-15)

A Rust launcher on the Linux side next to the Rust shell inside Android would let the two halves
talk to each other:

- **Linux launcher / Steam wrapper**: the engine's Linux host (native-ui's GTK4 backend, ADR 0028)
  as `wgapps`'s front: one program that owns the **podman lifecycle** (start, stop, attach,
  crash fallback; today bash in `bin/wgapps`) and is what the Steam entry runs.
- **A channel between the two halves**: a component on each side (Rust launcher on Linux, the shell
  in Android) over a socket we control (the container already forwards a port for adb, and the
  shared folder carries the app list today). With it the shell can show **Linux apps and windows**
  next to Android ones (SteamOS apps from the Steam library, desktop windows captured from gamescope
  as panels), and Android can reach the host for clipboard (exists), battery (exists), launching and
  settings without polling files.
- The catalog becomes two sources (Android packages, Linux/Steam entries) with one grid.

## Risks

- **FOCUSED** (solved in the prototype): with the Android dashboard panel in front, the session
  stays VISIBLE and gets no controller input. **Repeating `vrcmd --hidedashboard` for a few
  seconds** brings it to FOCUSED (once is not enough; `tools/gpu-trial.py` does that for hello_xr,
  and `wgapps` does it now after starting the shell). A projection layer was not needed for focus;
  the shell submits one anyway as its solid environment.
- **Controllers must be on**: SteamVR lists only the headset when no controller is connected
  (`vrcmd --info`: no `Device 1+`, "Dashboard pointer device: none"); the shell then reports its aim
  pose action as inactive. The Frame's controllers appear to OpenXR apps as Index controllers
  (`frame_controller_remapping.json`), so the shell binds both `khr/simple_controller` and
  `valve/index_controller`. Hover and click are **not yet verified on the headset**: no controller
  was connected during the tests.
- Offscreen View drawing: widgets that need a window (menus, dialogs, text input popups) will not
  work in an unattached tree; they need to be hosted in a `Presentation` on a virtual display
  (the S4 route) or reimplemented as in-panel sheets.
- Per-frame cost: uploading 1920x1080 RGBA only when a panel is dirty (the prototype does this).

## R0 result (2026-11-15)

Built and run on the Frame: `runtime-rust/xr-host` in a worktree of the engine's
`native-app-platform` branch (local branch `xr-host-spike`, not pushed; a copy is in
`spikes/starforge-xr-host/`). The Rust host loads the loader from the APK, creates an OpenXR GLES
session, reaches READY and shows a quad; with the dashboard hidden repeatedly the session reaches
FOCUSED. Headset screenshot: the quad is right-way up (dark panel, blue bar). Findings for R1/R2:

- The `openxr` crate (0.19) covers what is needed: `Entry::load` + `initialize_android_loader`,
  `khr_android_create_instance`, `opengles::SessionCreateInfo::Android`, quad layers.
- `cargo ndk` 4 takes the platform as `-P`, not `-p`.
- Compile and APK assembly work without Gradle; the engine's own `starforge-bundle build android`
  path (ADR 0031) is the intended way to package it and has not been tried for this crate.
- Next (R1): draw the native-ui Android View tree into a Bitmap and upload it instead of the
  placeholder painting; then R2 input (needs a connected controller).
