import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

from helpers import BIN, load

aw = load("wgapps-appwatch")


class PollTests(unittest.TestCase):
    def run_polls(self, results, grace=3):
        state = aw.new_state()
        for number, result in enumerate(results, start=1):
            state, code = aw.poll(state, result, grace)
            if code is not None:
                return code, number
        return None, len(results)

    def test_exits_when_package_has_no_process(self):
        self.assertEqual(self.run_polls(["up", "up", "down", "down"]), (0, 4))

    def test_exits_nonzero_when_container_stops(self):
        self.assertEqual(self.run_polls(["up", "stopped"]), (1, 2))

    def test_one_missed_poll_does_not_end_it(self):
        self.assertEqual(self.run_polls(["up", "down", "up", "down", "up"]), (None, 5))

    def test_an_app_that_never_starts_ends_after_the_grace_period(self):
        self.assertEqual(self.run_polls(["down"] * 10, grace=3), (0, 3))

    def test_a_slow_start_within_the_grace_period_is_waited_for(self):
        self.assertEqual(
            self.run_polls(["down", "down", "up", "up", "down", "down"], grace=3), (0, 6)
        )

    def test_stopped_wins_even_during_the_grace_period(self):
        self.assertEqual(self.run_polls(["stopped"]), (1, 1))


class MainTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        podman = self.tmp / "podman"
        podman.write_text(
            """#!/bin/bash
case "$1" in
inspect) cat "$FAKE_DIR/running" ;;
exec) cat "$FAKE_DIR/pids" ;;
esac
"""
        )
        podman.chmod(podman.stat().st_mode | stat.S_IEXEC)
        (self.tmp / "running").write_text("true")
        (self.tmp / "pids").write_text("")

    def watch(self, package, *extra):
        env = {
            "PATH": f"{self.tmp}:/usr/local/bin:/usr/bin:/bin",
            "FAKE_DIR": str(self.tmp),
            "WGAPPS_CONTAINER": "c",
        }
        return subprocess.run(
            [sys.executable, str(BIN / "wgapps-appwatch"), package, "--interval", "0.01", *extra],
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_package_name_is_validated_like_app_valid_package(self):
        for bad in ("nodots", "../x.y", "com.x y", "a." + "b" * 60, "com.x;rm"):
            done = self.watch(bad)
            self.assertEqual(done.returncode, 2, bad)
            self.assertIn("package", done.stderr)

    def test_returns_zero_once_the_process_is_gone(self):
        (self.tmp / "pids").write_text("")
        self.assertEqual(self.watch("com.a.b", "--grace", "2").returncode, 0)

    def test_returns_one_when_the_container_is_not_running(self):
        (self.tmp / "running").write_text("false")
        self.assertEqual(self.watch("com.a.b").returncode, 1)


if __name__ == "__main__":
    unittest.main()
