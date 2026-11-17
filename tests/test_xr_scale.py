"""wgapps xr scale: how much larger than SteamVR's recommendation OpenXR apps render."""

import pathlib
import shutil
import tempfile
import unittest

from helpers import wgapps_call

STUBS = "running() { return 1; }\n"


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class XrScaleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name) / "base"
        self.base.mkdir()
        self.env = {"HOME": tmp.name, "WGAPPS_BASE": str(self.base)}

    def call(self, script):
        return wgapps_call(self.env, "eval", STUBS + script)

    def test_default_is_the_panel_size_factor(self):
        self.assertEqual(self.call("xr_scale").stdout.strip(), "1.25")
        self.assertEqual(self.call("cmd_xr scale").stdout.strip(), "1.25")

    def test_a_chosen_factor_is_kept_and_default_removes_it(self):
        done = self.call("cmd_xr scale 1.5")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.base / "xr-scale").read_text().strip(), "1.5")
        self.assertEqual(self.call("xr_scale").stdout.strip(), "1.5")
        self.call("cmd_xr scale default")
        self.assertFalse((self.base / "xr-scale").exists())
        self.assertEqual(self.call("xr_scale").stdout.strip(), "1.25")

    def test_values_outside_one_to_two_or_not_plain_decimals_are_refused(self):
        for bad in ("0.9", "2.01", "2.5", "3", "abc", "1.255", ".5", "-1", "1,5", ""):
            done = self.call(f"cmd_xr scale '{bad}'")
            self.assertNotEqual(done.returncode, 0, bad)
            self.assertFalse((self.base / "xr-scale").exists(), bad)

    def test_edges_are_accepted(self):
        for good in ("1", "1.0", "1.05", "2", "2.0", "2.00"):
            self.assertEqual(self.call(f"cmd_xr scale '{good}'").returncode, 0, good)

    def test_a_damaged_file_falls_back_to_the_default(self):
        (self.base / "xr-scale").write_text("lots\n")
        self.assertEqual(self.call("xr_scale").stdout.strip(), "1.25")

    def test_percent_helper(self):
        for value, percent in (("1", "100"), ("1.25", "125"), ("1.5", "150"), ("2", "200")):
            self.assertEqual(self.call(f"xr_scale_percent {value}").stdout.strip(), percent)

    def test_the_property_reaches_android_with_the_other_props(self):
        script = (
            'HOST_UID=1000; ADB_PORT=5555; RUNDIR="$BASE/run"; windows_mode() { echo single; };'
            " app_wrap_props() { :; }; gpu_egl() { echo mesa; };"
            ' write_props false; grep "^debug.xr" "$RUNDIR/waydroid.prop"'
        )
        self.assertEqual(self.call(script).stdout.strip(), "debug.xr.render_scale=1.25")
        self.call("cmd_xr scale 1.4")
        self.assertEqual(self.call(script).stdout.strip(), "debug.xr.render_scale=1.4")

    def test_the_usage_line_and_dispatch_exist(self):
        text = (pathlib.Path(__file__).resolve().parent.parent / "bin/wgapps").read_text()
        self.assertIn("xr scale [1.0-2.0|default]", text)
        self.assertIn('xr) cmd_xr "$@" ;;', text)


if __name__ == "__main__":
    unittest.main()
