#!/bin/bash
# Build the release image (FROM scratch file bundle, linux/arm64) into an
# OCI archive without pushing it anywhere. The version is stamped into a
# temporary copy of the build context, so the repository stays unchanged.
# Needs lib/ from tools/build-libgbinder.sh and tools/build-android-libs.sh
# (the CI libgbinder and android-libs job artifacts).
#
# Usage: tools/build-image.sh <version> <output.tar>
# Optional environment: IMAGE_SOURCE (org.opencontainers.image.source),
#   IMAGE_REVISION (org.opencontainers.image.revision)
set -euo pipefail

version="${1:?usage: tools/build-image.sh <version> <output.tar>}"
out="${2:?usage: tools/build-image.sh <version> <output.tar>}"
root="$(cd "$(dirname "$0")/.." && pwd)"

[[ -f "$root/lib/libgbinder.so.1" ]] || {
	echo "build-image: missing lib/libgbinder.so.1; run tools/build-libgbinder.sh lib" >&2
	exit 1
}
for lib in libwgapps_xr_gles.so libwgapps_gbm_lock.so libwgapps_props.so libwgapps_egl_layer.so; do
	[[ -f "$root/lib/$lib" ]] || {
		echo "build-image: missing lib/$lib; run tools/build-android-libs.sh lib" >&2
		exit 1
	}
done
[[ -f "$root/hwdec/wgapps-hwdec.tar.xz" && -f "$root/hwdec/SHA256SUMS" ]] || {
	echo "build-image: missing hwdec/wgapps-hwdec.tar.xz or SHA256SUMS (tools/package-hwdec.py)" >&2
	exit 1
}
(cd "$root/hwdec" && sha256sum -c SHA256SUMS >/dev/null) || {
	echo "build-image: hwdec/wgapps-hwdec.tar.xz does not match hwdec/SHA256SUMS" >&2
	exit 1
}
ctx="$(mktemp -d)"
trap 'rm -rf "$ctx"' EXIT
cp -R "$root/bin" "$root/lib" "$root/overrides" "$root/hwdec" "$root/LICENSE" "$root/Containerfile" "$ctx/"
printf '%s\n' "$version" >"$ctx/VERSION"

docker buildx inspect sfa-builder >/dev/null 2>&1 ||
	docker buildx create --name sfa-builder --driver docker-container >/dev/null
# No provenance/SBOM attestations: they record the build context's git
# remote and registry names (internal hostnames).
docker buildx build --builder sfa-builder --platform linux/arm64 \
	--provenance=false --sbom=false \
	--label "org.opencontainers.image.source=${IMAGE_SOURCE:-https://github.com/tpmullan/steam-frame-android}" \
	--label "org.opencontainers.image.revision=${IMAGE_REVISION:-unknown}" \
	--label "org.opencontainers.image.version=$version" \
	--label "org.opencontainers.image.licenses=GPL-3.0-or-later" \
	--output "type=oci,dest=$out" \
	--file "$ctx/Containerfile" "$ctx"
echo "build-image: $version -> $out"
