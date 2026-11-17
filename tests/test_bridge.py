"""wgapps-bridge: the Linux end of the shell's bridge (protocol v1, shared with the Rust crate)."""

import json
import pathlib
import socket
import tempfile
import threading
import unittest

from helpers import load

bridge = load("wgapps-bridge")

# The same lines as starforge-bridge's tests (runtime-rust/bridge in the engine repo).
HELLO = '{"type":"hello","version":1}'
CATALOG = '{"type":"catalog"}'
APPS = '{"type":"apps","apps":[{"id":"steam:220","label":"Half-Life 2","kind":"linux"}]}'
LAUNCH = '{"type":"launch","id":"steam:220"}'
LAUNCHED = '{"type":"launched","id":"steam:220","ok":true}'
ICON = '{"type":"icon","id":"steam:220"}'
ICONDATA = '{"type":"icondata","id":"steam:220","format":"jpg","data":"/9j/4A=="}'

ACF = """"AppState"
{
\t"appid"\t\t"220"
\t"Universe"\t\t"1"
\t"name"\t\t"Half-Life 2"
\t"StateFlags"\t\t"4"
}
"""


def write_library(root: pathlib.Path, games: dict[str, str]) -> None:
    root.mkdir(parents=True)
    for appid, name in games.items():
        (root / f"appmanifest_{appid}.acf").write_text(
            f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n'
            f'\t"name"\t\t"{name.replace(chr(34), chr(92) + chr(34))}"\n}}\n'
        )


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.steam = pathlib.Path(tmp.name) / "steamapps"
        write_library(
            self.steam,
            {
                "220": "Half-Life 2",
                "228980": "Steamworks Common Redistributables",
                "1493710": "Proton Experimental",
                "1628350": "Steam Linux Runtime 3.0 (sniper)",
                "400": 'Portal "Quoted"',
            },
        )
        self.launched = []
        # No X displays here, whatever machine the tests run on.
        self.session = bridge.Session(
            self.steam,
            self.launched.append,
            x11_dir=self.steam.parent / "no-x11",
            grabber=self.steam.parent / "no-grabber",
        )

    def reply(self, line):
        return [json.loads(r) for r in self.session.handle(line)]

    def test_hello_is_answered_with_ours_and_the_fixture_lines_parse(self):
        self.assertEqual(self.reply(HELLO), [{"type": "hello", "version": 1}])
        for line in (HELLO, CATALOG, APPS, LAUNCH, LAUNCHED, ICON, ICONDATA):
            json.loads(line)  # the fixtures are valid JSON

    def test_catalog_lists_games_sorted_without_tools(self):
        (answer,) = self.reply(CATALOG)
        self.assertEqual(answer["type"], "apps")
        self.assertEqual(
            [(a["id"], a["label"], a["kind"]) for a in answer["apps"]],
            [("steam:220", "Half-Life 2", "linux"), ("steam:400", 'Portal "Quoted"', "linux")],
        )

    def test_launch_starts_the_game_and_says_so(self):
        self.assertEqual(self.reply(LAUNCH), [{"type": "launched", "id": "steam:220", "ok": True}])
        self.assertEqual(self.launched, [["steam", "steam://rungameid/220"]])

    def test_launch_refuses_ids_that_are_not_steam_apps(self):
        for bad in ("steam:", "steam:1;id", "com.a/.B", "steam:99999999999999", "../x"):
            line = json.dumps({"type": "launch", "id": bad})
            self.assertEqual(self.reply(line), [{"type": "launched", "id": bad, "ok": False}], bad)
        self.assertEqual(self.launched, [])

    def test_a_game_that_is_not_installed_is_not_launched(self):
        line = json.dumps({"type": "launch", "id": "steam:777"})
        self.assertEqual(self.reply(line), [{"type": "launched", "id": "steam:777", "ok": False}])
        self.assertEqual(self.launched, [])

    def test_unknown_messages_are_ignored_and_garbage_gets_an_error(self):
        self.assertEqual(self.reply('{"type":"teleport"}'), [])
        self.assertEqual(self.reply("   "), [])
        self.assertEqual(self.reply("not json")[0]["type"], "error")
        self.assertEqual(self.reply('{"type":"launch"}')[0]["type"], "error")
        self.assertEqual(self.reply("[1,2]")[0]["type"], "error")

    def test_a_flood_of_errors_is_cut_off(self):
        replies = sum(len(self.session.handle("not json")) for _ in range(200))
        self.assertLessEqual(replies, bridge.MAX_ERRORS)


class IconTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        self.steamapps = root / "steamapps"
        write_library(self.steamapps, {"220": "Half-Life 2", "400": "Portal"})
        self.cache = root / "librarycache"
        self.icon = bytes([0xFF, 0xD8, 0xFF, 0xE0])
        game = self.cache / "220"
        (game / "subdir").mkdir(parents=True)
        (game / ("a" * 40 + ".jpg")).write_bytes(self.icon)
        (game / "header.jpg").write_bytes(b"not the icon")
        (game / "subdir" / ("b" * 40 + ".jpg")).write_bytes(b"nested: ignored")
        self.session = bridge.Session(self.steamapps, lambda argv: None, librarycache=self.cache)

    def reply(self, line):
        return [json.loads(r) for r in self.session.handle(line)]

    def test_an_installed_games_small_icon_is_sent_as_base64(self):
        (answer,) = self.reply(ICON)
        self.assertEqual(
            answer,
            {"type": "icondata", "id": "steam:220", "format": "jpg", "data": "/9j/4A=="},
        )

    def test_a_game_without_an_icon_or_not_installed_gets_empty_data(self):
        for ident in ("steam:400", "steam:777"):
            line = json.dumps({"type": "icon", "id": ident})
            self.assertEqual(
                self.reply(line), [{"type": "icondata", "id": ident, "format": "", "data": ""}]
            )

    def test_bad_ids_get_empty_data_and_never_touch_the_filesystem(self):
        for bad in ("../../etc", "steam:../1", "220", "steam:"):
            line = json.dumps({"type": "icon", "id": bad})
            (answer,) = self.reply(line)
            self.assertEqual(answer["data"], "", bad)

    def test_an_oversize_icon_is_not_sent(self):
        (self.cache / "220" / ("a" * 40 + ".jpg")).write_bytes(b"x" * (bridge.MAX_ICON + 1))
        (answer,) = self.reply(ICON)
        self.assertEqual(answer["data"], "")

    def test_a_png_icon_is_labelled_png(self):
        game = self.cache / "400"
        game.mkdir()
        (game / ("c" * 40 + ".png")).write_bytes(b"\x89PNG")
        line = json.dumps({"type": "icon", "id": "steam:400"})
        (answer,) = self.reply(line)
        self.assertEqual((answer["format"], bool(answer["data"])), ("png", True))


class StreamTests(unittest.TestCase):
    def test_only_real_x_displays_are_watchable(self):
        for good in (":0", ":1", ":12"):
            self.assertTrue(bridge.valid_display(good), good)
        for bad in ("", "0", ":", ":x", ":123", ":0.0", ":0;id", "host:0", ":-1", ":0 "):
            self.assertFalse(bridge.valid_display(bad), bad)

    def test_gamescope_is_a_watchable_source_and_runs_the_pipewire_grabber(self):
        self.assertTrue(bridge.valid_source("gamescope"))
        self.assertTrue(bridge.valid_source(":0"))
        for bad in ("Gamescope", "gamescope ", "gamescope;id", "screen", ""):
            self.assertFalse(bridge.valid_source(bad), bad)
        argv = bridge.grab_command("gamescope", 5)
        self.assertEqual(argv[0].split("/")[-1], "wgapps-gamescope-grab")
        self.assertEqual(
            argv[1:],
            ["--fps", "5", "--width", str(bridge.STREAM_W), "--height", str(bridge.STREAM_H)],
        )

    def test_the_catalog_offers_the_gamescope_screen_when_the_grabber_is_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam = pathlib.Path(tmp) / "steamapps"
            write_library(steam, {"220": "Half-Life 2"})
            grabber = pathlib.Path(tmp) / "wgapps-gamescope-grab"
            session = bridge.Session(
                steam, lambda argv: None, x11_dir=pathlib.Path(tmp) / "none", grabber=grabber
            )
            (answer,) = [json.loads(r) for r in session.handle(CATALOG)]
            self.assertNotIn("screen:0", [a["id"] for a in answer["apps"]])
            grabber.write_text("#!/bin/sh\n")
            (answer,) = [json.loads(r) for r in session.handle(CATALOG)]
            screens = [a for a in answer["apps"] if a["id"] == "screen:0"]
            self.assertEqual(
                screens, [{"id": "screen:0", "label": "Screen (gamescope)", "kind": "linux"}]
            )

    def test_the_grab_command_scales_to_the_panel_and_emits_raw_rgba(self):
        argv = bridge.grab_command(":0", 5)
        self.assertEqual(argv[0], "ffmpeg")
        self.assertIn("x11grab", argv)
        self.assertEqual(argv[argv.index("-i") + 1], ":0")
        self.assertEqual(argv[argv.index("-framerate") + 1], "5")
        self.assertIn(f"scale={bridge.STREAM_W}:{bridge.STREAM_H},format=rgba", argv)
        self.assertEqual(argv[-1], "-")

    def test_frame_header_is_two_little_endian_u32s(self):
        self.assertEqual(
            bridge.frame_header(),
            bridge.STREAM_W.to_bytes(4, "little") + bridge.STREAM_H.to_bytes(4, "little"),
        )

    def test_x_displays_are_listed_from_the_socket_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("X0", "X1", "X11", "junk", "Xabc", "X123"):
                (pathlib.Path(tmp) / name).write_text("")
            self.assertEqual(bridge.x_displays(pathlib.Path(tmp)), [":0", ":1", ":11"])
            self.assertEqual(bridge.x_displays(pathlib.Path(tmp) / "missing"), [])

    def test_the_catalog_offers_each_display_as_a_linux_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam = pathlib.Path(tmp) / "steamapps"
            write_library(steam, {"220": "Half-Life 2"})
            x11 = pathlib.Path(tmp) / "x11"
            x11.mkdir()
            (x11 / "X0").write_text("")
            session = bridge.Session(steam, lambda argv: None, x11_dir=x11)
            (answer,) = [json.loads(r) for r in session.handle(CATALOG)]
            ids = [(a["id"], a["kind"]) for a in answer["apps"]]
            self.assertIn(("x11:0", "linux"), ids)
            self.assertIn(("steam:220", "linux"), ids)
            # A display is watched, not launched: the launcher says no and the shell opens a panel.
            reply = [json.loads(r) for r in session.handle('{"type":"launch","id":"x11:0"}')]
            self.assertEqual(reply, [{"type": "launched", "id": "x11:0", "ok": False}])

    def test_frames_are_streamed_over_the_stream_socket_until_the_client_leaves(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / "fake-grab"
            size = bridge.STREAM_W * bridge.STREAM_H * 4
            fake.write_text(
                "#!/usr/bin/env python3\nimport sys\n"
                f"for i in range(3): sys.stdout.buffer.write(bytes([i + 1]) * {size})\n"
                "sys.stdout.buffer.flush()\n"
            )
            fake.chmod(0o755)
            path = pathlib.Path(tmp) / "stream.sock"
            server = bridge.serve_stream(path, grab=lambda display, fps: [str(fake)])
            self.addCleanup(server.close)
            threading.Thread(target=server.run, daemon=True).start()
            client = socket.socket(socket.AF_UNIX)
            client.settimeout(10)
            client.connect(str(path))
            client.sendall(b'{"display":":0","fps":5}\n')

            def read(n):
                data = b""
                while len(data) < n:
                    chunk = client.recv(min(1 << 20, n - len(data)))
                    if not chunk:
                        raise AssertionError("stream ended early")
                    data += chunk
                return data

            self.assertEqual(read(8), bridge.frame_header())
            first = read(size)
            self.assertEqual((first[0], first[-1]), (1, 1))
            self.assertEqual(read(8), bridge.frame_header())
            client.close()
            self.assertEqual(oct(path.stat().st_mode)[-3:], "666")

    def test_closing_the_server_ends_a_grab_that_is_still_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / "slow-grab"
            fake.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n")
            fake.chmod(0o755)
            path = pathlib.Path(tmp) / "stream.sock"
            server = bridge.serve_stream(path, grab=lambda display, fps: [str(fake)])
            threading.Thread(target=server.run, daemon=True).start()
            client = socket.socket(socket.AF_UNIX)
            client.settimeout(5)
            client.connect(str(path))
            client.sendall(b'{"display":":0","fps":5}\n')
            for _ in range(100):
                with server.lock:
                    running = list(server.processes)
                if running:
                    break
                threading.Event().wait(0.05)
            self.assertEqual(len(running), 1)
            server.close()
            self.assertIsNotNone(running[0].wait(timeout=5))
            client.close()

    def test_a_bad_watch_request_is_closed_without_streaming(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "stream.sock"
            ran = []
            server = bridge.serve_stream(path, grab=lambda d, f: ran.append(d) or ["true"])
            self.addCleanup(server.close)
            threading.Thread(target=server.run, daemon=True).start()
            for request in (
                b'{"display":"x"}\n',
                b"junk\n",
                b'{"display":":0;id"}\n',
                b'{"display":"gamescope;id"}\n',
            ):
                client = socket.socket(socket.AF_UNIX)
                client.settimeout(5)
                client.connect(str(path))
                client.sendall(request)
                self.assertEqual(client.recv(16), b"")
                client.close()
            self.assertEqual(ran, [])


class DefaultsTests(unittest.TestCase):
    def test_the_library_cache_is_beside_steamapps(self):
        steamapps = pathlib.Path("/home/u/.local/share/Steam/steamapps")
        self.assertEqual(
            bridge.default_librarycache(steamapps),
            pathlib.Path("/home/u/.local/share/Steam/appcache/librarycache"),
        )


class AcfTests(unittest.TestCase):
    def test_a_manifest_gives_its_appid_and_name(self):
        self.assertEqual(bridge.parse_acf(ACF), ("220", "Half-Life 2"))

    def test_incomplete_or_odd_manifests_give_nothing(self):
        for text in ("", '"AppState"\n{\n}\n', '"AppState"\n{\n"appid" "12x"\n"name" "N"\n}\n'):
            self.assertIsNone(bridge.parse_acf(text), text)

    def test_names_longer_than_the_limit_are_cut(self):
        text = '"AppState"\n{\n"appid" "5"\n"name" "' + "n" * 500 + '"\n}\n'
        self.assertEqual(len(bridge.parse_acf(text)[1]), bridge.MAX_LABEL)


class LineReaderTests(unittest.TestCase):
    def test_lines_are_split_across_reads_and_oversize_lines_dropped(self):
        reader = bridge.LineReader()
        self.assertEqual(reader.feed(b'{"type":"cat'), [])
        self.assertEqual(reader.feed(b'alog"}\n{"a'), ['{"type":"catalog"}'])
        big = b"x" * (bridge.MAX_LINE + 10) + b"\n"
        # The unfinished '{"a' runs on into the oversize line, which is dropped whole; the line
        # after it still arrives.
        self.assertEqual(reader.feed(big + b'{"type":"catalog"}\n'), ['{"type":"catalog"}'])


class SocketTests(unittest.TestCase):
    def test_a_client_gets_hello_and_a_catalog_over_the_real_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam = pathlib.Path(tmp) / "steamapps"
            write_library(steam, {"220": "Half-Life 2"})
            path = pathlib.Path(tmp) / "bridge.sock"
            server = bridge.serve(path, steam, lambda argv: None)
            self.addCleanup(server.close)
            threading.Thread(target=server.run, daemon=True).start()
            client = socket.socket(socket.AF_UNIX)
            client.settimeout(5)
            client.connect(str(path))
            client.sendall((HELLO + "\n" + CATALOG + "\n").encode())
            data = b""
            while data.count(b"\n") < 2:
                data += client.recv(4096)
            lines = [json.loads(line) for line in data.splitlines()]
            self.assertEqual(lines[0], {"type": "hello", "version": 1})
            self.assertEqual(lines[1]["apps"][0]["id"], "steam:220")
            client.close()
            self.assertEqual(oct(path.stat().st_mode)[-3:], "666")


if __name__ == "__main__":
    unittest.main()
