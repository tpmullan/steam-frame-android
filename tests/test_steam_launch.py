"""`wgapps steam <package>`: the launch Steam runs for a library entry. The first entry starts
the container and owns the panel; later entries attach to it and never restart or stop it."""

import os
import pathlib
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

from helpers import BIN

FAKE_PODMAN = """#!/bin/bash
case "$1" in
inspect) cat "$FAKE_DIR/running" ;;
wait) sleep "${FAKE_WAIT:-0}" ;;
exec)
	cmd="${*: -1}"
	echo "$cmd" >>"$FAKE_LOG"
	case "$cmd" in
	*resolve-activity*) echo "com.x.y/.Main" ;;
	esac
	;;
esac
"""

# Replace the parts that need a real container; keep cmd_steam itself.
DRIVER = """source "$1"; shift
cmd_start() { echo START >>"$FAKE_LOG"; echo true >"$FAKE_DIR/running"; }
cmd_wait_boot() { :; }
cmd_stop() { echo STOP >>"$FAKE_LOG"; echo false >"$FAKE_DIR/running"; }
cmd_steam "$@"
"""

FAKE_WATCH_EXIT = "#!/usr/bin/env python3\n"
FAKE_WATCH_SLEEP = "#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n"


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class SteamLaunchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        self.base = self.tmp / "base"
        (self.base / "bin").mkdir(parents=True)
        (self.base / "share").mkdir()
        fake = self.tmp / "fakebin"
        fake.mkdir()
        (fake / "podman").write_text(FAKE_PODMAN)
        (fake / "podman").chmod(0o755)
        self.log = self.tmp / "log"
        self.log.write_text("")
        self.running(True)
        self.env = {
            **os.environ,
            "HOME": str(self.tmp / "home"),
            "WGAPPS_BASE": str(self.base),
            "PATH": f"{fake}:/usr/local/bin:/usr/bin:/bin",
            "FAKE_DIR": str(self.tmp),
            "FAKE_LOG": str(self.log),
        }

    def running(self, value):
        (self.tmp / "running").write_text("true" if value else "false")

    def watcher(self, script):
        path = self.base / "bin/wgapps-appwatch"
        path.write_text(script)
        path.chmod(0o755)

    def start(self, *args, **extra):
        return subprocess.Popen(
            ["bash", "-c", DRIVER, "bash", str(BIN / "wgapps"), *args],
            env={**self.env, **extra},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def lines(self):
        return self.log.read_text().splitlines()

    def wait_for_log(self, needle, seconds=10):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if needle in self.log.read_text():
                return
            time.sleep(0.05)
        self.fail(f"{needle!r} never appeared in {self.log.read_text()!r}")

    def test_second_launch_does_not_stop_or_restart_a_running_container(self):
        self.watcher(FAKE_WATCH_EXIT)
        done = self.start("com.x.y")
        out, err = done.communicate(timeout=20)
        self.assertEqual(done.returncode, 0, err)
        self.assertNotIn("STOP", self.lines())
        self.assertNotIn("START", self.lines())
        self.assertTrue(
            any("am start" in line and "com.x.y/.Main" in line for line in self.lines())
        )
        self.assertFalse(any("force-stop" in line for line in self.lines()))

    def test_quit_force_stops_only_that_package(self):
        self.watcher(FAKE_WATCH_SLEEP)
        proc = self.start("com.x.y")
        self.wait_for_log("am start")
        time.sleep(0.3)  # let the script reach its wait
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(any("am force-stop 'com.x.y'" in line for line in self.lines()))
        self.assertNotIn("STOP", self.lines())

    def test_first_launch_starts_the_container_under_the_reaper_and_owns_it(self):
        self.running(False)
        self.watcher(FAKE_WATCH_EXIT)
        done = self.start("com.x.y", FAKE_WAIT="0")
        done.communicate(timeout=20)
        lines = self.lines()
        self.assertEqual(lines[0], "START")
        self.assertTrue(any("am start" in line for line in lines))
        # The owner does not follow its app: the panel must outlive it for other entries.
        self.assertFalse(any("force-stop" in line for line in lines))

    def test_quitting_the_owner_stops_the_container(self):
        self.running(False)
        proc = self.start("com.x.y", FAKE_WAIT="30")
        self.wait_for_log("am start")
        time.sleep(0.3)
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=20)
        self.assertIn("STOP", self.lines())

    def test_entry_without_a_package_attaches_to_the_home_screen(self):
        done = self.start(FAKE_WAIT="0")
        done.communicate(timeout=20)
        self.assertEqual(done.returncode, 0)
        self.assertTrue(any("android.intent.category.HOME" in line for line in self.lines()))
        self.assertNotIn("STOP", self.lines())
        self.assertNotIn("START", self.lines())

    def test_a_bad_package_name_is_refused_before_anything_runs(self):
        done = self.start("com.x;touch /tmp/pwned")
        done.communicate(timeout=20)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.lines(), [])


if __name__ == "__main__":
    unittest.main()
