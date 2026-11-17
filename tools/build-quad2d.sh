#!/bin/bash
# Build the S4 spike app (spikes/quad2d/) into <out dir>/quad2d.apk with the Android SDK's
# command-line tools (no Gradle). Debug-signed; install it into a running Android with
# `wgapps sh pm install` after copying it to the Frame. Not shipped.
#
# Usage: tools/build-quad2d.sh <out dir>   (ANDROID_HOME, JAVA_HOME as for build-settings-app.sh)
set -euo pipefail

out="${1:?usage: tools/build-quad2d.sh <out dir>}"
here="$(cd "$(dirname "$0")" && pwd)"
app="$here/../spikes/quad2d"

sdk="${ANDROID_HOME:-}"
for candidate in "$HOME/Library/Android/sdk" "$HOME/Android/Sdk"; do
	if [[ -z "$sdk" && -d "$candidate" ]]; then sdk="$candidate"; fi
done
[[ -d "$sdk" ]] || {
	echo "build-quad2d: no Android SDK (set ANDROID_HOME)" >&2
	exit 1
}
build_tools="$(find "$sdk/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)"
platform="$(find "$sdk/platforms" -mindepth 1 -maxdepth 1 -type d -name 'android-3[3-9]' | sort -V | head -1)"
if [[ -z "${JAVA_HOME:-}" ]] && command -v /usr/libexec/java_home >/dev/null; then
	JAVA_HOME="$(/usr/libexec/java_home 2>/dev/null || true)"
fi
javac="${JAVA_HOME:+$JAVA_HOME/bin/}javac"
android_jar="$platform/android.jar"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$out" "$work/classes"

"$build_tools/aapt2" link -o "$work/base.apk" -I "$android_jar" --manifest "$app/AndroidManifest.xml" \
	--min-sdk-version 33 --target-sdk-version 33 --version-code 1 --version-name 1.0
"$javac" --release 8 -Xlint:-options -cp "$android_jar" -d "$work/classes" "$app"/src/dev/wgapps/quad2d/*.java
"$build_tools/d8" --min-api 33 --lib "$android_jar" --output "$work" "$work"/classes/dev/wgapps/quad2d/*.class
(cd "$work" && zip -q base.apk classes.dex)
"$build_tools/zipalign" -f 4 "$work/base.apk" "$work/aligned.apk"

keystore="$HOME/.android/debug.keystore"
if [[ ! -f "$keystore" ]]; then
	keystore="$work/debug.keystore"
	"${JAVA_HOME:+$JAVA_HOME/bin/}keytool" -genkeypair -keystore "$keystore" -storepass android -keypass android \
		-alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US" >/dev/null 2>&1
fi
"$build_tools/apksigner" sign --ks "$keystore" --ks-pass pass:android --key-pass pass:android --v4-signing-enabled false \
	--out "$out/quad2d.apk" "$work/aligned.apk"
"$build_tools/apksigner" verify "$out/quad2d.apk"
echo "build-quad2d: $out/quad2d.apk ok"
