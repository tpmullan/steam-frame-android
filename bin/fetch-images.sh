#!/bin/bash
# Resumable download of Waydroid's LineageOS 20 GAPPS images for 64-bit-only
# ARM CPUs (the Frame's SM8650 has no AArch32), straight from Waydroid's
# servers. URLs and SHA-256 come from Waydroid's OTA index (wgapps-ota).
# Retries across drops, stalls and sleep/wake; writes DONE only once both
# archives match their published hashes and are unpacked.
#
# WGAPPS_BUILD=YYYYMMDD pins a build; default is the newest published one.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${WGAPPS_BASE:-$HOME/.local/share/waydroid-gapps}/images"
VARIANT="${WGAPPS_VARIANT:-waydroid_arm64_only}"

log() { printf "%s %s\n" "$(date "+%F %T")" "$*"; }
die() {
	log "$*"
	exit 1
}

ota_args=(--variant "$VARIANT")
[[ -n "${WGAPPS_BUILD:-}" ]] && ota_args+=(--build "$WGAPPS_BUILD")
resolved="$(python3 "$HERE/wgapps-ota" "${ota_args[@]}")" || die "cannot resolve Waydroid images"
BUILD="" SYSTEM_URL="" SYSTEM_SHA256="" VENDOR_URL="" VENDOR_SHA256=""
eval "$resolved"

mkdir -p "$DIR" && cd "$DIR" || exit 1

hash_ok() { [[ -s "$1" ]] && [[ "$(sha256sum "$1" | cut -d' ' -f1)" == "$2" ]]; }

fetch() {
	local out="$1" url="$2" sha="$3" attempt=0 rc delay
	until hash_ok "$out" "$sha"; do
		attempt=$((attempt + 1))
		log "$out: attempt $attempt, have $(stat -c %s "$out" 2>/dev/null || echo 0) bytes"
		# Only abandon a connection that is truly dead (<500 B/s for 3 min).
		curl -fL -sS -C - --connect-timeout 30 --speed-limit 500 --speed-time 180 \
			-o "$out" "$url"
		rc=$?
		if [[ "$rc" -eq 0 || "$rc" -eq 22 || "$rc" -eq 33 ]]; then
			if ! hash_ok "$out" "$sha"; then
				log "$out: curl rc=$rc but SHA-256 does not match Waydroid's index, restarting from zero"
				rm -f "$out"
			fi
		else
			log "$out: curl rc=$rc, will resume"
		fi
		delay=$((attempt < 12 ? attempt * 5 : 60))
		hash_ok "$out" "$sha" || sleep "$delay"
	done
	log "$out: verified ($sha)"
}

if [[ -f DONE && "$(cat variant 2>/dev/null)" == "$VARIANT $BUILD" ]]; then
	log "build $BUILD already downloaded"
	exit 0
fi
rm -f DONE
# A different build: start the archives over.
if [[ "$(cat variant.wanted 2>/dev/null)" != "$VARIANT $BUILD" ]]; then
	rm -f system.zip vendor.zip
fi
echo "$VARIANT $BUILD" >variant.wanted
fetch vendor.zip "$VENDOR_URL" "$VENDOR_SHA256"
fetch system.zip "$SYSTEM_URL" "$SYSTEM_SHA256"
rm -f system.img vendor.img
for z in vendor.zip system.zip; do
	bsdtar -xf "$z" -C "$DIR" || die "unpack of $z failed"
done
mv variant.wanted variant
log "ALLDONE: $(cat variant)"
touch DONE
