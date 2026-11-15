#!/usr/bin/env python3
"""Release tooling for steam-frame-android (run by GitLab CI on vX.Y.Z tags).

Development and CI live in the development repository. A release tag there
builds the image once, checks it, publishes it to the GitLab registry and
GHCR as :vX.Y.Z (moving GHCR :latest when it is the highest release, or equal
for a re-run), checks the published image, then pushes one snapshot commit
plus the tag to the public GitHub repository. Re-running a tag re-publishes.
The only thing that stops a release is internal data (host names, cluster
names, deny-listed patterns) in the released files or image.

Subcommands:
  highest TAG...                        print the highest vX.Y.Z
  release vX.Y.Z [COMMIT]               snapshot commit + tag to the public repo
  check-image oci-archive:PATH|docker://REF
  publish vX.Y.Z IMAGE.tar              images, check, then release
  check-credentials                     read-only check of GITHUB_RELEASE_TOKEN

Environment: see each subcommand's docstring.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
DEFAULT_DENY = pathlib.Path.home() / ".config/steam-frame-android/release-deny"

REQUIRED_FILES = (
    "wgapps/bin/wgapps",
    "wgapps/bin/wgapps-pad",
    "wgapps/bin/wgapps-ota",
    "wgapps/bin/wgapps-gen-overrides",
    "wgapps/bin/steam-shortcuts.py",
    "wgapps/bin/fetch-images.sh",
    "wgapps/VERSION",
    "wgapps/LICENSE",
    "wgapps/overrides/system/etc/init/z_wgapps.rc",
)
# Android/Google artifacts and files generated from Waydroid's vendor image
# must never ship.
FORBIDDEN_FILE_RE = re.compile(r"\.(apk|img|zip|jar)$|vintf/manifest\.xml$|seccomp_policy/")
PLATFORM = "linux/arm64"


class ReleaseError(Exception):
    pass


def log(msg: str) -> None:
    print(f"sfa-release: {msg}", file=sys.stderr, flush=True)


def run(*cmd: str, input: str | None = None, cwd: str | None = None, check: bool = True) -> str:
    """Run a command and return its stdout.

    Secrets are passed via ``input`` or the environment, never as arguments,
    so they never appear in error messages.
    """
    res = subprocess.run(cmd, input=input, capture_output=True, text=True, cwd=cwd, check=False)
    if check and res.returncode != 0:
        detail = res.stderr.strip() or res.stdout.strip()
        raise ReleaseError(f"`{' '.join(cmd[:3])}` exited {res.returncode}: {detail}")
    return res.stdout


def require_env(env, *names: str) -> None:
    missing = [n for n in names if not env.get(n)]
    if missing:
        raise ReleaseError(f"missing environment: {', '.join(missing)}")


# --- versions -------------------------------------------------------------


def parse_version(tag: str) -> tuple[int, int, int] | None:
    m = VERSION_RE.match(tag)
    return tuple(int(x) for x in m.groups()) if m else None


def highest(tags: list[str]) -> str | None:
    """Highest vX.Y.Z among tags (others ignored), or None."""
    versions = [t for t in tags if parse_version(t)]
    return max(versions, key=parse_version) if versions else None


def is_latest(tag: str, released: list[str]) -> bool:
    """True when tag is the highest of released + tag (equal counts)."""
    return highest([*released, tag]) == tag


# --- internal-name patterns -----------------------------------------------


def internal_patterns(env=os.environ, deny_file: str | None = None) -> re.Pattern[bytes]:
    """Regexes for data that must never be published."""
    pats = [r"svc\.cluster\.local", r"\.tun\."]
    for var in ("CI_SERVER_HOST", "CI_REGISTRY"):
        if env.get(var):
            pats.append(re.escape(env[var]))
    deny = deny_file or env.get("RELEASE_DENY")
    if deny and pathlib.Path(deny).is_file():
        for line in pathlib.Path(deny).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pats.append(line)
    return re.compile("|".join(f"(?:{p})" for p in pats).encode())


# --- public git snapshot --------------------------------------------------


def remote_version_tags(remote: str, cwd: str | None = None) -> list[str]:
    out = run("git", "ls-remote", "--tags", remote, cwd=cwd)
    tags = []
    for line in out.splitlines():
        ref = line.split("\t")[-1]
        name = ref.removeprefix("refs/tags/")
        if ref.startswith("refs/tags/") and parse_version(name):
            tags.append(name)
    return tags


def deny_hits(commit: str, deny_file: str, cwd: str | None = None) -> str:
    """Lines of COMMIT's files matching the deny-list (git grep output)."""
    pats = [
        line.strip()
        for line in pathlib.Path(deny_file).read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not pats:
        return ""
    with tempfile.NamedTemporaryFile("w", suffix=".deny") as f:
        f.write("\n".join(pats) + "\n")
        f.flush()
        res = subprocess.run(
            ["git", "grep", "-n", "-I", "-E", "-f", f.name, commit, "--", "."],
            capture_output=True,
            text=True,
            cwd=cwd,
            check=False,
        )
    # git grep exits 1 when nothing matches.
    if res.returncode not in (0, 1):
        raise ReleaseError(f"git grep exited {res.returncode}: {res.stderr.strip()}")
    return res.stdout


def deny_hits_text(text: str, deny_file: str | os.PathLike) -> bool:
    """True when TEXT matches a deny-list pattern."""
    for line in pathlib.Path(deny_file).read_text().splitlines():
        pat = line.strip()
        if pat and not pat.startswith("#") and re.search(pat, text):
            return True
    return False


def release(
    version: str,
    commit: str = "HEAD",
    remote: str = "github",
    deny_file: str | os.PathLike = DEFAULT_DENY,
    dry_run: bool = False,
    cwd: str | None = None,
) -> dict:
    """Push COMMIT (or, with unrelated histories, one snapshot of its tree) and the tag.

    When the public main is an ancestor of COMMIT the histories are one, and
    COMMIT is pushed as it is; otherwise a snapshot commit is made on top of
    the public main.

    The tag is force-updated, so a re-run re-publishes. The public main branch
    moves only when VERSION is the highest release (or equal); an older
    hotfix gets its tag only. Stops only when the files match the deny-list.
    """
    if not parse_version(version):
        raise ReleaseError(f"not a vX.Y.Z version: {version}")
    if not pathlib.Path(deny_file).is_file():
        raise ReleaseError(f"no deny-list at {deny_file} (create it, even if empty)")
    hits = deny_hits(commit, deny_file, cwd=cwd)
    if hits:
        raise ReleaseError(f"released files match the deny-list:\n{hits}")

    tree = run("git", "rev-parse", f"{commit}^{{tree}}", cwd=cwd).strip()
    advance_main = is_latest(version, remote_version_tags(remote, cwd=cwd))

    public_ref = "refs/release/public-main"
    run("git", "update-ref", "-d", public_ref, cwd=cwd, check=False)
    heads = run("git", "ls-remote", "--heads", remote, "main", cwd=cwd).strip()
    message = f"Release {version}"
    if heads:
        run("git", "fetch", "-q", remote, f"+refs/heads/main:{public_ref}", cwd=cwd)
        shared = (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", public_ref, commit], cwd=cwd, check=False
            ).returncode
            == 0
        )
        if shared:
            # One history: the public repo is an ancestor of COMMIT, so publish
            # COMMIT itself. Every commit that becomes public is checked too.
            snapshot = run("git", "rev-parse", f"{commit}^{{commit}}", cwd=cwd).strip()
            for new in run("git", "rev-list", f"{public_ref}..{commit}", cwd=cwd).split():
                hits = deny_hits(new, deny_file, cwd=cwd)
                if hits:
                    raise ReleaseError(f"commit {new[:12]} matches the deny-list:\n{hits}")
                if deny_hits_text(run("git", "log", "-1", "--format=%B", new, cwd=cwd), deny_file):
                    raise ReleaseError(f"commit {new[:12]} message matches the deny-list")
        elif run("git", "rev-parse", f"{public_ref}^{{tree}}", cwd=cwd).strip() == tree:
            snapshot = run("git", "rev-parse", public_ref, cwd=cwd).strip()
        else:
            snapshot = run("git", "commit-tree", tree, "-p", public_ref, "-m", message, cwd=cwd)
    else:
        snapshot = run("git", "commit-tree", tree, "-m", message, cwd=cwd)
    snapshot = snapshot.strip()

    refspecs = [f"+{snapshot}:refs/tags/{version}"]
    if advance_main:
        refspecs.append(f"{snapshot}:refs/heads/main")
    log(f"release {version}: {snapshot[:12]}, main advances: {advance_main}")
    if not dry_run:
        run("git", "push", "-q", remote, *refspecs, cwd=cwd)
    return {"commit": snapshot, "advance_main": advance_main, "refspecs": refspecs}


# --- image checks ---------------------------------------------------------


def _blob(layout: pathlib.Path, digest: str) -> pathlib.Path:
    algo, hexd = digest.split(":", 1)
    return pathlib.Path(layout) / "blobs" / algo / hexd


def check_registry_manifest(raw: str) -> None:
    """A published tag must be a single image manifest, not an index."""
    media = json.loads(raw).get("mediaType", "")
    if "image.manifest" not in media and "distribution.manifest.v2" not in media:
        raise ReleaseError(f"registry has {media}, expected a single image manifest")


def check_layout(
    layout: str | os.PathLike, patterns: re.Pattern[bytes], extra_blobs: tuple[bytes, ...] = ()
) -> str:
    """Check an OCI image layout; return a summary or raise ReleaseError."""
    layout = pathlib.Path(layout)
    index_raw = (layout / "index.json").read_bytes()
    if b"attestation-manifest" in index_raw:
        raise ReleaseError("carries build attestations")
    index = json.loads(index_raw)
    if len(index.get("manifests", [])) != 1:
        raise ReleaseError(f"expected one manifest, found {len(index.get('manifests', []))}")
    mdesc = index["manifests"][0]
    manifest_raw = _blob(layout, mdesc["digest"]).read_bytes()
    manifest = json.loads(manifest_raw)
    if "image.manifest" not in manifest.get("mediaType", mdesc.get("mediaType", "")):
        raise ReleaseError(f"top-level entry is {manifest.get('mediaType')}, not an image manifest")
    config_raw = _blob(layout, manifest["config"]["digest"]).read_bytes()
    config = json.loads(config_raw)
    platform = f"{config.get('os')}/{config.get('architecture')}"
    if platform != PLATFORM:
        raise ReleaseError(f"platform is {platform}")

    files, hits = set(), []
    for blob in (index_raw, manifest_raw, config_raw, *extra_blobs):
        hits += [m.group(0).decode(errors="replace") for m in patterns.finditer(blob)]
    for layer in manifest["layers"]:
        with tarfile.open(_blob(layout, layer["digest"]), "r:*") as tar:
            for member in tar:
                name = member.name.removeprefix("./").rstrip("/")
                if name:
                    files.add(name)
                if member.isfile():
                    content = tar.extractfile(member).read()
                    hits += [
                        f"{name}: {m.group(0).decode(errors='replace')}"
                        for m in patterns.finditer(content)
                    ]
    if hits:
        raise ReleaseError("contains internal names: " + "; ".join(sorted(set(hits))))
    missing = [f for f in REQUIRED_FILES if f not in files]
    if missing:
        raise ReleaseError(f"missing files: {', '.join(missing)}")
    forbidden = sorted(f for f in files if FORBIDDEN_FILE_RE.search(f))
    if forbidden:
        raise ReleaseError(f"contains files it must not ship: {', '.join(forbidden)}")
    outside = sorted(f for f in files if f != "wgapps" and not f.startswith("wgapps/"))
    if outside:
        raise ReleaseError(f"contains files outside /wgapps: {', '.join(outside)}")
    return f"{platform}, {len(files)} paths"


def check_image(source: str, patterns: re.Pattern[bytes]) -> str:
    """Check an oci-archive:PATH or docker://REF image."""
    with tempfile.TemporaryDirectory() as tmp:
        layout = pathlib.Path(tmp, "layout")
        extra = ()
        if source.startswith("oci-archive:"):
            layout.mkdir()
            with tarfile.open(source.removeprefix("oci-archive:")) as tar:
                tar.extractall(layout, filter="data")
        elif source.startswith("docker://"):
            raw = run("skopeo", "inspect", "--raw", source)
            check_registry_manifest(raw)
            extra = (raw.encode(),)
            run("skopeo", "copy", "--quiet", source, f"oci:{layout}")
        else:
            raise ReleaseError(f"unsupported image source {source}")
        summary = check_layout(layout, patterns, extra)
    log(f"check-image {source}: clean ({summary})")
    return summary


# --- publish --------------------------------------------------------------


def publish(tag: str, archive: str, env=os.environ) -> None:
    """Images first, then the public git tag.

    Environment: IMAGE_REF (GitLab registry repo), PUBLIC_IMAGE (GHCR repo),
    PUBLIC_REPO (GitHub https URL without .git), RELEASE_DENY; skopeo and
    git logged in / configured for both registries and GitHub.
    """
    if not parse_version(tag):
        raise ReleaseError(f"not a vX.Y.Z tag: {tag}")
    require_env(env, "IMAGE_REF", "PUBLIC_IMAGE", "PUBLIC_REPO", "RELEASE_DENY")
    src = f"oci-archive:{archive}"
    public_repo = env["PUBLIC_REPO"] + ".git"
    for dest in (f"{env['IMAGE_REF']}:{tag}", f"{env['PUBLIC_IMAGE']}:{tag}"):
        run("skopeo", "copy", "--quiet", src, f"docker://{dest}")
        log(f"pushed {dest}")
    if is_latest(tag, remote_version_tags(public_repo)):
        run("skopeo", "copy", "--quiet", src, f"docker://{env['PUBLIC_IMAGE']}:latest")
        log(f"{env['PUBLIC_IMAGE']}:latest -> {tag}")
    else:
        log(f"{tag} is older than the newest release; latest unchanged")
    check_image(f"docker://{env['PUBLIC_IMAGE']}:{tag}", internal_patterns(env))
    release(tag, "HEAD", public_repo, env["RELEASE_DENY"])
    log(f"published {tag}")


# --- credentials ----------------------------------------------------------


def check_credentials(env=os.environ) -> None:
    """Read-only: GITHUB_RELEASE_TOKEN works for the repo and GHCR. Writes nothing.

    Environment: GITHUB_RELEASE_TOKEN, PUBLIC_REPO; git configured with the
    credential helper that reads the token.
    """
    require_env(env, "GITHUB_RELEASE_TOKEN", "PUBLIC_REPO")
    token = env["GITHUB_RELEASE_TOKEN"]
    req = urllib.request.Request(
        "https://api.github.com/user", headers={"Authorization": f"token {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            scopes = {s.strip() for s in resp.headers.get("X-OAuth-Scopes", "").split(",")}
    except OSError as e:
        raise ReleaseError(f"GitHub rejected the token: {e}") from None
    if not scopes & {"repo", "public_repo"}:
        raise ReleaseError(f"token lacks repo scope ({sorted(scopes)})")
    if "write:packages" not in scopes:
        raise ReleaseError(f"token lacks write:packages ({sorted(scopes)})")
    run("git", "ls-remote", "--heads", env["PUBLIC_REPO"] + ".git")
    run("skopeo", "login", "--password-stdin", "-u", "tpmullan", "ghcr.io", input=token)
    log(f"credentials ok (scopes: {', '.join(sorted(s for s in scopes if s))})")


# --- CLI ------------------------------------------------------------------


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="steam-frame-android release tooling")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("highest")
    s.add_argument("tags", nargs="*")
    s = sub.add_parser("release")
    s.add_argument("version")
    s.add_argument("commit", nargs="?", default="HEAD")
    s.add_argument("--remote", default=os.environ.get("RELEASE_REMOTE", "github"))
    s.add_argument("--deny", default=os.environ.get("RELEASE_DENY", str(DEFAULT_DENY)))
    s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("check-image")
    s.add_argument("source")
    s = sub.add_parser("publish")
    s.add_argument("tag")
    s.add_argument("archive")
    sub.add_parser("check-credentials")
    a = p.parse_args(argv)
    try:
        if a.cmd == "highest":
            print(highest(a.tags) or "")
        elif a.cmd == "release":
            release(a.version, a.commit, a.remote, a.deny, a.dry_run)
        elif a.cmd == "check-image":
            check_image(a.source, internal_patterns())
        elif a.cmd == "publish":
            publish(a.tag, a.archive)
        elif a.cmd == "check-credentials":
            check_credentials()
    except ReleaseError as e:
        log(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
