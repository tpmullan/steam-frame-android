"""Mode switch: `wgapps mode steam|vr`, the 3D home setting, the shell mount and the fallback."""

import pathlib
import shutil
import tempfile
import unittest

from helpers import wgapps_call


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class ModeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name) / "base"
        (self.base / "lib").mkdir(parents=True)
        self.env = {"HOME": tmp.name, "WGAPPS_BASE": str(self.base)}

    def call(self, function, *args):
        return wgapps_call(self.env, function, *args)

    def install_shell(self):
        (self.base / "lib/WgappsShell.apk").write_text("apk")

    def test_default_is_steam_with_the_home_off(self):
        done = self.call("cmd_mode")
        self.assertEqual(done.stdout.strip(), "steam (home off)")

    def test_vr_is_refused_without_the_shell_and_nothing_is_written(self):
        done = self.call("cmd_mode", "vr")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("WgappsShell.apk", done.stderr)
        self.assertFalse((self.base / "mode").exists())

    def test_vr_with_the_shell_is_saved_and_effective_until_the_shell_goes(self):
        self.install_shell()
        self.assertEqual(self.call("cmd_mode", "vr").returncode, 0)
        self.assertEqual((self.base / "mode").read_text().strip(), "vr")
        self.assertEqual(self.call("mode_effective").stdout.strip(), "vr")
        (self.base / "lib/WgappsShell.apk").unlink()
        self.assertEqual(self.call("mode_effective").stdout.strip(), "steam")
        self.assertEqual(self.call("mode_saved").stdout.strip(), "vr")

    def test_unknown_arguments_are_rejected(self):
        for args in (("nope",), ("home", "maybe")):
            self.assertNotEqual(self.call("cmd_mode", *args).returncode, 0, args)

    def mirror(self):
        return (self.base / "share/app-mode.conf").read_text()

    def test_the_saved_mode_is_mirrored_for_the_settings_screen(self):
        self.install_shell()
        self.call("export_mode")
        self.assertEqual(self.mirror(), "steam\n")
        self.call("cmd_mode", "vr")
        self.assertEqual(self.mirror(), "vr\n")
        self.call("cmd_mode", "steam")
        self.assertEqual(self.mirror(), "steam\n")

    def test_import_takes_the_mode_the_screen_wrote(self):
        self.install_shell()
        written = self.base / "app-mode.conf"
        written.write_text("vr\n")
        self.assertEqual(self.call("cmd_mode", "import", str(written)).returncode, 0)
        self.assertEqual((self.base / "mode").read_text().strip(), "vr")
        written.write_text("steam\n")
        self.assertEqual(self.call("cmd_mode", "import", str(written)).returncode, 0)
        self.assertEqual(self.mirror(), "steam\n")

    def test_import_of_vr_without_the_shell_is_refused_and_the_mirror_snaps_back(self):
        written = self.base / "app-mode.conf"
        written.write_text("vr\n")
        done = self.call("cmd_mode", "import", str(written))
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse((self.base / "mode").exists())
        self.assertEqual(self.mirror(), "steam\n")

    def test_import_refuses_anything_that_is_not_a_mode(self):
        written = self.base / "app-mode.conf"
        for text in ("both\n", "VR\n", "", "x" * 100):
            written.write_text(text)
            self.assertNotEqual(self.call("cmd_mode", "import", str(written)).returncode, 0, text)
        self.assertFalse((self.base / "mode").exists())
        self.assertNotEqual(
            self.call("cmd_mode", "import", str(self.base / "missing")).returncode, 0
        )

    def test_environment_defaults_to_the_room_and_round_trips(self):
        self.assertEqual(self.call("cmd_mode", "env").stdout.strip(), "room")
        self.assertEqual(self.call("cmd_mode", "env", "solid", "#1a2b3c").returncode, 0)
        self.assertEqual(self.call("cmd_mode", "env").stdout.strip(), "solid #1a2b3c")
        self.assertEqual(self.call("cmd_mode", "env", "solid").returncode, 0)
        self.assertEqual(self.call("cmd_mode", "env").stdout.strip(), "solid")
        self.assertEqual(self.call("cmd_mode", "env", "home").returncode, 0)
        self.assertEqual(self.call("cmd_mode", "env").stdout.strip(), "home")
        self.assertEqual(self.call("cmd_mode", "env", "room").returncode, 0)
        self.assertEqual(self.call("cmd_mode", "env").stdout.strip(), "room")

    def test_a_bad_environment_is_refused_and_changes_nothing(self):
        self.call("cmd_mode", "env", "solid", "#102030")
        for args in (
            ("garden",),
            ("home", "x"),
            ("solid", "red"),
            ("solid", "#12"),
            ("solid", "#102030", "x"),
        ):
            done = self.call("cmd_mode", "env", *args)
            self.assertNotEqual(done.returncode, 0, args)
        self.assertEqual(self.call("cmd_mode", "env").stdout.strip(), "solid #102030")

    def test_home_and_environment_settings_do_not_overwrite_each_other(self):
        self.call("cmd_mode", "env", "solid", "#102030")
        self.call("cmd_mode", "home", "on")
        self.assertEqual(self.call("cmd_mode", "env").stdout.strip(), "solid #102030")
        self.assertEqual(self.call("cmd_mode", "home").stdout.strip(), "on")
        self.call("cmd_mode", "env", "room")
        self.assertEqual(self.call("cmd_mode", "home").stdout.strip(), "on")

    def test_home_setting_round_trips_and_is_separate_from_the_mode(self):
        self.assertEqual(self.call("cmd_mode", "home", "on").returncode, 0)
        self.assertEqual(self.call("cmd_mode", "home").stdout.strip(), "on")
        self.assertEqual(self.call("cmd_mode").stdout.strip(), "steam (home on)")
        self.assertEqual(self.call("cmd_mode", "home", "off").returncode, 0)
        self.assertEqual(self.call("cmd_mode", "home").stdout.strip(), "off")

    def test_the_shell_is_mounted_only_in_vr_mode(self):
        self.install_shell()
        script = "mount_shell_app; printf '%s\\n' \"${ARGS[@]}\""
        self.assertNotIn("WgappsShell", self.call("eval", script).stdout)
        self.call("cmd_mode", "vr")
        out = self.call("eval", script).stdout
        self.assertIn("destination=/system/priv-app/WgappsShell/WgappsShell.apk", out)

    def test_three_failed_starts_fall_back_to_steam_and_a_good_start_resets(self):
        self.install_shell()
        self.call("cmd_mode", "vr")
        (self.base / "run").mkdir()
        self.call("mode_record_start", "fail")
        self.call("mode_record_start", "fail")
        self.call("mode_record_start", "ok")
        self.call("mode_record_start", "fail")
        self.call("mode_record_start", "fail")
        self.assertEqual(self.call("mode_saved").stdout.strip(), "vr")
        done = self.call("mode_record_start", "fail")
        self.assertIn("back to steam mode", done.stderr)
        self.assertEqual(self.call("mode_saved").stdout.strip(), "steam")


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class ContainerNameTests(unittest.TestCase):
    def test_the_container_name_can_be_set_so_a_second_android_can_run_beside_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = {"HOME": tmp, "WGAPPS_BASE": tmp}
            default = wgapps_call(base, "eval", 'echo "$NAME"')
            other = wgapps_call({**base, "WGAPPS_NAME": "wg-test"}, "eval", 'echo "$NAME"')
        self.assertEqual(default.stdout.strip(), "waydroid-gapps")
        self.assertEqual(other.stdout.strip(), "wg-test")


if __name__ == "__main__":
    unittest.main()
