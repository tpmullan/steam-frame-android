#!/bin/bash
# Build this project's own libraries for Android (arm64) into <out>/:
#   libwgapps_xr_gles.so   the OpenXR layer in xr-layer/
#   libwgapps_gbm_lock.so  the graphics allocator's preload in gbm-lock/
#   libwgapps_props.so     the per-app property overrides in props-override/
# First builds and runs each one's test on the build host.
#
# Needs no Android NDK (there is none for arm64 Linux hosts), only clang with
# lld: the libraries use a handful of functions from Android's public
# libraries, declare them themselves, and link against empty stand-ins made
# here.
#
# Usage: tools/build-android-libs.sh <out dir>
#   CC       clang that can target Android (default clang; an NDK's works too)
#   HOST_CC  compiler for the tests (default cc)
#   READELF  default readelf (llvm-readelf works too)
set -euo pipefail

out="${1:?usage: tools/build-android-libs.sh <out dir>}"
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=tools/xr-layer.env
source "$here/xr-layer.env"
CC="${CC:-clang}"
HOST_CC="${HOST_CC:-cc}"
READELF="${READELF:-readelf}"
root="$here/.."

src="$(mktemp -d)"
trap 'rm -rf "$src"' EXIT
sdk="OpenXR-SDK-release-$OPENXR_SDK_VERSION"
curl -fsSL -o "$src/sdk.tar.gz" \
	"https://github.com/KhronosGroup/OpenXR-SDK/archive/refs/tags/release-$OPENXR_SDK_VERSION.tar.gz"
echo "$OPENXR_SDK_SHA256  $src/sdk.tar.gz" | sha256sum -c --quiet -
tar -xzf "$src/sdk.tar.gz" -C "$src" "$sdk/include/openxr"
echo "build-android-libs: OpenXR headers $OPENXR_SDK_VERSION verified"

warn=(-std=c11 -Wall -Wextra -Wno-missing-field-initializers -Werror)
android=(--target=aarch64-linux-android28 -ffreestanding -nostdlib -shared -fPIC -fuse-ld=lld)

host_test() { # test.c [compiler flag...]
	"$HOST_CC" "${warn[@]}" "${@:2}" -o "$src/test" "$1"
	"$src/test"
}

# An empty library with the given functions, to link against in place of
# Android's.
stand_in() { # soname function...
	local soname="$1" fn
	shift
	for fn in "$@"; do echo "void $fn(void) {}"; done >"$src/stand_in.c"
	"$CC" "${android[@]}" -Wl,-soname,"$soname" -o "$src/$soname" "$src/stand_in.c"
}
stand_in libc.so strcmp strstr snprintf memcpy memset __stack_chk_fail \
	pthread_mutex_lock pthread_mutex_unlock open read close getenv strlen mmap mprotect getpagesize __system_property_find
stand_in libdl.so dlopen dlsym
stand_in liblog.so __android_log_print
stand_in libEGL.so eglGetCurrentContext
stand_in libGLESv2.so glGetString glDisable

# Build a library, show what was built and fail on surprises.
android_lib() { # soname source "Android libraries" "exported functions" [compiler flag...]
	local name="$1" source="$2" libs="$3" exports="$4" lib="$out/$1"
	local dep fn header dynamic symbols soname needed links=()
	shift 4
	for dep in $libs; do links+=("$src/$dep"); done
	mkdir -p "$out"
	# 16 KiB segments load on kernels with either page size.
	"$CC" "${android[@]}" "${warn[@]}" -O2 -fvisibility=hidden "$@" \
		-Wl,-soname,"$name" -Wl,--no-undefined -Wl,-z,relro,-z,now \
		-Wl,-z,max-page-size=16384 -Wl,--hash-style=both -Wl,-s \
		-o "$lib" "$source" "${links[@]}"

	# (Captured first: grep -q closing a pipe early fails the pipeline.)
	header="$("$READELF" -h "$lib")"
	dynamic="$("$READELF" -d "$lib")"
	symbols="$("$READELF" -W --dyn-syms "$lib")"
	grep -E 'Class|Machine' <<<"$header"
	soname="$(sed -n 's/.*(SONAME).*\[\(.*\)\]/\1/p' <<<"$dynamic")"
	needed="$(sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p' <<<"$dynamic" | sort | tr '\n' ' ')"
	echo "build-android-libs: soname $soname; needs: $needed"
	[[ "$header" == *AArch64* ]] || {
		echo "build-android-libs: $name is not an AArch64 library" >&2
		exit 1
	}
	[[ "$soname" == "$name" ]] || {
		echo "build-android-libs: unexpected soname $soname" >&2
		exit 1
	}
	for dep in $needed; do
		[[ " $libs " == *" $dep "* ]] || {
			echo "build-android-libs: $name has an unexpected dependency, $dep" >&2
			exit 1
		}
	done
	for fn in $exports; do
		grep -qE " FUNC +GLOBAL +DEFAULT .* $fn\$" <<<"$symbols" || {
			echo "build-android-libs: $name does not export $fn" >&2
			exit 1
		}
	done
	echo "build-android-libs: $lib ok"
}

host_test "$root/xr-layer/test_gles_layer.c" -I "$src/$sdk/include"
android_lib libwgapps_xr_gles.so "$root/xr-layer/gles_layer.c" \
	"libc.so liblog.so libEGL.so libGLESv2.so" xrNegotiateLoaderApiLayerInterface \
	-I "$src/$sdk/include"

host_test "$root/gbm-lock/test_gbm_lock.c" -pthread
android_lib libwgapps_gbm_lock.so "$root/gbm-lock/gbm_lock.c" \
	"libc.so libdl.so liblog.so" "gbm_bo_map gbm_bo_unmap"

host_test "$root/props-override/test_props_override.c"
# Nothing exported: it does its work in a constructor when Android loads it.
android_lib libwgapps_props.so "$root/props-override/props_override.c" \
	"libc.so liblog.so" ""
