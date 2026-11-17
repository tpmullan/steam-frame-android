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
  steam-shortcuts.py sync <catalog-file>    # lines: package<TAB>label

`sync` makes the wgapps entries match the catalog: it adds a shortcut for each
package that has none and removes the wgapps shortcuts of packages that are gone.
Shortcuts that are not `wgapps steam <package>` launches, and the base "Android"
entry (`wgapps steam`), are never touched. With Steam running it talks to Steam's
own client API on the web-UI debug port (127.0.0.1:8080, or $WGAPPS_CEF_PORT);
with Steam stopped it writes shortcuts.vdf.
"""

import base64
import binascii
import json
import os
import pathlib
import re
import shlex
import socket
import struct
import subprocess
import sys
import time
import urllib.request

STEAM = pathlib.Path.home() / ".local/share/Steam"
WGAPPS = pathlib.Path.home() / ".local/share/waydroid-gapps/bin/wgapps"

SETTLE_SECONDS = 10
PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")

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


# --- sync ---------------------------------------------------------------------------


def parse_catalog(text):
    """[(package, label)] from `package<TAB>label` lines; bad packages are skipped and a
    blank label becomes the capitalised last part of the package name."""
    rows = []
    for line in text.splitlines():
        package, _, label = line.partition("\t")
        package, label = package.strip(), label.strip()
        if not PACKAGE.match(package) or len(package) > 54:
            continue
        rows.append((package, label or package.rsplit(".", 1)[-1].capitalize()))
    return rows


def wgapps_package(shortcut):
    """The package of a `wgapps steam <package>` shortcut; None for anything else, including
    the base `wgapps steam` entry."""
    exe = shlex.split(str(shortcut.get("Exe", "")) or "''")
    if exe != [str(WGAPPS)]:
        return None
    words = str(shortcut.get("LaunchOptions", "")).split()
    if len(words) == 2 and words[0] == "steam" and PACKAGE.match(words[1]):
        return words[1]
    return None


def plan(shortcuts, wanted):
    """(to_add [(package, label)], to_remove [shortcut key]) for the given catalog."""
    have = {}
    for key, shortcut in shortcuts.items():
        package = wgapps_package(shortcut)
        if package is not None:
            have.setdefault(package, key)
    packages = {package for package, _ in wanted}
    add = [(p, label) for p, label in dict(wanted).items() if p not in have]
    remove = [key for package, key in have.items() if package not in packages]
    return add, remove


class Cef:
    """A minimal websocket client for Steam's SharedJSContext page (stdlib only)."""

    def __init__(self, port):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as reply:
                pages = json.load(reply)
        except OSError as error:
            raise ConnectionError(f"no Steam debug port on 127.0.0.1:{port} ({error})") from error
        url = next(
            (p["webSocketDebuggerUrl"] for p in pages if p.get("title") == "SharedJSContext"), None
        )
        if url is None:
            sys.exit("Steam's debug port has no SharedJSContext page; restart Steam and retry")
        host, _, path = url.removeprefix("ws://").partition("/")
        address, _, port_text = host.partition(":")
        self.sock = socket.create_connection((address, int(port_text)), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET /{path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.sock.recv(1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            sys.exit(
                "Steam's debug port refused the websocket: " + head.decode(errors="replace")[:80]
            )
        self.counter = 0

    def close(self):
        self.sock.close()

    def read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise EOFError("Steam closed the debug connection")
            buf += chunk
        return buf

    def message(self):
        payload = b""
        while True:
            b1, b2 = self.read(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self.read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self.read(8))[0]
            payload += self.read(n)
            if b1 & 0x80:
                return json.loads(payload)

    def evaluate(self, expression):
        self.counter += 1
        data = json.dumps(
            {
                "id": self.counter,
                "method": "Runtime.evaluate",
                "params": {"expression": expression, "awaitPromise": True, "returnByValue": True},
            }
        ).encode()
        mask = os.urandom(4)
        n = len(data)
        header = bytearray([0x81])
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        while True:
            reply = self.message()
            if reply.get("id") == self.counter:
                break
        result = reply.get("result", {})
        if "exceptionDetails" in result or "error" in reply:
            detail = result.get("exceptionDetails", reply.get("error"))
            raise RuntimeError(f"Steam rejected {expression[:60]!r}: {detail}")
        return result.get("result", {}).get("value")


def js(value):
    return json.dumps(value, ensure_ascii=True)


def apply_live(shortcuts, to_add, to_remove, port):
    cef = Cef(port)
    try:
        for key in to_remove:
            cef.evaluate(f"SteamClient.Apps.RemoveShortcut({shortcuts[key]['appid'] & 0xFFFFFFFF})")
        for package, label in to_add:
            made = entry(label, package)
            app = cef.evaluate(
                "SteamClient.Apps.AddShortcut("
                f"{js(label)}, {js(shlex.split(made['Exe'])[0])}, "
                f'{js(shlex.split(made["StartDir"])[0])}, "")'
            )
            if not isinstance(app, int):
                raise RuntimeError(f"AddShortcut for {package} returned {app!r}")
            cef.evaluate(f"SteamClient.Apps.SetShortcutName({app}, {js(label)})")
            cef.evaluate(
                f"SteamClient.Apps.SetShortcutLaunchOptions({app}, {js(made['LaunchOptions'])})"
            )
    finally:
        cef.close()


def settle(path, packages_in, packages_out):
    """Steam writes shortcuts.vdf a few seconds after a live change; wait for it so an
    immediate second sync does not add the same entries again."""
    deadline = time.monotonic() + SETTLE_SECONDS
    while time.monotonic() < deadline:
        present = {wgapps_package(s) for s in load(path).values()}
        if packages_in <= present and not (packages_out & present):
            return
        time.sleep(0.5)


def cmd_sync(path, catalog_file):
    shortcuts = load(path)
    wanted = parse_catalog(pathlib.Path(catalog_file).read_text())
    to_add, to_remove = plan(shortcuts, wanted)
    if steam_running():
        port = int(os.environ.get("WGAPPS_CEF_PORT", "8080"))
        try:
            apply_live(shortcuts, to_add, to_remove, port)
        except ConnectionError as error:
            sys.exit(f"Steam is running and {error}; quit Steam and run sync again")
        except RuntimeError as error:
            sys.exit(str(error))
        removed = {wgapps_package(shortcuts[k]) for k in to_remove}
        settle(path, {p for p, _ in to_add}, removed)
        how = "live"
    else:
        kept = [v for k, v in shortcuts.items() if k not in to_remove]
        kept += [entry(label, package) for package, label in to_add]
        kept = {str(i): v for i, v in enumerate(kept)}
        if to_add or to_remove:
            save(path, kept)
        how = "file"
    print(f"sync ({how}): {len(to_add)} added, {len(to_remove)} removed")


def main(argv):
    if len(argv) < 2 or argv[1] not in ("list", "add", "add-exec", "remove", "sync"):
        sys.exit(__doc__)
    path = shortcuts_path()
    if argv[1] == "sync":
        if len(argv) != 3:
            sys.exit(__doc__)
        return cmd_sync(path, argv[2])
    shortcuts = load(path)
    if argv[1] == "list":
        for s in shortcuts.values():
            print(f"{s.get('AppName')}\t{s.get('Exe')} {s.get('LaunchOptions', '')}")
        return
    if steam_running():
        sys.exit("Steam is running; it would overwrite shortcuts.vdf. Quit Steam first.")
    name = argv[2]
    kept = {
        str(i): v for i, v in enumerate(s for s in shortcuts.values() if s.get("AppName") != name)
    }
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
