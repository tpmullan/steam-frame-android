#!/bin/bash
# Development deploy: copy this checkout to a Frame over SSH in the same
# layout `wgapps update` installs from the release image. Only touches
# ~/.local/share/waydroid-gapps (or $FRAME_BASE, relative to the Frame home).
set -euo pipefail

HOST="${FRAME_HOST:?set FRAME_HOST, e.g. steamos@<frame address>}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${FRAME_BASE:-.local/share/waydroid-gapps}"

# shellcheck disable=SC2029 # $BASE is meant to expand here
ssh "$HOST" "mkdir -p $BASE && rm -rf $BASE/overrides"
scp -q -r "$HERE/bin" "$HERE/overrides" "$HERE/VERSION" "$HOST:$BASE/"
# shellcheck disable=SC2029
ssh "$HOST" "rm -rf $BASE/bin/__pycache__ && chmod 0755 $BASE/bin/* && find $BASE/overrides -type f -exec chmod 0644 {} +"
echo "deployed $(cat "$HERE/VERSION") to $HOST:~/$BASE"
