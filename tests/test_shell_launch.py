"""VR mode on the host: the app list for the shell and starting the shell."""

import pathlib
import shutil
import tempfile
import unittest

from helpers import wgapps_call

STUBS = """
hide_dashboard() { echo hide >>"$WGAPPS_BASE/asys.log"; }
running() { return 0; }
asys() { echo "$*" >>"$WGAPPS_BASE/asys.log"; case "$*" in pidof*) echo "${FAKE_PID:-}";; esac; }
sleep() { :; }
"""


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class ShellLaunchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name) / "base"
        (self.base / "lib").mkdir(parents=True)
        (self.base / "run").mkdir()
        self.env = {"HOME": tmp.name, "WGAPPS_BASE": str(self.base), "WGAPPS_SHELL_TRIES": "3"}

    def vr_mode(self):
        (self.base / "lib/WgappsShell.apk").write_text("apk")
        (self.base / "mode").write_text("vr\n")

    def call(self, script, **env):
        return wgapps_call({**self.env, **env}, "eval", STUBS + script)

    def asys_log(self):
        path = self.base / "asys.log"
        return path.read_text() if path.exists() else ""

    def test_steam_mode_starts_no_shell_and_pushes_nothing(self):
        done = self.call("shell_launch")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.asys_log(), "")
        self.assertFalse((self.base / "share/apps.tsv").exists())

    def test_vr_mode_pushes_the_list_then_starts_the_shell_and_counts_success(self):
        self.vr_mode()
        script = (
            'cmd_apps() { [[ $1 == push ]] || return 0; mkdir -p "$SHARE";'
            ' echo ok >"$SHARE/apps.tsv"; };'
            'mode_record_start() { echo "record $1" >>"$WGAPPS_BASE/asys.log"; };'
            "shell_launch"
        )
        done = self.call(script, FAKE_PID="123")
        self.assertEqual(done.returncode, 0, done.stderr)
        log = self.asys_log()
        self.assertIn("am start -n dev.wgapps.shell/.ShellActivity", log)
        self.assertIn("record ok", log)
        self.assertTrue((self.base / "share/apps.tsv").exists())

    def test_the_shell_is_given_the_environment_in_the_shared_folder(self):
        self.vr_mode()
        script = (
            "cmd_apps() { :; }; mode_record_start() { :; };"
            ' printf "%s\\n" "home=off" "env=solid #102030" >"$BASE/mode.conf"; shell_launch'
        )
        self.call(script, FAKE_PID="1")
        self.assertEqual((self.base / "share/environment").read_text().strip(), "solid #102030")
        self.assertEqual(oct((self.base / "share/environment").stat().st_mode)[-3:], "644")

    def test_focus_is_asked_for_repeatedly_after_the_shell_is_up_not_once(self):
        self.vr_mode()
        script = "cmd_apps() { :; }; mode_record_start() { :; }; shell_launch"
        self.call(script, FAKE_PID="1")
        self.assertGreaterEqual(self.asys_log().count("hide"), 4)

    def test_the_openxr_scene_is_launched_only_when_the_build_had_the_native_part(self):
        self.vr_mode()
        script = "cmd_apps() { :; }; mode_record_start() { :; }; shell_launch"
        self.call(script, FAKE_PID="1")
        self.assertIn("dev.wgapps.shell/.ShellActivity", self.asys_log())
        self.assertNotIn(".VrShellActivity", self.asys_log())
        (self.base / "asys.log").unlink()
        (self.base / "lib/WgappsShell.vr").write_text("")
        self.call(script, FAKE_PID="1")
        self.assertIn("dev.wgapps.shell/.VrShellActivity", self.asys_log())

    def starforge_shell(self):
        (self.base / "lib/StarforgeShell.apk").write_text("apk")
        (self.base / "mode").write_text("vr\n")

    def test_the_starforge_shell_is_preferred_and_launched_by_its_own_package_and_activity(self):
        self.starforge_shell()
        (self.base / "lib/WgappsShell.apk").write_text("apk")
        script = "cmd_apps() { :; }; mode_record_start() { :; }; shell_launch"
        done = self.call(script, FAKE_PID="1")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("am start -n rs.starforge.xrhost/rs.starforge.Activity", self.asys_log())
        self.assertIn("pidof rs.starforge.xrhost", self.asys_log())
        self.assertNotIn("dev.wgapps.shell", self.asys_log())

    def test_vr_mode_is_available_with_only_the_starforge_shell_installed(self):
        self.starforge_shell()
        done = self.call("mode_effective")
        self.assertEqual(done.stdout.strip(), "vr")

    def test_the_starforge_shell_is_the_one_mounted_as_a_system_app(self):
        self.starforge_shell()
        done = self.call('ARGS=(); mount_shell_app; printf "%s\\n" "${ARGS[@]}"')
        self.assertIn("destination=/system/priv-app/StarforgeShell/StarforgeShell.apk", done.stdout)

    def test_the_shell_is_hidden_from_the_app_lists(self):
        text = (pathlib.Path(__file__).resolve().parent.parent / "bin/wgapps").read_text()
        line = next(ln for ln in text.splitlines() if ln.startswith("APPS_HIDDEN_DEFAULT="))
        self.assertIn("rs.starforge.xrhost", line)

    def test_a_shell_that_never_runs_counts_a_failure_and_returns_nonzero(self):
        self.vr_mode()
        script = (
            "cmd_apps() { :; };"
            ' mode_record_start() { echo "record $1" >>"$WGAPPS_BASE/asys.log"; };'
            "shell_launch"
        )
        done = self.call(script, FAKE_PID="")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("record fail", self.asys_log())
        self.assertIn("did not start", done.stderr)

    def test_three_failures_in_a_row_fall_back_to_steam_mode(self):
        self.vr_mode()
        for _ in range(3):
            self.call("cmd_apps() { :; }; shell_launch", FAKE_PID="")
        self.assertEqual((self.base / "mode").read_text().strip(), "steam")

    def test_apps_push_writes_the_catalog_into_the_shared_folder_atomically(self):
        script = (
            "cmd_apps_list() { :; }; "
            "catalog_refresh_labels() { :; }; "
            "catalog_build() { printf 'a.b\\tAB\\ta.b/.M\\t2d\\n'; }; "
            "cmd_apps push"
        )
        done = self.call(script)
        self.assertEqual(done.returncode, 0, done.stderr)
        target = self.base / "share/apps.tsv"
        self.assertEqual(target.read_text(), "a.b\tAB\ta.b/.M\t2d\n")
        self.assertEqual(oct(target.stat().st_mode)[-3:], "644")
        self.assertEqual([p.name for p in (self.base / "share").iterdir()], ["apps.tsv"])

    def test_the_panel_input_helper_runs_only_in_vr_mode_and_is_stopped_with_the_others(self):
        text = (pathlib.Path(__file__).resolve().parent.parent / "bin/wgapps").read_text()
        start = text[text.index("start_helpers() {") : text.index("start_helper() {")]
        self.assertIn('mode_effective)" == "vr" ]]; then', start)
        self.assertIn("start_helper wgapps-panelinput", start)
        self.assertIn("start_helper wgapps-bridge", start)
        stop = text[text.index("stop_helpers() {") : text.index("cmd_stop() {")]
        self.assertIn("wgapps-panelinput", stop)
        self.assertIn("wgapps-bridge", stop)

    def test_view_panel_stops_the_shell_and_shows_home_and_view_vr_starts_it(self):
        (self.base / "lib/StarforgeShell.apk").write_text("apk")
        done = self.call("cmd_view panel")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("am force-stop rs.starforge.xrhost; input keyevent 3", self.asys_log())
        (self.base / "asys.log").unlink()
        done = self.call("cmd_view vr")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("am start -n rs.starforge.xrhost/rs.starforge.Activity", self.asys_log())
        self.assertIn("hide", self.asys_log())

    def test_view_vr_stops_the_vr_apps_still_running_before_starting_the_shell(self):
        (self.base / "lib/StarforgeShell.apk").write_text("apk")
        (self.base / "share").mkdir()
        (self.base / "share/apps.tsv").write_text(
            "org.w/org.w/.M\tWolvic\torg.w/.M\txr\ncom.s\tSettings\tcom.s/.S\t2d\n"
        )
        (self.base / "share/apps.tsv").write_text(
            "org.w\tWolvic\torg.w/.M\txr\ncom.s\tSettings\tcom.s/.S\t2d\n"
        )
        done = self.call("cmd_view vr")
        self.assertEqual(done.returncode, 0, done.stderr)
        log = self.asys_log()
        self.assertIn("am force-stop org.w", log)
        self.assertNotIn("am force-stop com.s", log)
        self.assertLess(log.index("force-stop org.w"), log.index("am start -n rs.starforge"))

    def test_view_vr_needs_the_starforge_shell_and_view_needs_panel_or_vr(self):
        self.assertNotEqual(self.call("cmd_view vr").returncode, 0)  # not installed
        self.assertNotEqual(self.call("cmd_view sideways").returncode, 0)
        self.assertNotEqual(self.call("cmd_view").returncode, 0)

    def test_the_steam_entry_wires_the_shell_in_only_for_vr_mode(self):
        text = (pathlib.Path(__file__).resolve().parent.parent / "bin/wgapps").read_text()
        self.assertIn('[[ "$(mode_effective)" == "vr" ]]; then\n\t\t\tshell_launch', text)


if __name__ == "__main__":
    unittest.main()
