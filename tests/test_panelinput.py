"""wgapps-panelinput: taps the VR shell asks for on a 2D app's panel become `input -d` commands."""

import os
import pathlib
import tempfile
import unittest

from helpers import load

pi = load("wgapps-panelinput")


class ParseTests(unittest.TestCase):
    def test_good_lines_become_requests_in_order(self):
        self.assertEqual(
            pi.parse("tap 2 10 20\ntap 3 0 719\n"),
            [("tap", 2, 10, 20), ("tap", 3, 0, 719)],
        )

    def test_open_and_close_requests(self):
        text = "open 2 com.android.settings/.Settings\nclose com.android.settings\n"
        self.assertEqual(
            pi.parse(text),
            [("open", 2, "com.android.settings/.Settings"), ("close", "com.android.settings")],
        )

    def test_swipes_are_a_display_two_points_and_a_duration(self):
        self.assertEqual(
            pi.parse("swipe 2 100 400 100 200 100\n"), [("swipe", 2, 100, 400, 100, 200, 100)]
        )
        for bad in (
            "swipe 0 1 1 1 1 100",  # the main display
            "swipe 2 1 1 1 100",  # a number missing
            "swipe 2 9000 1 1 1 100",  # off any screen
            "swipe 2 1 1 1 1 5000",  # too slow to be a swipe
            "swipe 2 1 1 1 1 -5",
            "swipe 2 a 1 1 1 100",
        ):
            self.assertEqual(pi.parse(bad), [], bad)
        self.assertEqual(
            pi.command("c", ("swipe", 2, 100, 400, 100, 200, 100)),
            ["podman", "exec", "c", "input", "-d", "2", "swipe", "100", "400", "100", "200", "100"],
        )

    def test_mode_requests_are_panel_or_vr_and_nothing_else(self):
        text = "mode panel\nmode vr\nmode steam\nmode panel now\nmode\nmode  vr\n"
        self.assertEqual(pi.parse(text), [("mode", "panel"), ("mode", "vr")])

    def test_names_that_are_not_package_and_component_names_are_dropped(self):
        text = "\n".join(
            [
                "open 2 a.b/.C d",  # extra word
                "open 2 a.b;id/.C",  # metacharacter
                "open 2 nocomponent",
                "open 0 a.b/.C",  # the main display
                "open 2 a.b/.C$Inner",  # inner classes are legal
                "close a b",
                "close ../etc",
                "close a.b",
            ]
        )
        self.assertEqual(pi.parse(text), [("open", 2, "a.b/.C$Inner"), ("close", "a.b")])

    def test_anything_else_is_skipped(self):
        text = "\n".join(
            [
                "tap 2 10",  # missing a number
                "tap two 1 2",  # not numbers
                "tap 2 1 2 3",  # extra
                "swipe 2 1 2",  # not a tap
                "tap 2 -1 5",  # negative
                "tap 0 5 5",  # display 0 is the main display: never from here
                "tap 100 5 5",  # no such display
                "tap 2 9000 5",  # outside any screen
                "rm -rf /",
                "tap 2 5 5; id",  # no shell metacharacters get through
                "tap 4 6 7",
            ]
        )
        self.assertEqual(pi.parse(text), [("tap", 4, 6, 7)])

    def test_a_flood_is_cut_to_a_batch(self):
        taps = pi.parse("tap 2 1 1\n" * 500)
        self.assertEqual(len(taps), pi.MAX_PER_BATCH)

    def test_commands_are_argument_lists_run_in_the_container(self):
        c = "waydroid-gapps"
        self.assertEqual(
            pi.command(c, ("tap", 2, 10, 20)),
            ["podman", "exec", c, "input", "-d", "2", "tap", "10", "20"],
        )
        self.assertEqual(
            pi.command(c, ("open", 2, "a.b/.C")),
            ["podman", "exec", c, "am", "start", "--display", "2", "-n", "a.b/.C"],
        )
        self.assertEqual(
            pi.command(c, ("close", "a.b")), ["podman", "exec", c, "am", "force-stop", "a.b"]
        )
        # Panel mode: stop the VR shell and show Android's home on the flat panel.
        self.assertEqual(
            pi.command(c, ("mode", "panel")),
            [
                "podman",
                "exec",
                c,
                "sh",
                "-c",
                "am force-stop rs.starforge.xrhost; input keyevent 3",
            ],
        )
        # VR mode: start the shell.
        self.assertEqual(
            pi.command(c, ("mode", "vr")),
            ["podman", "exec", c, "am", "start", "-n", "rs.starforge.xrhost/rs.starforge.Activity"],
        )

    def test_vr_mode_first_stops_every_other_vr_app_the_catalog_lists(self):
        # SteamVR runs one scene app at a time per Steam app key: a VR app left running (Wolvic)
        # makes the shell's session start fail, so they are stopped before the shell starts.
        with tempfile.TemporaryDirectory() as tmp:
            share = pathlib.Path(tmp)
            (share / "apps.tsv").write_text(
                "com.igalia.wolvic.vanilla\tWolvic\tcom.igalia.wolvic.vanilla/.Main\txr\n"
                "com.android.settings\tSettings\tcom.android.settings/.S\t2d\n"
                "org.khronos.openxr.hello_xr.opengles\tHello\torg.khronos.openxr.hello_xr.opengles/.A\txr\n"
                "bad name\tX\tbad/.C\txr\n"
            )
            commands = pi.commands("c", ("mode", "vr"), share)
            self.assertEqual(
                commands[:-1],
                [
                    ["podman", "exec", "c", "am", "force-stop", "com.igalia.wolvic.vanilla"],
                    [
                        "podman",
                        "exec",
                        "c",
                        "am",
                        "force-stop",
                        "org.khronos.openxr.hello_xr.opengles",
                    ],
                ],
            )
            self.assertEqual(commands[-1][-2:], ["-n", "rs.starforge.xrhost/rs.starforge.Activity"])
            # Without a catalog, or for other requests, nothing extra.
            self.assertEqual(len(pi.commands("c", ("mode", "vr"), share / "none")), 1)
            self.assertEqual(len(pi.commands("c", ("tap", 2, 1, 1), share)), 1)


class ConsumeTests(unittest.TestCase):
    def test_a_request_file_is_taken_once_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "panel-input"
            path.write_text("tap 2 1 2\n")
            self.assertEqual(pi.consume(path), "tap 2 1 2\n")
            self.assertFalse(path.exists())
            self.assertIsNone(pi.consume(path))
            self.assertEqual(os.listdir(tmp), [])

    def test_lines_appended_while_consuming_are_not_lost(self):
        # consume() renames first, so a writer that opens the path again makes a new file.
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "panel-input"
            path.write_text("tap 2 1 1\n")
            first = pi.consume(path)
            path.write_text("tap 2 2 2\n")
            self.assertEqual((first, pi.consume(path)), ("tap 2 1 1\n", "tap 2 2 2\n"))


class RunTests(unittest.TestCase):
    def test_one_batch_runs_each_tap_through_the_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "panel-input"
            path.write_text("tap 2 1 2\nbad\ntap 2 3 4\n")
            ran = []
            n = pi.run_once(path, "c", ran.append)
            self.assertEqual(n, 2)
            self.assertEqual([r[-2:] for r in ran], [["1", "2"], ["3", "4"]])

    def test_open_then_tap_run_in_the_order_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "panel-input"
            path.write_text("open 2 a.b/.C\ntap 2 5 6\nclose a.b\n")
            ran = []
            pi.run_once(path, "c", ran.append)
            self.assertEqual([r[3] for r in ran], ["am", "input", "am"])

    def test_no_file_no_taps(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(pi.run_once(pathlib.Path(tmp) / "nope", "c", lambda c: None), 0)


if __name__ == "__main__":
    unittest.main()
