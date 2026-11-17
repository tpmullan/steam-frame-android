# starforge-xr-host (R0 spike)

Rust OpenXR host for the VR shell, written for the user's engine workspace
(`~/git/starforge-drift`, branch `native-app-platform`; a copy of the crate as `runtime-rust/xr-host`).
It is kept here so the spike is not lost; it is not built by this repo.

R0 (verified on the Steam Frame, 2026-11-15): `android-activity` NativeActivity entry, the OpenXR
loader loaded at run time (`openxr` crate, feature `loaded`, `initialize_android_loader`), an OpenGL
ES 3 session on EGL (`khronos-egl`, `glow`), an sRGB swapchain, a quad layer in front of the user,
and the session state machine (IDLE, READY, SYNCHRONIZED, VISIBLE, FOCUSED).

Build (in the engine workspace, with `runtime-rust/xr-host` added to the members):

    ANDROID_NDK_HOME=<ndk> cargo ndk -t arm64-v8a -P 33 build -p starforge-xr-host --release

Package: a `hasCode=false` APK with `android.app.NativeActivity`, `android.app.lib_name` =
`starforge_xr_host`, the `org.khronos.openxr.intent.category.IMMERSIVE_HMD` category, both OpenXR
permissions, `extractNativeLibs=false`, and `libstarforge_xr_host.so` plus the loader
(`libopenxr_loader.so`, built by `tools/build-shell.sh`'s loader step) stored uncompressed under
`lib/arm64-v8a/`. Start it, then call `vrcmd --hidedashboard` repeatedly for a few seconds so the
session reaches FOCUSED.
