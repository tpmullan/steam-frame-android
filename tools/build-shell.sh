#!/bin/bash
# Build the VR shell (vr-shell/) into <out dir>/WgappsShell.apk, by hand with the
# Android SDK's command-line tools (no Gradle). First runs the Java tests.
#
# Signed with the SDK's debug key: a system app mounted by bin/wgapps only when
# `wgapps mode vr` is set. Copy it to ~/.local/share/waydroid-gapps/lib/ and
# restart Android. Optional, like the Settings APK.
#
# Usage: tools/build-shell.sh <out dir>
#   ANDROID_NDK   the NDK for the OpenXR scene (default: newest under $ANDROID_HOME/ndk)
#   ANDROID_HOME  the SDK (default ~/Library/Android/sdk, then ~/Android/Sdk)
#   JAVA_HOME     a JDK 11 or newer (default: /usr/libexec/java_home, then PATH)
set -euo pipefail

out="${1:?usage: tools/build-shell.sh <out dir>}"
here="$(cd "$(dirname "$0")" && pwd)"
app="$here/../vr-shell"

sdk="${ANDROID_HOME:-}"
for candidate in "$HOME/Library/Android/sdk" "$HOME/Android/Sdk"; do
	if [[ -z "$sdk" && -d "$candidate" ]]; then sdk="$candidate"; fi
done
[[ -d "$sdk" ]] || {
	echo "build-shell: no Android SDK (set ANDROID_HOME)" >&2
	exit 1
}
build_tools="$(find "$sdk/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)"
platform="$(find "$sdk/platforms" -mindepth 1 -maxdepth 1 -type d -name 'android-3[3-9]' | sort -V | head -1)"
[[ -x "$build_tools/aapt2" && -f "$platform/android.jar" ]] || {
	echo "build-shell: need build-tools with aapt2 and platform android-33 or newer in $sdk" >&2
	exit 1
}
if [[ -z "${JAVA_HOME:-}" ]] && command -v /usr/libexec/java_home >/dev/null; then
	JAVA_HOME="$(/usr/libexec/java_home 2>/dev/null || true)"
fi
javac="${JAVA_HOME:+$JAVA_HOME/bin/}javac"
java="${JAVA_HOME:+$JAVA_HOME/bin/}java"
android_jar="$platform/android.jar"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$out" "$work/test" "$work/classes"

# The logic that needs no Android runs on this machine first.
"$javac" -d "$work/test" "$app/src/dev/wgapps/shell/Catalog.java" "$app/src/dev/wgapps/shell/Hits.java" "$app"/test/*.java
"$java" -ea -cp "$work/test" CatalogTest
"$java" -ea -cp "$work/test" HitsTest

# A new version code per build, so Android replaces an older copy of the system app.
"$build_tools/aapt2" link -o "$work/base.apk" -I "$android_jar" --manifest "$app/AndroidManifest.xml" \
	--min-sdk-version 33 --target-sdk-version 33 \
	--version-code "$(($(date +%s) / 60))" --version-name 1.0
"$javac" --release 8 -Xlint:-options -cp "$android_jar" -d "$work/classes" "$app"/src/dev/wgapps/shell/*.java
"$build_tools/d8" --min-api 33 --lib "$android_jar" --output "$work" "$work"/classes/dev/wgapps/shell/*.class
(cd "$work" && zip -q base.apk classes.dex)

# The OpenXR scene (native/shell.c) needs the Android NDK and the OpenXR loader, which is built
# from the pinned SDK (tools/xr-layer.env) and cached. Without an NDK the APK has the flat grid
# only, and no WgappsShell.vr marker, so `wgapps` starts the flat activity.
ndk="${ANDROID_NDK:-}"
if [[ -z "$ndk" && -d "$sdk/ndk" ]]; then ndk="$(find "$sdk/ndk" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)"; fi
rm -f "$out/WgappsShell.vr"
if [[ -n "$ndk" && -d "$ndk/toolchains/llvm" ]]; then
	# shellcheck source=tools/xr-layer.env
	. "$here/xr-layer.env"
	cache="${WGAPPS_CACHE:-$HOME/.cache/wgapps}/openxr-$OPENXR_SDK_VERSION"
	sdksrc="$cache/OpenXR-SDK-release-$OPENXR_SDK_VERSION"
	if [[ ! -f "$cache/libopenxr_loader.so" ]]; then
		mkdir -p "$cache"
		curl -fsSL -o "$cache/sdk.tar.gz" \
			"https://github.com/KhronosGroup/OpenXR-SDK/archive/refs/tags/release-$OPENXR_SDK_VERSION.tar.gz"
		echo "$OPENXR_SDK_SHA256  $cache/sdk.tar.gz" | shasum -a 256 -c --quiet -
		tar -xzf "$cache/sdk.tar.gz" -C "$cache"
		cmake -S "$sdksrc" -B "$cache/build" -DCMAKE_TOOLCHAIN_FILE="$ndk/build/cmake/android.toolchain.cmake" \
			-DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-33 -DCMAKE_BUILD_TYPE=Release \
			-DBUILD_API_LAYERS=OFF -DBUILD_TESTS=OFF -DBUILD_CONFORMANCE_TESTS=OFF -DDYNAMIC_LOADER=ON >/dev/null
		cmake --build "$cache/build" --target openxr_loader >/dev/null
		cp "$cache/build/src/loader/libopenxr_loader.so" "$cache/libopenxr_loader.so"
	fi
	bin_dir="$(find "$ndk/toolchains/llvm/prebuilt" -mindepth 2 -maxdepth 2 -name bin | head -1)"
	glue="$ndk/sources/android/native_app_glue"
	mkdir -p "$work/apk/lib/arm64-v8a"
	"$bin_dir/aarch64-linux-android33-clang" -shared -fPIC -O2 -Wall -Wextra -Wno-unused-parameter \
		-Wno-missing-field-initializers -Wl,-z,max-page-size=16384 -Wl,-z,relro,-z,now \
		-I"$glue" -I"$sdksrc/include" -o "$work/apk/lib/arm64-v8a/libwgshell.so" \
		"$app/native/shell.c" "$glue/android_native_app_glue.c" -L"$cache" \
		-lopenxr_loader -llog -landroid -lEGL -lGLESv3
	cp "$cache/libopenxr_loader.so" "$work/apk/lib/arm64-v8a/"
	"$bin_dir/llvm-strip" --strip-unneeded "$work/apk/lib/arm64-v8a/libopenxr_loader.so"
	# Stored, not compressed: the manifest says extractNativeLibs=false.
	(cd "$work/apk" && zip -q -0 -X ../base.apk lib/arm64-v8a/libwgshell.so lib/arm64-v8a/libopenxr_loader.so)
	: >"$out/WgappsShell.vr"
	echo "build-shell: native scene built with $(basename "$ndk")"
else
	echo "build-shell: no Android NDK (set ANDROID_NDK): flat grid only" >&2
fi
"$build_tools/zipalign" -f -p 4 "$work/base.apk" "$work/aligned.apk"

keystore="$HOME/.android/debug.keystore"
if [[ ! -f "$keystore" ]]; then
	keystore="$work/debug.keystore"
	"${JAVA_HOME:+$JAVA_HOME/bin/}keytool" -genkeypair -keystore "$keystore" -storepass android -keypass android \
		-alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US" >/dev/null 2>&1
fi
"$build_tools/apksigner" sign --ks "$keystore" --ks-pass pass:android --key-pass pass:android --v4-signing-enabled false \
	--out "$out/WgappsShell.apk" "$work/aligned.apk"
"$build_tools/apksigner" verify "$out/WgappsShell.apk"
echo "build-shell: $out/WgappsShell.apk ok"
