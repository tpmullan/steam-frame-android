#!/usr/bin/env python3
"""Add or update non-Steam shortcuts that launch Android apps via wgapps.

Steam keeps non-Steam shortcuts in a binary VDF file per Steam user:
~/.local/share/Steam/userdata/<id>/config/shortcuts.vdf. Steam rewrites that
file from memory, so only edit it while Steam is not running.

Usage:
  steam-shortcuts.py list
  steam-shortcuts.py add <name> [package]   # no package: Android home screen
  steam-shortcuts.py add-exec <name> <exe> [launch options...]
  steam-shortcuts.py remove <name>
"""

import binascii
import os
import pathlib
import shlex
import struct
import subprocess
import sys

STEAM = pathlib.Path.home() / ".local/share/Steam"
WGAPPS = pathlib.Path.home() / ".local/share/waydroid-gapps/bin/wgapps"

T_MAP, T_STR, T_INT, T_END = 0x00, 0x01, 0x02, 0x08


def read_cstr(buf, pos):
    end = buf.index(b"\x00", pos)
    return buf[pos:end].decode("utf-8"), end + 1


def parse_map(buf, pos):
    out = {}
    while True:
        t = buf[pos]
        pos += 1
        if t == T_END:
            return out, pos
        key, pos = read_cstr(buf, pos)
        if t == T_MAP:
            out[key], pos = parse_map(buf, pos)
        elif t == T_STR:
            out[key], pos = read_cstr(buf, pos)
        elif t == T_INT:
            out[key] = struct.unpack_from("<i", buf, pos)[0]
            pos += 4
        else:
            raise ValueError(f"unsupported VDF type {t:#x} at {pos - 1}")


def dump_map(d):
    out = bytearray()
    for key, val in d.items():
        k = key.encode("utf-8") + b"\x00"
        if isinstance(val, dict):
            out += bytes([T_MAP]) + k + dump_map(val)
        elif isinstance(val, int):
            out += bytes([T_INT]) + k + struct.pack("<i", val)
        else:
            out += bytes([T_STR]) + k + str(val).encode("utf-8") + b"\x00"
    return bytes(out) + bytes([T_END])


def shortcuts_path():
    users = sorted(p for p in (STEAM / "userdata").iterdir() if p.name.isdigit() and p.name != "0")
    if len(users) != 1:
        found = [u.name for u in users]
        sys.exit(f"expected one Steam user under {STEAM / 'userdata'}, found {found}")
    return users[0] / "config" / "shortcuts.vdf"


def load(path):
    if not path.exists():
        return {}
    buf = path.read_bytes()
    root, _ = parse_map(buf, 0)
    return root.get("shortcuts", {})


def save(path, shortcuts):
    ordered = {str(i): v for i, v in enumerate(shortcuts.values())}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".vdf.tmp")
    tmp.write_bytes(dump_map({"shortcuts": ordered}) + bytes([T_END]))
    os.replace(tmp, path)


def steam_running():
    result = subprocess.run(["pgrep", "-x", "steam"], capture_output=True, check=False)
    return result.returncode == 0


def appid(exe, name):
    # Steam's id for a non-Steam shortcut: crc32(exe + name) with the top bit
    # set, stored as a signed 32-bit integer.
    crc = binascii.crc32((exe + name).encode("utf-8")) | 0x80000000
    return struct.unpack("<i", struct.pack("<I", crc))[0]


def entry(name, package, exe=None, launch=None, tag="Android"):
    if exe is None:
        exe = shlex.quote(str(WGAPPS))
        start_dir = shlex.quote(str(WGAPPS.parent))
        launch = f"steam {package}".strip()
    else:
        exe = shlex.quote(exe)
        start_dir = shlex.quote(str(pathlib.Path.home()))
    return {
        "appid": appid(exe, name),
        "AppName": name,
        "Exe": exe,
        "StartDir": start_dir,
        "icon": "",
        "ShortcutPath": "",
        "LaunchOptions": launch,
        "IsHidden": 0,
        "AllowDesktopConfig": 1,
        "AllowOverlay": 1,
        "OpenVR": 0,
        "Devkit": 0,
        "DevkitGameID": "",
        "DevkitOverrideAppID": 0,
        "LastPlayTime": 0,
        "FlatpakAppID": "",
        "tags": {"0": tag},
    }


def main(argv):
    if len(argv) < 2 or argv[1] not in ("list", "add", "add-exec", "remove"):
        sys.exit(__doc__)
    path = shortcuts_path()
    shortcuts = load(path)
    if argv[1] == "list":
        for s in shortcuts.values():
            print(f"{s.get('AppName')}\t{s.get('Exe')} {s.get('LaunchOptions', '')}")
        return
    if steam_running():
        sys.exit("Steam is running; it would overwrite shortcuts.vdf. Quit Steam first.")
    name = argv[2]
    kept = {k: v for k, v in shortcuts.items() if v.get("AppName") != name}
    if argv[1] == "add":
        kept[str(len(kept))] = entry(name, argv[3] if len(argv) > 3 else "")
    elif argv[1] == "add-exec":
        if len(argv) < 4:
            sys.exit(__doc__)
        launch = shlex.join(argv[4:])
        kept[str(len(kept))] = entry(name, "", exe=argv[3], launch=launch, tag="Desktop")
    save(path, kept)
    print(f"{argv[1]}: {name} -> {path}")


if __name__ == "__main__":
    main(sys.argv)
