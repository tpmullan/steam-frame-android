#!/bin/bash
# Build the system app behind the "Device profile per app" screen in Android's
# Settings (settings-app/) into <out dir>/WgappsSettings.apk, by hand with the
# Android SDK's command-line tools (no Gradle). First runs the Java tests.
#
# The APK is signed with the SDK's debug key: it is a system app mounted by
# bin/wgapps, not something installed from a store. Copy it to
# ~/.local/share/waydroid-gapps/lib/ and restart Android.
#
# Usage: tools/build-settings-app.sh <out dir>
#   ANDROID_HOME  the SDK (default ~/Library/Android/sdk, then ~/Android/Sdk)
#   JAVA_HOME     a JDK 11 or newer (default: /usr/libexec/java_home, then PATH)
set -euo pipefail

out="${1:?usage: tools/build-settings-app.sh <out dir>}"
here="$(cd "$(dirname "$0")" && pwd)"
app="$here/../settings-app"

sdk="${ANDROID_HOME:-}"
for candidate in "$HOME/Library/Android/sdk" "$HOME/Android/Sdk"; do
	if [[ -z "$sdk" && -d "$candidate" ]]; then sdk="$candidate"; fi
done
[[ -d "$sdk" ]] || {
	echo "build-settings-app: no Android SDK (set ANDROID_HOME)" >&2
	exit 1
}
build_tools="$(find "$sdk/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)"
platform="$(find "$sdk/platforms" -mindepth 1 -maxdepth 1 -type d -name 'android-3[3-9]' | sort -V | head -1)"
[[ -x "$build_tools/aapt2" && -f "$platform/android.jar" ]] || {
	echo "build-settings-app: need build-tools with aapt2 and platform android-33 or newer in $sdk" >&2
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
"$javac" -d "$work/test" "$app/src/dev/wgapps/settings/Profiles.java" \
	"$app/src/dev/wgapps/settings/ProfilesFile.java" "$app/src/dev/wgapps/settings/Labels.java" \
	"$app/src/dev/wgapps/settings/Kinds.java" "$app/src/dev/wgapps/settings/Modes.java" "$app"/test/*.java
"$java" -ea -cp "$work/test" ProfilesTest
"$java" -ea -cp "$work/test" ProfilesFileTest
"$java" -ea -cp "$work/test" LabelsTest
"$java" -ea -cp "$work/test" KindsTest
"$java" -ea -cp "$work/test" ModesTest

"$build_tools/aapt2" compile --dir "$app/res" -o "$work/res.zip"
# A new version code per build, so Android replaces an older copy of the system app.
"$build_tools/aapt2" link -o "$work/base.apk" -I "$android_jar" --manifest "$app/AndroidManifest.xml" \
	--min-sdk-version 33 --target-sdk-version 33 \
	--version-code "$(($(date +%s) / 60))" --version-name 1.0 "$work/res.zip"
"$javac" --release 8 -Xlint:-options -cp "$android_jar" -d "$work/classes" "$app"/src/dev/wgapps/settings/*.java
"$build_tools/d8" --min-api 33 --lib "$android_jar" --output "$work" "$work"/classes/dev/wgapps/settings/*.class
(cd "$work" && zip -q base.apk classes.dex)
"$build_tools/zipalign" -f 4 "$work/base.apk" "$work/aligned.apk"

keystore="$HOME/.android/debug.keystore"
if [[ ! -f "$keystore" ]]; then
	keystore="$work/debug.keystore"
	"${JAVA_HOME:+$JAVA_HOME/bin/}keytool" -genkeypair -keystore "$keystore" -storepass android -keypass android \
		-alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US" >/dev/null 2>&1
fi
"$build_tools/apksigner" sign --ks "$keystore" --ks-pass pass:android --key-pass pass:android --v4-signing-enabled false \
	--out "$out/WgappsSettings.apk" "$work/aligned.apk"
"$build_tools/apksigner" verify "$out/WgappsSettings.apk"
echo "build-settings-app: $out/WgappsSettings.apk ok"
