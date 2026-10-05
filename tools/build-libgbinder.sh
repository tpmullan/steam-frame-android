#!/bin/bash
# Build libgbinder for the Frame (arm64, glibc) into <out>/:
#   libgbinder.so.1, licenses/libgbinder.LICENSE, licenses/libglibutil.LICENSE
# libglibutil is linked in statically, so the library needs only GLib/GObject
# and libc at runtime (all present on SteamOS). Runs natively on an arm64
# Debian/Ubuntu host with build-essential, pkg-config, libglib2.0-dev, curl.
#
# Usage: tools/build-libgbinder.sh <out dir>
set -euo pipefail

out="${1:?usage: tools/build-libgbinder.sh <out dir>}"
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=tools/libgbinder.env
source "$here/libgbinder.env"

[[ "$(uname -m)" == aarch64 ]] || {
	echo "build-libgbinder: needs an aarch64 build host (got $(uname -m))" >&2
	exit 1
}

src="$(mktemp -d)"
trap 'rm -rf "$src"' EXIT
fetch() { # name repo version sha256
	local tarball="$src/$1.tar.gz"
	curl -fsSL -o "$tarball" "https://github.com/$2/archive/refs/tags/$3.tar.gz"
	echo "$4  $tarball" | sha256sum -c --quiet -
	tar -xzf "$tarball" -C "$src"
	echo "build-libgbinder: $2 $3 verified"
}
fetch glibutil sailfishos/libglibutil "$GLIBUTIL_VERSION" "$GLIBUTIL_SHA256"
fetch gbinder mer-hybris/libgbinder "$GBINDER_VERSION" "$GBINDER_SHA256"

make -C "$src/libgbinder-$GBINDER_VERSION" -j"$(nproc)" \
	LIBGLIBUTIL_PATH="$src/libglibutil-$GLIBUTIL_VERSION" release

mkdir -p "$out/licenses"
lib="$out/libgbinder.so.1"
cp "$src/libgbinder-$GBINDER_VERSION/build/release/libgbinder.so.$GBINDER_VERSION" "$lib"
strip --strip-unneeded "$lib"
cp "$src/libgbinder-$GBINDER_VERSION/LICENSE" "$out/licenses/libgbinder.LICENSE"
cp "$src/libglibutil-$GLIBUTIL_VERSION/LICENSE" "$out/licenses/libglibutil.LICENSE"

# Show what was built and fail on surprises.
readelf -h "$lib" | grep -E 'Class|Machine'
soname="$(readelf -d "$lib" | sed -n 's/.*(SONAME).*\[\(.*\)\]/\1/p')"
needed="$(readelf -d "$lib" | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p' | sort | tr '\n' ' ')"
echo "build-libgbinder: soname $soname; needs: $needed"
readelf -h "$lib" | grep -q 'AArch64' || {
	echo "build-libgbinder: not an AArch64 library" >&2
	exit 1
}
[[ "$soname" == libgbinder.so.1 ]] || {
	echo "build-libgbinder: unexpected soname $soname" >&2
	exit 1
}
for dep in $needed; do
	case "$dep" in
	libglib-2.0.so.0 | libgobject-2.0.so.0 | libc.so.6 | libpthread.so.0 | ld-linux-aarch64.so.1) ;;
	*)
		echo "build-libgbinder: unexpected dependency $dep" >&2
		exit 1
		;;
	esac
done
echo "build-libgbinder: $lib ok"
