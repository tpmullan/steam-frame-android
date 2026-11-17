# Wolvic with Steam Frame controllers

Stock Wolvic only knows the controllers of a list of headsets, picked by the Android model name.
On the Frame that name is unknown, so it gets the minimal `khr/simple_controller` profile: trigger
and menu only. `0001-generic-controller-mapping.patch` (against Igalia/wolvic tag `v1.10`) adds
the `khr/generic_controller` profile (trigger, grip, thumbstick with click, primary/secondary)
and enables `XR_KHR_generic_controller`.

Build (Mac, JDK 21, Android SDK with platform 36):

    git clone --branch v1.10 --depth 1 --recurse-submodules --shallow-submodules https://github.com/Igalia/wolvic
    cd wolvic && git apply /path/to/0001-generic-controller-mapping.patch
    echo "sdk.dir=$HOME/Library/Android/sdk" > local.properties
    ./gradlew assembleLynxArm64GeckoGenericDebug

The APK keeps the stock package name, so uninstall the stock one first (`pm uninstall`; its settings go
with it). Output: `app/build/outputs/apk/lynxArm64GeckoGeneric/debug/`.
