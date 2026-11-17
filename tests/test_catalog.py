"""The app catalog in bin/wgapps: `wgapps apps list` and catalog_build, which turn Android's
`cmd package query-activities --brief` output into `package<TAB>label<TAB>activity<TAB>kind`."""

import pathlib
import shutil
import tempfile
import unittest

from helpers import BIN, load, wgapps_call

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
LAUNCHER = FIXTURES / "apps-query-launcher.txt"
XR = FIXTURES / "apps-query-xr.txt"


def query(*components):
    """Android's --brief output for the given package/activity components."""
    lines = [f"{len(components)} activities found:"]
    for number, component in enumerate(components):
        lines += [
            f"  Activity #{number}:",
            "    priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true",
            f"    {component}",
        ]
    return "\n".join(lines) + "\n"


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class CatalogTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        self.base = self.tmp / "base"
        (self.base / "share").mkdir(parents=True)
        self.env = {"HOME": str(self.tmp / "home"), "WGAPPS_BASE": str(self.base)}

    def build(self, launcher_text, xr_text=""):
        launcher = self.tmp / "launcher.txt"
        xr = self.tmp / "xr.txt"
        launcher.write_text(launcher_text)
        xr.write_text(xr_text)
        done = wgapps_call(self.env, "catalog_build", str(launcher), str(xr))
        self.assertEqual(done.returncode, 0, done.stderr)
        return [line.split("\t") for line in done.stdout.splitlines()]

    def test_parse_lists_launcher_apps_sorted(self):
        rows = self.build(query("org.x.zulu/.Main", "com.x.alpha/.Main", "com.x.mike/.Main"))
        self.assertEqual([row[0] for row in rows], ["com.x.alpha", "com.x.mike", "org.x.zulu"])
        self.assertEqual(rows[0], ["com.x.alpha", "Alpha", "com.x.alpha/.Main", "2d"])

    def test_sort_is_by_label_then_package_ignoring_case(self):
        (self.base / "share/app-labels.conf").write_text(
            "com.a.one\tzebra\ncom.b.two\tApple\ncom.c.three\tApple\n"
        )
        rows = self.build(query("com.a.one/.M", "com.c.three/.M", "com.b.two/.M"))
        self.assertEqual([row[0] for row in rows], ["com.b.two", "com.c.three", "com.a.one"])

    def test_missing_label_falls_back_to_package_tail(self):
        rows = self.build(query("com.example.deskclock/.DeskClock"))
        self.assertEqual(rows[0][1], "Deskclock")

    def test_labels_file_supplies_labels_and_survives_odd_lines(self):
        (self.base / "share/app-labels.conf").write_text(
            "com.example.one\tOne App\nnot a label line\n\tno package\ncom.example.two\t\n"
        )
        rows = self.build(query("com.example.one/.M", "com.example.two/.M"))
        self.assertEqual(
            {row[0]: row[1] for row in rows},
            {"com.example.one": "One App", "com.example.two": "Two"},
        )

    def test_xr_kind_needs_the_launcher_component_itself(self):
        rows = self.build(
            query("com.chrome/.Main", "com.xr.app/.Native"),
            query("com.chrome/.XrHostActivity", "com.xr.app/.Native"),
        )
        self.assertEqual({row[0]: row[3] for row in rows}, {"com.chrome": "2d", "com.xr.app": "xr"})

    def test_hidden_file_and_default_hidden_apps_are_dropped(self):
        (self.base / "apps-hidden").write_text("# comment\ncom.hide.me\n\n")
        rows = self.build(
            query(
                "com.hide.me/.M",
                "com.keep.me/.M",
                "com.android.documentsui/.LauncherActivity",
                "dev.wgapps.settings/.AppListActivity",
                "dev.wgapps.shell/.ShellActivity",  # the VR shell must not list itself
                "com.android.settings/.Settings",
            )
        )
        # Labels are "Me" and "Settings".
        self.assertEqual([row[0] for row in rows], ["com.keep.me", "com.android.settings"])

    def test_duplicate_labels_keep_both_packages(self):
        (self.base / "share/app-labels.conf").write_text("com.a.x\tBrowser\ncom.b.y\tBrowser\n")
        rows = self.build(query("com.a.x/.M", "com.b.y/.M"))
        self.assertEqual([row[0] for row in rows], ["com.a.x", "com.b.y"])

    def test_an_app_with_two_launcher_activities_is_listed_once(self):
        rows = self.build(query("com.two.act/.First", "com.two.act/.Second"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "com.two.act/.First")

    def test_garbled_and_carriage_return_lines_are_skipped_not_fatal(self):
        text = (
            "3 activities found:\r\n  Activity #0:\r\n    priority=0\r\n    com.ok.app/.Main\r\n"
            + (
                "    not a component\r\n    /.NoPackage\r\n"
                "    com.bad pkg/.Main\r\n    ../x/.Main\r\n"
            )
        )
        rows = self.build(text)
        self.assertEqual([row[0] for row in rows], ["com.ok.app"])
        self.assertEqual(rows[0][2], "com.ok.app/.Main")

    def test_a_label_with_tab_or_control_characters_cannot_split_a_row(self):
        (self.base / "share/app-labels.conf").write_text("com.x.y\tBad\tLabel\x01\n")
        rows = self.build(query("com.x.y/.M"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 4)

    def test_empty_input_prints_nothing(self):
        self.assertEqual(self.build(""), [])

    def test_real_frame_output(self):
        done = wgapps_call(self.env, "catalog_build", str(LAUNCHER), str(XR))
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = {line.split("\t")[0]: line.split("\t") for line in done.stdout.splitlines()}
        self.assertEqual(rows["com.igalia.wolvic.vanilla"][3], "xr")
        self.assertEqual(rows["org.khronos.openxr.hello_xr.vulkan"][3], "xr")
        self.assertEqual(rows["com.android.chrome"][3], "2d")
        self.assertNotIn("com.android.documentsui", rows)
        self.assertIn("com.plexapp.android", rows)

    # --- `apps list` against a fake podman -----------------------------------------------

    FAKE_PODMAN = """#!/bin/bash
case "$1" in
inspect) echo true ;;
exec)
	cmd="${*: -1}"
	case "$cmd" in
	*"am broadcast"*)
		echo "$cmd" >>"$FAKE_LOG"
		if [[ -n "${FAKE_APP_LABELS:-}" ]]; then
			printf '%b' "$FAKE_APP_LABELS" >"$WGAPPS_BASE/share/app-labels.conf"
		fi
		;;
	*IMMERSIVE_HMD*) cat "$FIXTURES/apps-query-xr.txt" ;;
	*LAUNCHER*) cat "$FIXTURES/apps-query-launcher.txt" ;;
	esac
	;;
esac
"""

    def list_apps(self, with_apk=True, **extra):
        bindir = self.tmp / "fakebin"
        bindir.mkdir(exist_ok=True)
        podman = bindir / "podman"
        podman.write_text(self.FAKE_PODMAN)
        podman.chmod(0o755)
        if with_apk:
            (self.base / "lib").mkdir(exist_ok=True)
            (self.base / "lib/WgappsSettings.apk").write_text("")
        log = self.tmp / "broadcasts.log"
        env = {
            **self.env,
            "PATH": f"{bindir}:/usr/bin:/bin",
            "FIXTURES": str(FIXTURES),
            "FAKE_LOG": str(log),
            "WGAPPS_LABEL_TRIES": "3",
            **extra,
        }
        done = wgapps_call(env, "cmd_apps", "list")
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = {line.split("\t")[0]: line.split("\t") for line in done.stdout.splitlines()}
        return rows, (log.read_text() if log.exists() else "")

    def test_list_asks_the_settings_app_for_labels_and_uses_them(self):
        rows, broadcasts = self.list_apps(
            FAKE_APP_LABELS="com.plexapp.android\tPlex\ncom.igalia.wolvic.vanilla\tWolvic\n"
        )
        self.assertIn("dev.wgapps.settings/.LabelsReceiver", broadcasts)
        self.assertEqual(rows["com.plexapp.android"][1], "Plex")
        self.assertEqual(rows["com.igalia.wolvic.vanilla"][1], "Wolvic")
        self.assertEqual(rows["com.igalia.wolvic.vanilla"][3], "xr")

    def test_list_without_the_settings_apk_sends_no_broadcast_and_falls_back(self):
        rows, broadcasts = self.list_apps(
            with_apk=False, FAKE_APP_LABELS="com.plexapp.android\tPlex\n"
        )
        self.assertEqual(broadcasts, "")
        self.assertEqual(rows["com.plexapp.android"][1], "Android")

    def test_an_app_that_does_not_answer_keeps_the_previous_labels(self):
        (self.base / "share/app-labels.conf").write_text("com.plexapp.android\tPlex\n")
        rows, broadcasts = self.list_apps()  # the fake writes nothing
        self.assertIn("LabelsReceiver", broadcasts)
        self.assertEqual(rows["com.plexapp.android"][1], "Plex")
        self.assertTrue((self.base / "share/app-labels.conf").is_file())
        self.assertFalse((self.base / "share/app-labels.conf.prev").exists())

    def test_fresh_labels_replace_old_ones_and_leave_no_leftover(self):
        (self.base / "share/app-labels.conf").write_text("com.plexapp.android\tOld Plex\n")
        rows, _ = self.list_apps(FAKE_APP_LABELS="com.plexapp.android\tNew Plex\n")
        self.assertEqual(rows["com.plexapp.android"][1], "New Plex")
        self.assertFalse((self.base / "share/app-labels.conf.prev").exists())

    def test_list_with_container_stopped_prints_nothing_and_exits_1(self):
        # `running` is false without podman state: bin/wgapps must refuse, not hang.
        done = wgapps_call({**self.env, "PATH": "/usr/bin:/bin"}, "cmd_apps", "list")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertIn("not running", done.stderr)

    def test_apps_sync_writes_one_shortcut_per_app_and_keeps_the_rest(self):
        steam = self.tmp / "home/.local/share/Steam/userdata/1234/config"
        steam.mkdir(parents=True)
        # Seed Android and a hand-made shortcut with the real script's own writer.
        helper = load("steam-shortcuts.py")
        helper.STEAM = self.tmp / "home/.local/share/Steam"
        helper.save(
            steam / "shortcuts.vdf",
            {
                "0": helper.entry("Android", ""),
                "1": helper.entry("Mine", "", exe="/usr/bin/mine", launch="x", tag="Desktop"),
            },
        )
        (self.base / "bin").mkdir()
        shutil.copy(BIN / "steam-shortcuts.py", self.base / "bin/steam-shortcuts.py")
        (self.base / "lib").mkdir()
        (self.base / "lib/WgappsSettings.apk").write_text("")
        self.list_apps_sync()
        names = {s["AppName"] for s in helper.load(steam / "shortcuts.vdf").values()}
        self.assertTrue({"Android", "Mine", "Plex", "Chrome"} <= names, names)

    def list_apps_sync(self):
        bindir = self.tmp / "fakebin"
        bindir.mkdir(exist_ok=True)
        podman = bindir / "podman"
        podman.write_text(self.FAKE_PODMAN)
        podman.chmod(0o755)
        env = {
            **self.env,
            "PATH": f"{bindir}:/usr/bin:/bin",
            "FIXTURES": str(FIXTURES),
            "FAKE_LOG": str(self.tmp / "log"),
            "WGAPPS_LABEL_TRIES": "1",
            "FAKE_APP_LABELS": "com.plexapp.android\tPlex\ncom.android.chrome\tChrome\n",
        }
        done = wgapps_call(env, "cmd_apps", "sync")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class KindFileTests(unittest.TestCase):
    """The launch-type rows of Android's Settings screen: apps-kind is mirrored to the shared
    folder and a file written there is taken over (validated) by apps_kind_import."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        self.base = self.tmp / "base"
        (self.base / "share").mkdir(parents=True)
        self.env = {"HOME": str(self.tmp / "home"), "WGAPPS_BASE": str(self.base)}
        self.kinds = self.base / "apps-kind"
        self.mirror = self.base / "share" / "app-kinds.conf"

    def test_setting_a_kind_mirrors_the_file_for_android(self):
        done = wgapps_call(self.env, "apps_kind_set", "com.a.app", "2d")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.mirror.read_text(), "com.a.app 2d\n")
        wgapps_call(self.env, "apps_kind_set", "com.a.app", "auto")
        self.assertEqual(self.mirror.read_text(), "")

    def test_an_import_keeps_valid_lines_and_the_last_line_of_a_package(self):
        src = self.tmp / "app-kinds.conf"
        src.write_text("com.a.app xr\nbad pkg xr\ncom.b.app auto\ncom.a.app 2d\n../x 2d\nnospace\n")
        done = wgapps_call(self.env, "apps_kind_import", str(src))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.kinds.read_text(), "com.a.app 2d\n")

    def test_an_import_refuses_binary_and_oversized_files(self):
        big = self.tmp / "big"
        big.write_bytes(b"a" * 70000)
        binary = self.tmp / "bin"
        binary.write_bytes(b"com.a.app xr\n\0")
        for path in (big, binary):
            self.assertNotEqual(wgapps_call(self.env, "apps_kind_import", str(path)).returncode, 0)
        self.assertFalse(self.kinds.exists())


if __name__ == "__main__":
    unittest.main()
