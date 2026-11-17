# VR shell: the next project

The Android integration release (Steam mode, mode switch, Settings screens, hardware video decode, full
resolution OpenXR, the Rust VR shell with windows and controller input) is closed out. Two pieces were
set aside on 2026-11-16 as a new project with a solid start:

## 1. The optional 3D home on the engine's renderer

- Exists: `environment = home` draws a plain sky and floor grid per eye in GLES (`xr-host/src/home.rs`), and
  the room and solid-colour backdrops. Checked by reading the framebuffer back, not yet seen in the headset
  with tracking (SteamVR's room view covers scene layers while tracking is in IMU fallback).
- Open: a scene with objects on the engine's wgpu renderer (needs an ADR: a wgpu device created on the
  Vulkan device OpenXR picks, `XR_KHR_vulkan_enable2`), saved layouts in a documented `.home` format with
  autosave and export, launcher panels placed in the room, app objects as a later option. Assets CC0 only,
  with a per-item cost budget. `home=off` keeps the plain environment.

## 2. The Rust launcher and Linux windows as panels

- Exists: the container lifecycle model, `status`, `stop` and `start` from a specification proven on the
  Frame (it boots a second Android); the gamescope screen as a panel through the bridge; the bridge's game
  icons and the app list.
- Open: moving the preparation steps (generated overrides, props, seccomp, optional mounts) from bash into
  Rust so the launcher owns the whole lifecycle; Linux windows as panels beyond the gamescope screen; the
  shell showing SteamOS apps and Android apps in one grid.

## Also for later

- A new Android image built Waydroid-style from the latest LineageOS, after everything here is stable (it
  may affect VR apps). The recipe is in the maintainer's private notes.
- The VR shell's status panel (host battery, volume and a few toggles through `wgapps-battery`).
