import base64
import contextlib
import hashlib
import io
import json
import os
import pathlib
import socket
import struct
import tempfile
import threading
import unittest
from unittest import mock

from helpers import load

sc = load("steam-shortcuts.py")


class VdfTests(unittest.TestCase):
    def test_round_trip(self):
        shortcuts = {"0": sc.entry("Android", ""), "1": sc.entry("Plex", "com.plexapp.android")}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, "shortcuts.vdf")
            sc.save(path, shortcuts)
            back = sc.load(path)
        self.assertEqual(back["0"]["AppName"], "Android")
        self.assertEqual(back["1"]["LaunchOptions"], "steam com.plexapp.android")
        self.assertEqual(back["1"]["tags"], {"0": "Android"})
        self.assertEqual(back["1"]["appid"], shortcuts["1"]["appid"])

    def test_appid_has_top_bit_set_and_is_stable(self):
        a = sc.appid("/x/wgapps", "Plex")
        self.assertLess(a, 0)
        self.assertEqual(a, sc.appid("/x/wgapps", "Plex"))
        self.assertNotEqual(a, sc.appid("/x/wgapps", "Android"))


def read_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


class FakeCef:
    """Steam's CEF debug port: /json lists SharedJSContext; its websocket answers
    Runtime.evaluate. `handler(expression)` returns the value (or raises to report an exception)."""

    def __init__(self, handler, title="SharedJSContext"):
        self.handler = handler
        self.title = title
        self.expressions = []
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def close(self):
        self.server.close()

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
        with conn:
            head = b""
            while b"\r\n\r\n" not in head:
                head += conn.recv(1)
            request = head.decode().split("\r\n")
            if request[0].startswith("GET /json"):
                body = json.dumps(
                    [
                        {
                            "title": self.title,
                            "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/page/1",
                        }
                    ]
                ).encode()
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\n\r\n".encode()
                    + body
                )
                return
            key = next(
                line.split(": ", 1)[1]
                for line in request
                if line.lower().startswith("sec-websocket-key")
            )
            accept = base64.b64encode(
                hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
            ).decode()
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                    f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode()
            )
            try:
                while True:
                    b1, b2 = read_exact(conn, 2)
                    n = b2 & 0x7F
                    if n == 126:
                        n = struct.unpack(">H", read_exact(conn, 2))[0]
                    elif n == 127:
                        n = struct.unpack(">Q", read_exact(conn, 8))[0]
                    mask = read_exact(conn, 4)
                    data = bytes(b ^ mask[i % 4] for i, b in enumerate(read_exact(conn, n)))
                    message = json.loads(data)
                    expression = message["params"]["expression"]
                    self.expressions.append(expression)
                    try:
                        reply = {
                            "result": {"result": {"type": "x", "value": self.handler(expression)}}
                        }
                    except Exception as error:  # noqa: BLE001
                        reply = {"result": {"exceptionDetails": {"text": str(error)}}}
                    out = json.dumps({"id": message["id"], **reply}).encode()
                    header = bytes([0x81])
                    header += bytes([n_len]) if (n_len := len(out)) < 126 else b""
                    if len(out) >= 126:
                        header += bytes([126]) + struct.pack(">H", len(out))
                    conn.sendall(header + out)
            except (EOFError, OSError):
                return


class SyncTests(unittest.TestCase):
    EXE = "/home/u/.local/share/waydroid-gapps/bin/wgapps"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        self.vdf = self.tmp / "userdata/1234/config/shortcuts.vdf"
        self.vdf.parent.mkdir(parents=True)
        for patcher in (
            mock.patch.object(sc, "STEAM", self.tmp),
            mock.patch.object(sc, "WGAPPS", pathlib.Path(self.EXE)),
            mock.patch.object(sc, "steam_running", lambda: False),
            mock.patch.object(sc, "SETTLE_SECONDS", 0),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"WGAPPS_CEF_PORT": "1"})  # nothing listens on port 1
        env.start()
        self.addCleanup(env.stop)
        self.catalog = self.tmp / "catalog.tsv"

    def write(self, *entries):
        sc.save(self.vdf, {str(i): e for i, e in enumerate(entries)})

    def sync(self, *rows):
        self.catalog.write_text("".join(f"{pkg}\t{label}\n" for pkg, label in rows))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sc.main(["steam-shortcuts.py", "sync", str(self.catalog)])
        return out.getvalue()

    def names(self):
        return {s["AppName"]: s["LaunchOptions"] for s in sc.load(self.vdf).values()}

    def test_sync_adds_missing_and_keeps_existing_appids_stable(self):
        android = sc.entry("Android", "")
        plex = sc.entry("Plex", "com.plexapp.android")
        self.write(android, plex)
        self.sync(("com.plexapp.android", "Plex"), ("org.mozilla.fennec", "Firefox"))
        shortcuts = sc.load(self.vdf)
        self.assertEqual(
            self.names(),
            {
                "Android": "steam",
                "Plex": "steam com.plexapp.android",
                "Firefox": "steam org.mozilla.fennec",
            },
        )
        by_name = {s["AppName"]: s for s in shortcuts.values()}
        self.assertEqual(by_name["Plex"]["appid"], plex["appid"])
        self.assertEqual(by_name["Android"]["appid"], android["appid"])

    def test_sync_removes_our_entries_of_uninstalled_apps(self):
        self.write(
            sc.entry("Android", ""),
            sc.entry("Plex", "com.plexapp.android"),
            sc.entry("Gone", "com.gone.app"),
        )
        self.sync(("com.plexapp.android", "Plex"))
        self.assertEqual(set(self.names()), {"Android", "Plex"})

    def test_sync_never_touches_entries_that_are_not_wgapps_launches(self):
        mine = sc.entry("Moonlight", "", exe="/usr/bin/moonlight", launch="stream", tag="Desktop")
        lookalike = sc.entry("Lookalike", "com.x.y")
        lookalike["Exe"] = "/usr/bin/other"
        lookalike["LaunchOptions"] = "steam com.x.y"
        other_options = sc.entry("Android", "")
        other_options["LaunchOptions"] = "doctor"
        self.write(mine, lookalike, other_options)
        self.sync()
        self.assertEqual(set(self.names()), {"Moonlight", "Lookalike", "Android"})

    def test_the_base_android_entry_is_kept_even_with_an_empty_catalog(self):
        self.write(sc.entry("Android", ""))
        self.sync()
        self.assertEqual(self.names(), {"Android": "steam"})

    def test_removing_a_middle_entry_and_adding_one_loses_nothing(self):
        self.write(
            sc.entry("Android", ""),
            sc.entry("Gone", "com.gone.app"),
            sc.entry("Plex", "com.plexapp.android"),
        )
        self.sync(("com.plexapp.android", "Plex"), ("com.a.b", "Alpha"))
        self.assertEqual(set(self.names()), {"Android", "Plex", "Alpha"})

    def test_sync_is_idempotent(self):
        self.write(sc.entry("Android", ""))
        self.sync(("com.a.b", "Alpha"), ("com.c.d", "Charlie"))
        first = self.vdf.read_bytes()
        out = self.sync(("com.a.b", "Alpha"), ("com.c.d", "Charlie"))
        self.assertEqual(self.vdf.read_bytes(), first)
        self.assertIn("0 added, 0 removed", out)

    def test_sync_without_a_shortcuts_file_creates_it(self):
        self.sync(("com.a.b", "Alpha"))
        self.assertEqual(self.names(), {"Alpha": "steam com.a.b"})

    def test_catalog_lines_with_bad_packages_or_blank_labels_are_handled(self):
        self.catalog.write_text("not a package\tBad\ncom.ok.app\t\n\n../x\tEvil\n")
        with contextlib.redirect_stdout(io.StringIO()):
            sc.main(["steam-shortcuts.py", "sync", str(self.catalog)])
        # A blank label falls back to the package's last part; bad packages are skipped.
        self.assertEqual(self.names(), {"App": "steam com.ok.app"})

    def test_file_mode_still_refuses_while_steam_runs(self):
        self.write(sc.entry("Android", ""))
        with (
            mock.patch.object(sc, "steam_running", lambda: True),
            self.assertRaises(SystemExit) as raised,
        ):
            self.sync(("com.a.b", "Alpha"))
        self.assertIn("Steam is running", str(raised.exception))
        self.assertEqual(self.names(), {"Android": "steam"})

    def test_falls_back_to_file_mode_when_the_debug_port_is_absent(self):
        # Steam stopped: nothing listens, so the file is written.
        self.write(sc.entry("Android", ""))
        self.sync(("com.a.b", "Alpha"))
        self.assertIn("Alpha", self.names())

    # --- live mode ----------------------------------------------------------------------

    def start_cef(self, **kwargs):
        ids = iter(range(3_000_000_000, 3_000_000_100))

        def handler(expression):
            if "AddShortcut" in expression:
                return next(ids)
            return None

        cef = FakeCef(kwargs.get("handler", handler))
        self.addCleanup(cef.close)
        env = mock.patch.dict(os.environ, {"WGAPPS_CEF_PORT": str(cef.port)})
        env.start()
        self.addCleanup(env.stop)
        steam = mock.patch.object(sc, "steam_running", lambda: True)
        steam.start()
        self.addCleanup(steam.stop)
        return cef

    def test_live_mode_issues_add_then_name_then_launch_options_and_uses_the_returned_id(self):
        cef = self.start_cef()
        self.write(sc.entry("Android", ""))
        out = self.sync(("org.mozilla.fennec", "Firefox"))
        self.assertEqual(len(cef.expressions), 3)
        add, name, options = cef.expressions
        self.assertIn("SteamClient.Apps.AddShortcut(", add)
        self.assertIn(self.EXE, add)
        self.assertIn('SetShortcutName(3000000000, "Firefox")', name)
        self.assertIn('SetShortcutLaunchOptions(3000000000, "steam org.mozilla.fennec")', options)
        self.assertIn("1 added, 0 removed", out)
        self.assertIn("live", out)

    def test_live_mode_removes_by_the_unsigned_appid_of_our_entry(self):
        cef = self.start_cef()
        gone = sc.entry("Gone", "com.gone.app")
        self.write(sc.entry("Android", ""), gone)
        self.sync()
        self.assertEqual(
            cef.expressions,
            [f"SteamClient.Apps.RemoveShortcut({gone['appid'] & 0xFFFFFFFF})"],
        )

    def test_live_mode_quotes_labels_safely(self):
        cef = self.start_cef()
        self.write(sc.entry("Android", ""))
        self.sync(("com.q.r", 'Say "hi"\\ </script>'))
        self.assertIn(
            'SetShortcutName(3000000000, "Say \\"hi\\"\\\\ </script>")', cef.expressions[1]
        )

    def test_live_mode_reports_a_steam_error_and_stops(self):
        def handler(expression):
            raise RuntimeError("boom")

        self.start_cef(handler=handler)
        self.write(sc.entry("Android", ""))
        with self.assertRaises(SystemExit) as raised:
            self.sync(("com.a.b", "Alpha"))
        self.assertIn("boom", str(raised.exception))

    def test_live_mode_without_the_shared_context_page_says_so(self):
        cef = FakeCef(lambda expression: None, title="Something else")
        self.addCleanup(cef.close)
        env = mock.patch.dict(os.environ, {"WGAPPS_CEF_PORT": str(cef.port)})
        env.start()
        self.addCleanup(env.stop)
        with (
            mock.patch.object(sc, "steam_running", lambda: True),
            self.assertRaises(SystemExit) as raised,
        ):
            self.sync(("com.a.b", "Alpha"))
        self.assertIn("SharedJSContext", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
