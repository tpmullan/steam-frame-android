"""wgapps talks to the user's own session whatever shell it runs in.

docs/bugs/2026-11-15-wrong-session-podman.md: from a terminal in another session (a nested
desktop with XDG_RUNTIME_DIR=/run/user/1000/nested_plasma) podman looked for the container's state
in that directory: `logcat` failed with "container ... does not exist", `status` said "stopped" for
a running Android, and `start` failed with an sd-bus error.
"""

import unittest

from helpers import BIN

SCRIPT = (BIN / "wgapps").read_text()


class SessionTests(unittest.TestCase):
    def test_the_runtime_dir_is_the_users_own_before_anything_runs(self):
        head = SCRIPT.split("BASE=", 1)[0]
        self.assertIn('XDG_RUNTIME_DIR="/run/user/$(id -u)"', head)
        self.assertIn("export XDG_RUNTIME_DIR", head)
        self.assertIn('DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"', head)

    def test_it_does_not_trust_the_environment_it_was_started_in(self):
        self.assertNotIn("${XDG_RUNTIME_DIR:-", SCRIPT)


if __name__ == "__main__":
    unittest.main()
