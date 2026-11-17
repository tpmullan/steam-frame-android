# Android's display restarts when you point at the panel (ANGLE)

Status: **fixed** in `bin/wgapps` (commit "ANGLE: the composer really gets Mesa's EGL"). Verified on
a Steam Frame by a person pointing at the panel and using Wolvic; not verifiable by script (see
"How to verify").

## Symptom

With `wgapps gpu egl angle`, Android looked fine (apps drew, `wgapps gpu trial` passed) but **the
moment the user pointed at the Android panel with a controller, Android's display restarted**: the
screen went black, SurfaceFlinger restarted, apps were killed and Android came back up. It also
crashed once per boot while Android started. With the default (`mesa`) nothing happened.

## Root cause

1. Android's graphics **composer HAL** (`android.hardware.graphics.composer@2.1-service`, with
   Waydroid's `hwcomposer.waydroid.so`) draws some layers itself: `egl_render_to_pixels` calls
   `eglCreateImageKHR` with an Android native buffer.
2. With `ro.hardware.egl=angle` **every** process gets ANGLE's EGL, the composer included. ANGLE's
   Vulkan backend cannot import Android native buffers on this driver (Turnip on Linux has no
   `VK_ANDROID_external_memory_android_hardware_buffer`). Image creation fails and ANGLE's failure
   path calls `egl::Image::onDestroy`, which dereferences a null pointer.
3. The composer dies with SIGSEGV; `onrestart restart surfaceflinger` takes the display with it.

Tombstone (full fixture: `tests/fixtures/tombstone-composer-angle.txt`):

```
Cmdline: /vendor/bin/hw/android.hardware.graphics.composer@2.1-service ...
signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0
  #00 pc 0000000000000000  <unknown>
  #01 libGLESv2_angle.so (egl::Image::onDestroy(egl::Display const*)+112)
  #02 libGLESv2_angle.so (egl::Display::createImage(...)+584)
  #03 libGLESv2_angle.so (egl::CreateImageKHR(...)+156)
  #04 libGLESv2_angle.so (EGL_CreateImageKHR+172)
  #05 libEGL_angle.so    (eglCreateImageKHR+72)
  #07 hwcomposer.waydroid.so (egl_render_to_pixels(display*, buffer*)+172)
  #08 hwcomposer.waydroid.so (egl_loop(void*)+88)
```

## Why the tests missed it

The GPU trial (`tools/gpu-trial.py`) drove apps only. It never used the pointer and only compared
the newest tombstone around app launches. It now injects pointer input and fails if SurfaceFlinger
or the composer is restarted or a new tombstone appears, and it names this crash
(`known_crash`). Android keeps at most 50 tombstones, so a tombstone *count* never changes once the
folder is full: compare the newest name.

## The fix

The composer only imports buffers, so it keeps Mesa's EGL while apps and SurfaceFlinger use ANGLE.
`bin/wgapps` (`prepare_composer_egl`, `bind_overrides`, `mount_composer_egl`), when the GLES
driver is `angle`:

- writes `props.d/wgapps.composer` containing `ro.hardware.egl=mesa`;
- adds `setenv LD_PRELOAD /vendor/lib64/libwgapps_props.so` and `setenv WGP wgapps.composer` to
  the composer service in **every rc file that defines it**;
- binds the patched copies, each destination once.

`libwgapps_props.so` (`props-override/`, the per-app device-profile preload) replaces the page of
Android's property area holding `ro.hardware.egl` in that one process, so the EGL loader picks
`libEGL_mesa.so` for the composer.

Check on a running Android:

```sh
p=$(wgapps sh pidof android.hardware.graphics.composer@2.1-service)
wgapps sh "tr '\0' '\n' < /proc/$p/environ | grep -E 'WGP|LD_PRELOAD'"
wgapps sh "grep -o '/vendor/lib64/egl/libEGL_[a-z]*' /proc/$p/maps | sort -u"      # libEGL_mesa
wgapps sh "grep -o '/vendor/lib64/egl/libEGL_[a-z]*' /proc/\$(pidof surfaceflinger)/maps | sort -u"  # libEGL_angle
```

## Three mistakes on the way (each has a test)

| Mistake | What it looked like | Test |
|---|---|---|
| Patched only the vendor's rc. The service is defined again with `override` in `init.waydroid.rc` and in our `z_wgapps.rc`, and the last override wins. | The composer still loaded ANGLE; its environment had no `WGP`. | `test_angle_composer.py`: `test_the_unpatched_files_leave_the_composer_on_the_wrong_egl`, `test_patching_only_the_vendor_rc_is_not_enough`, `test_after_the_fix_the_definition_init_uses_loads_the_preload` (a small model of init's override rule) |
| Added a second bind for `z_wgapps.rc`, which `cmd_start` already binds from `overrides/`. | `Error: /system/etc/init/z_wgapps.rc: duplicate mount destination`; **Android did not start at all.** | `test_no_file_is_mounted_twice` (runs the real `bind_overrides` and `mount_composer_egl` and checks destinations) |
| Named the override file `wgapps-composer`. The preload accepts only letters, digits, `_` and `.` for `WGP` and **silently** does nothing otherwise. | Preload loaded (`LD_PRELOAD` in the environment) but `ro.hardware.egl` stayed `angle`. | `props-override/test_props_override.c`: `the_composer_file_name_works_and_a_hyphen_is_silently_ignored`; `test_windows.py`: `test_the_preload_accepts_the_composer_file_name` |

## How to reproduce the original bug

On a Frame (this is what the fix prevents; it restarts Android's display):

1. `wgapps gpu egl angle`, restart Android, then remove the composer lines from `$BASE/run`
   (or run a `wgapps` from before the fix).
2. Point at the Android panel with a controller. Within a second the display restarts.
3. `wgapps sh 'ls -t /data/tombstones | head -1'` is a composer tombstone like the fixture.

Without hardware, the unit tests above reproduce the signature of every step.

## How to verify

Only a person pointing at the panel exercises the real path: controller -> SteamVR overlay events
-> gamescope -> Wayland -> the composer's input FIFOs -> Android. We found no way to inject that:

- `vrcmd --send-vrevent` takes arguments we could not decode (no output for JSON or names);
- `overlay_viewer` is a Qt GUI that exits on a headless run;
- the community devkit (`mcp-steamos-devkit`) says it has no pointer injection and drives input
  with ADB `input` inside the container, which skips the Wayland path;
- `tools/frame-pointer.py` sends libei pointer events into gamescope's emulated-input socket
  (`gamescope-0-ei`); the events are accepted, but their coordinate range is unmapped and we
  cannot observe them arriving in Android (the `wl_*_events` devices are FIFOs).

So: run `python3 tools/gpu-trial.py angle --keep` (apps, `input` events, display service pids),
then point at the panel for a minute and read the newest tombstone.

## Not fixed by this

- ANGLE on Turnip reports OpenGL ES 3.1. OpenGL ES OpenXR apps that assume 3.2 or ask for a depth
  swapchain (Khronos `hello_xr`) do not run (see `docs/superpowers/spikes/S3-S4-S5-partial.md`).
  That is why `mesa` stays the default.
- The underlying ANGLE bug (null dereference on the `eglCreateImageKHR` failure path) is not
  reported upstream yet.
