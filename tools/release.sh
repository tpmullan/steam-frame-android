#!/bin/bash
# Publish a release to the public repository as a single snapshot commit.
#
# Development history stays in the development repository. The public
# repository receives one commit per release whose tree is exactly the
# released development commit, plus the release tag. No development commits
# or messages reach the public repo. Run by the GitLab `release-public` job
# on release tags (which also copies the image), or by hand.
#
# Usage: tools/release.sh vX.Y.Z [commit]   (default commit: HEAD)
#
# Environment:
#   RELEASE_REMOTE  remote name or URL of the public repository (default: github)
#   RELEASE_DENY    file with extended regexes (one per line) that must not
#                   appear in released files, e.g. internal hostnames.
#                   Kept outside the repository so the patterns themselves
#                   are never published.
#                   Default: ~/.config/steam-frame-android/release-deny
#   RELEASE_DRY_RUN=1  run every check and build the commit, but do not push
set -euo pipefail

VERSION="${1:?usage: tools/release.sh vX.Y.Z [commit]}"
COMMIT="${2:-HEAD}"
REMOTE="${RELEASE_REMOTE:-github}"
DENY="${RELEASE_DENY:-$HOME/.config/steam-frame-android/release-deny}"

die() {
	echo "release: $*" >&2
	exit 1
}

[[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must look like v1.2.3"
[[ -z "$(git status --porcelain)" ]] || die "working tree is not clean"
[[ -f "$DENY" ]] || die "no deny-list at $DENY (create it, even if empty)"

tree="$(git rev-parse "$COMMIT^{tree}")"

# Refuse to publish anything matching the deny-list.
patterns="$(mktemp)"
trap 'rm -f "$patterns"' EXIT
grep -v -E '^[[:space:]]*(#|$)' "$DENY" >"$patterns" || true
if [[ -s "$patterns" ]] && git grep -n -I -E -f "$patterns" "$COMMIT" -- . >&2; then
	die "released files match the deny-list (above)"
fi

# VERSION in the released commit must match the tag.
grep -qx "${VERSION#v}" <(git show "$COMMIT:VERSION") ||
	die "VERSION in $COMMIT is not ${VERSION#v}"

if git ls-remote --exit-code --tags "$REMOTE" "refs/tags/$VERSION" >/dev/null; then
	die "$VERSION already exists on the public repository"
fi

# Previous release on the public main branch, if any (an empty repository
# gets a root commit).
public_ref=refs/release/public-main
git update-ref -d "$public_ref" 2>/dev/null || true
parent=()
if git ls-remote --exit-code --heads "$REMOTE" main >/dev/null; then
	git fetch -q "$REMOTE" "+refs/heads/main:$public_ref"
	parent=(-p "$public_ref")
	if [[ "$(git rev-parse "$public_ref^{tree}")" == "$tree" ]]; then
		die "the public main branch already has this tree"
	fi
fi

release="$(git commit-tree "$tree" "${parent[@]}" -m "Release $VERSION")"
echo "release commit $release (tree of $(git rev-parse --short "$COMMIT"))"
if [[ "${RELEASE_DRY_RUN:-0}" == "1" ]]; then
	echo "dry run: not pushing"
	exit 0
fi
git push -q "$REMOTE" "$release:refs/heads/main" "$release:refs/tags/$VERSION"
echo "pushed $VERSION to the public repository"
