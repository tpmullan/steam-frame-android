"""Window mode (`wgapps windows`) and the per-app launch kind (`wgapps apps kind`)."""

import pathlib
import shutil
import tempfile
import unittest

from helpers import wgapps_call

PROP = "persist.waydroid.multi_windows=true"


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class WindowsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name) / "base"
        self.base.mkdir()
        self.env = {"HOME": str(self.base / "home"), "WGAPPS_BASE": str(self.base)}

    def call(self, function, *args):
        return wgapps_call(self.env, function, *args)

    def props(self):
        done = self.call("write_props", "false")
        self.assertEqual(done.returncode, 0, done.stderr)
        return (self.base / "run/waydroid.prop").read_text().splitlines()

    def test_windows_floating_writes_multi_windows_prop_and_single_removes_it(self):
        self.assertNotIn(PROP, self.props())
        self.assertEqual(self.call("cmd_windows", "floating").returncode, 0)
        self.assertEqual((self.base / "windows").read_text().strip(), "floating")
        self.assertIn(PROP, self.props())
        self.assertEqual(self.call("cmd_windows", "single").returncode, 0)
        self.assertNotIn(PROP, self.props())
        self.assertEqual(self.call("cmd_windows").stdout.strip(), "single")

    def test_windows_rejects_other_values_and_changes_nothing(self):
        self.call("cmd_windows", "floating")
        for bad in ("tiled", "", "floating extra", "FLOATING", "true"):
            done = (
                self.call("cmd_windows", *bad.split(" ", 1))
                if bad
                else self.call("cmd_windows", "")
            )
            self.assertEqual(done.returncode, 1, bad)
            self.assertIn("floating|single", done.stderr)
        self.assertEqual((self.base / "windows").read_text().strip(), "floating")

    def test_hand_edited_garbage_in_the_windows_file_means_single(self):
        (self.base / "windows").write_text("floating; reboot\n")
        self.assertNotIn(PROP, self.props())

    def test_windows_setting_survives_update(self):
        # `update` moves only bin, lib, overrides, VERSION and image out of the way.
        script = (pathlib.Path(__file__).resolve().parent.parent / "bin/wgapps").read_text()
        moved = [
            line for line in script.splitlines() if "for item in bin lib overrides VERSION" in line
        ]
        self.assertTrue(moved)
        self.assertTrue(all("windows" not in line for line in moved))

    # --- GLES implementation ------------------------------------------------------------

    def test_gpu_egl_defaults_to_mesa_and_angle_changes_the_boot_property(self):
        self.assertIn("ro.hardware.egl=mesa", self.props())
        self.assertEqual(self.call("cmd_gpu", "egl", "angle").returncode, 0)
        self.assertIn("ro.hardware.egl=angle", self.props())
        self.assertNotIn("ro.hardware.egl=mesa", self.props())
        self.assertEqual(self.call("cmd_gpu", "egl").stdout.strip(), "angle")
        self.assertEqual(self.call("cmd_gpu", "egl", "mesa").returncode, 0)
        self.assertFalse((self.base / "gpu-egl").exists())
        self.assertIn("ro.hardware.egl=mesa", self.props())

    def test_gpu_egl_rejects_other_values_and_garbage_means_mesa(self):
        for args in (("egl", "swiftshader"), ("egl", "angle", "x"), ("vulkan", "angle"), ()):
            self.assertEqual(self.call("cmd_gpu", *args).returncode, 1, args)
        self.assertFalse((self.base / "gpu-egl").exists())
        (self.base / "gpu-egl").write_text("angle; reboot\n")
        self.assertIn("ro.hardware.egl=mesa", self.props())

    # --- per-app kind -------------------------------------------------------------------

    def test_kind_key_is_validated_and_stored_apart_from_the_device_profiles(self):
        ok = self.call("cmd_apps", "kind", "com.a.b", "xr")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual((self.base / "apps-kind").read_text().splitlines(), ["com.a.b xr"])
        self.assertFalse((self.base / "apps.conf").exists())  # the Settings screen's file
        for package, kind in (
            ("nodots", "xr"),
            ("com.a.b", "vr"),
            ("com.a.b;x", "2d"),
            ("com.a.b", ""),
        ):
            bad = self.call("cmd_apps", "kind", package, kind)
            self.assertEqual(bad.returncode, 1, (package, kind))
        self.assertEqual((self.base / "apps-kind").read_text().splitlines(), ["com.a.b xr"])

    def test_kind_replaces_and_auto_removes_the_entry(self):
        self.call("cmd_apps", "kind", "com.a.b", "xr")
        self.call("cmd_apps", "kind", "com.c.d", "2d")
        self.call("cmd_apps", "kind", "com.a.b", "2d")
        self.assertEqual(
            sorted((self.base / "apps-kind").read_text().splitlines()), ["com.a.b 2d", "com.c.d 2d"]
        )
        self.call("cmd_apps", "kind", "com.a.b", "auto")
        self.assertEqual((self.base / "apps-kind").read_text().splitlines(), ["com.c.d 2d"])

    def test_kind_overrides_the_detected_kind_in_the_app_list(self):
        (self.base / "apps-kind").write_text("com.x.app xr\ncom.chrome 2d\nbad line here\n")
        launcher = self.base / "launcher.txt"
        xr = self.base / "xr.txt"
        launcher.write_text("    com.x.app/.Main\n    com.chrome/.Main\n    com.y.native/.Main\n")
        xr.write_text("    com.y.native/.Main\n")
        done = self.call("catalog_build", str(launcher), str(xr))
        kinds = {line.split("\t")[0]: line.split("\t")[3] for line in done.stdout.splitlines()}
        self.assertEqual(kinds, {"com.x.app": "xr", "com.chrome": "2d", "com.y.native": "xr"})
        # A user's 2d beats detection too.
        (self.base / "apps-kind").write_text("com.y.native 2d\n")
        done = self.call("catalog_build", str(launcher), str(xr))
        kinds = {line.split("\t")[0]: line.split("\t")[3] for line in done.stdout.splitlines()}
        self.assertEqual(kinds["com.y.native"], "2d")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class ReportTests(unittest.TestCase):
    def test_report_writes_a_file_with_sections_and_drops_account_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp) / "base"
            (base / "run").mkdir(parents=True)
            (base / "run/waydroid.prop").write_text(
                "ro.hardware.egl=mesa\nandroid_id=abc123\n"
            )
            (base / "run/kmsg.log").write_text("init: boot loop\n")
            env = {"HOME": tmp, "WGAPPS_BASE": str(base)}
            out = pathlib.Path(tmp) / "r.txt"
            done = wgapps_call(env, "cmd_report", str(out))
            self.assertEqual(done.returncode, 0, done.stderr)
            text = out.read_text()
            for heading in ("===== wgapps =====", "===== steam =====", "init: boot loop"):
                self.assertIn(heading, text)
            self.assertIn("ro.hardware.egl=mesa", text)
            self.assertNotIn("abc123", text)
