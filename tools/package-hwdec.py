#!/usr/bin/env python3
"""Pack a built hardware-decode tree into hwdec/wgapps-hwdec.tar.xz, the same bytes every time.

The tree is the one tools/v4l2-codec2/README.md ends with: vendor/ and system/ with the files the
Codec2 V4L2 service needs. Entries are sorted, owned by root, with a fixed time and mode, so packing
the same files twice gives the same archive and SHA256SUMS only changes when the files do.

Usage: tools/package-hwdec.py TREE [OUT_DIR]     (OUT_DIR defaults to hwdec/)
"""

from __future__ import annotations

import hashlib
import io
import lzma
import pathlib
import sys
import tarfile

ARCHIVE = "wgapps-hwdec.tar.xz"
EPOCH = 1_700_000_000  # a fixed modification time (2023-11-14), so the archive does not change


def tree_files(tree: pathlib.Path) -> list[pathlib.Path]:
    """The regular files of the tree, sorted and relative; links and special files are refused."""
    found = []
    for path in sorted(tree.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise SystemExit(f"package-hwdec: {path} is not a plain file or directory")
        if path.is_file():
            found.append(path.relative_to(tree))
    if not found:
        raise SystemExit(f"package-hwdec: {tree} holds no files")
    return found


def pack(tree: pathlib.Path) -> bytes:
    """The deterministic .tar.xz of the tree."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel in tree_files(tree):
            source = tree / rel
            info = tarfile.TarInfo(str(rel))
            info.size = source.stat().st_size
            info.mtime = EPOCH
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
            with source.open("rb") as handle:
                tar.addfile(info, handle)
    return lzma.compress(raw.getvalue(), preset=9 | lzma.PRESET_EXTREME)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    tree = pathlib.Path(argv[1])
    out = (
        pathlib.Path(argv[2])
        if len(argv) == 3
        else pathlib.Path(__file__).resolve().parent.parent / "hwdec"
    )
    out.mkdir(parents=True, exist_ok=True)
    data = pack(tree)
    (out / ARCHIVE).write_bytes(data)
    (out / "SHA256SUMS").write_text(f"{sha256(data)}  {ARCHIVE}\n")
    print(
        f"package-hwdec: {len(tree_files(tree))} files -> {out / ARCHIVE} "
        f"({len(data)} bytes, {sha256(data)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
