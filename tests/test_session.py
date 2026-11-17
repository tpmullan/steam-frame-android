"""wgapps talks to the user's own session whatever shell it runs in.

docs/bugs/2026-11-15-wrong-session-podman.md: from a terminal in another session (a nested
desktop with XDG_RUNTIME_DIR=/run/user/1000/nested_plasma) podman looked for the container's state
in that directory: `logcat` failed with "container ... does not exist", `status` said "stopped" for
a running Android, and `start` failed with an sd-bus error.
"""

import os
import shutil
import subprocess
import unittest

from helpers import BIN


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class SessionTests(unittest.TestCase):
    def runtime_dir(self, **env):
        base = {"PATH": os.environ["PATH"], "HOME": "/nonexistent", **env}
        script = 'source "$1"; printf "%s|%s" "$XDG_RUNTIME_DIR" "${DBUS_SESSION_BUS_ADDRESS:-}"'
        done = subprocess.run(
            ["bash", "-c", script, "bash", str(BIN / "wgapps")],
            env=base,
            capture_output=True,
            text=True,
            check=False,
        )
        return done.stdout.split("|")

    def test_another_sessions_runtime_dir_is_replaced_by_the_users_own(self):
        uid = str(os.getuid())
        for foreign in (f"/run/user/{uid}/nested_plasma", "/tmp/other-session", ""):
            runtime, _bus = self.runtime_dir(XDG_RUNTIME_DIR=foreign)
            self.assertEqual(runtime, f"/run/user/{uid}", foreign)

    def test_an_unset_runtime_dir_is_set(self):
        self.assertEqual(self.runtime_dir()[0], f"/run/user/{os.getuid()}")

    def test_the_session_bus_follows_when_it_exists(self):
        runtime, bus = self.runtime_dir()
        expected = f"unix:path={runtime}/bus" if os.path.exists(f"{runtime}/bus") else ""
        self.assertEqual(bus, expected)


if __name__ == "__main__":
    unittest.main()
