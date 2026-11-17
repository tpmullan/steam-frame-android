"""Per-app overrides in bin/wgapps: `wgapps app`, the per-package files, the boot-time
`wrap.` properties and the mounts that give Android's apps libwgapps_props.so."""

import os
import pathlib
import shutil
import tempfile
import unittest

from helpers import wgapps_call, wgapps_mounts

WOLVIC = "com.igalia.wolvic.vanilla"
# Android keeps a copy of each product property per partition, and apps differ in which they read
# (Wolvic reads the vendor one, Java's Build.MODEL the plain one).
PARTITIONS = ("", "system.", "vendor.", "odm.", "system_ext.", "vendor_dlkm.", "product.")


def lines_for(key, value):
    return [f"ro.product.{partition}{key}={value}" for partition in PARTITIONS]


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class AppOverrideTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name) / "base"
        self.library = self.base / "lib/libwgapps_props.so"
        self.library.parent.mkdir(parents=True)
        self.library.write_text("")
        self.conf = self.base / "apps.conf"
        self.props_d = self.base / "run/props.d"
        self.env = {"HOME": str(self.base / "home"), "WGAPPS_BASE": str(self.base)}

    def call(self, function, *args):
        return wgapps_call(self.env, function, *args)

    def ok(self, function, *args):
        done = self.call(function, *args)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def conf_lines(self):
        return self.conf.read_text().splitlines() if self.conf.exists() else []

    # --- apps.conf --------------------------------------------------------------------

    def test_set_writes_apps_conf(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        self.assertEqual(self.conf_lines(), [f"{WOLVIC} model=Quest 3"])

    def test_set_replaces_the_same_key_and_keeps_the_others(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        self.ok("cmd_app", "set", WOLVIC, "brand", "Meta")
        self.ok("cmd_app", "set", "com.other.app", "model", "Pixel 8")
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest Pro")
        self.assertEqual(
            sorted(self.conf_lines()),
            sorted(
                [f"{WOLVIC} brand=Meta", f"{WOLVIC} model=Quest Pro", "com.other.app model=Pixel 8"]
            ),
        )

    def test_unset_one_key_then_the_whole_package(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        self.ok("cmd_app", "set", WOLVIC, "brand", "Meta")
        self.ok("cmd_app", "set", "com.other.app", "model", "Pixel 8")
        self.ok("cmd_app", "unset", WOLVIC, "model")
        self.assertEqual(
            sorted(self.conf_lines()), [f"{WOLVIC} brand=Meta", "com.other.app model=Pixel 8"]
        )
        self.ok("cmd_app", "unset", WOLVIC)
        self.assertEqual(self.conf_lines(), ["com.other.app model=Pixel 8"])

    def test_a_package_name_that_is_a_prefix_of_another_is_not_touched(self):
        self.ok("cmd_app", "set", "com.x.app", "model", "A")
        self.ok("cmd_app", "set", "com.x.app2", "model", "B")
        self.ok("cmd_app", "unset", "com.x.app")
        self.assertEqual(self.conf_lines(), ["com.x.app2 model=B"])

    def test_list_prints_the_overrides(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        self.assertEqual(
            self.ok("cmd_app", "list").stdout.splitlines(), [f"{WOLVIC} model=Quest 3"]
        )

    def test_list_with_none_says_so(self):
        self.assertIn("no per-app overrides", self.ok("cmd_app", "list").stdout)

    def test_unset_of_something_not_set_is_fine(self):
        self.ok("cmd_app", "unset", WOLVIC)
        self.ok("cmd_app", "unset", WOLVIC, "model")

    def test_bad_input_is_rejected_and_nothing_is_written(self):
        bad = [
            (WOLVIC, "model", "a'b"),
            (WOLVIC, "model", "a;b"),
            (WOLVIC, "model", "$(touch x)"),
            (WOLVIC, "model", "a\nb"),
            (WOLVIC, "model", "back\\slash"),
            (WOLVIC, "model", 'quo"te'),
            (WOLVIC, "model", ""),
            (WOLVIC, "model", " leading"),
            (WOLVIC, "model", "trailing "),
            (WOLVIC, "model", "v" * 92),
            (WOLVIC, "foo", "x"),
            (WOLVIC, "model brand", "x"),
            (WOLVIC, "", "x"),
            ("bad pkg", "model", "x"),
            ("nodots", "model", "x"),
            ("com..x", "model", "x"),
            ("com.x.y;rm", "model", "x"),
            ("com." + "a" * 51, "model", "x"),  # 55 characters
        ]
        for args in bad:
            with self.subTest(args=args):
                done = self.call("cmd_app", "set", *args)
                self.assertNotEqual(done.returncode, 0)
                self.assertFalse(self.conf.exists(), done.stdout + done.stderr)

    def test_the_longest_allowed_package_and_value_are_accepted(self):
        self.ok("cmd_app", "set", "com." + "a" * 50, "model", "v" * 91)  # 54-character package
        self.assertEqual(len(self.conf_lines()), 1)

    def test_set_needs_all_three_arguments_and_an_action_is_required(self):
        self.assertNotEqual(self.call("cmd_app", "set", WOLVIC, "model").returncode, 0)
        self.assertNotEqual(self.call("cmd_app", "frobnicate").returncode, 0)
        self.assertNotEqual(self.call("cmd_app").returncode, 0)
        self.assertFalse(self.conf.exists())

    # --- the files Android reads --------------------------------------------------------

    def test_generate_writes_one_file_per_package(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        self.ok("cmd_app", "set", WOLVIC, "manufacturer", "Meta Platforms")
        self.ok("cmd_app", "set", "com.other.app", "device", "eureka")
        self.ok("generate_app_props")
        self.assertEqual(
            sorted((self.props_d / WOLVIC).read_text().splitlines()),
            sorted(lines_for("manufacturer", "Meta Platforms") + lines_for("model", "Quest 3")),
        )
        self.assertEqual(
            (self.props_d / "com.other.app").read_text().splitlines(), lines_for("device", "eureka")
        )
        self.assertEqual(os.stat(self.props_d / WOLVIC).st_mode & 0o777, 0o644)
        self.assertEqual(
            sorted(p.name for p in self.props_d.iterdir()), sorted([WOLVIC, "com.other.app"])
        )

    def test_generate_removes_files_of_packages_no_longer_set_and_keeps_the_directory(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        self.ok("generate_app_props")
        inode = self.props_d.stat().st_ino
        self.ok("cmd_app", "unset", WOLVIC)
        self.ok("generate_app_props")
        self.assertEqual(list(self.props_d.iterdir()), [])
        self.assertEqual(self.props_d.stat().st_ino, inode)  # It is bind-mounted into Android.

    def test_generate_skips_hand_edited_lines_that_are_invalid(self):
        self.conf.write_text(
            f"{WOLVIC} model=Quest 3\n"
            f"{WOLVIC} bogus=1\n"
            "bad pkg model=x\n"
            f"{WOLVIC} brand=we'ird\n"
            "\n"
            "garbage\n"
        )
        self.ok("generate_app_props")
        self.assertEqual(
            (self.props_d / WOLVIC).read_text().splitlines(), lines_for("model", "Quest 3")
        )
        self.assertEqual([p.name for p in self.props_d.iterdir()], [WOLVIC])

    def test_a_stale_file_is_not_kept_by_a_package_that_only_looks_similar(self):
        # "." in a package name is not a wildcard.
        self.props_d.mkdir(parents=True)
        (self.props_d / "com.x.y").write_text("ro.product.model=old\n")
        self.conf.write_text("comAx.y model=Quest 3\n")
        self.ok("generate_app_props")
        self.assertEqual([p.name for p in self.props_d.iterdir()], ["comAx.y"])

    def test_generate_with_no_settings_leaves_an_empty_directory(self):
        self.ok("generate_app_props")
        self.assertEqual(list(self.props_d.iterdir()), [])

    # --- what Android's init and podman are given ---------------------------------------

    def test_wrap_property_per_package(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        self.ok("cmd_app", "set", "com.other.app", "model", "Pixel 8")
        self.ok("generate_app_props")
        lines = self.ok("app_wrap_props").stdout.splitlines()
        self.assertEqual(
            sorted(lines),
            sorted(
                f"wrap.{p}=LD_PRELOAD=/data/wgapps/props.so WGP={p}"
                for p in (WOLVIC, "com.other.app")
            ),
        )

    def test_the_longest_wrap_property_value_fits_in_a_property(self):
        package = "com." + "a" * 50
        self.ok("cmd_app", "set", package, "model", "x")
        self.ok("generate_app_props")
        (line,) = self.ok("app_wrap_props").stdout.splitlines()
        self.assertEqual(len(line.split("=", 1)[1]), 91)

    def test_no_wrap_properties_without_the_library(self):
        # A missing preload library stops the app from starting.
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        self.ok("generate_app_props")
        self.library.unlink()
        self.assertEqual(self.ok("app_wrap_props").stdout, "")

    def test_no_wrap_properties_without_settings(self):
        self.ok("generate_app_props")
        self.assertEqual(self.ok("app_wrap_props").stdout, "")

    def test_mounts_the_library_and_the_per_package_files(self):
        self.ok("generate_app_props")
        mounts = wgapps_mounts("mount_app_props", self.env)
        self.assertEqual(
            mounts,
            {
                "/data/wgapps/props.so": (str(self.library), "ro"),
                "/data/wgapps/props.d": (str(self.props_d), "ro"),
            },
        )

    def test_no_mounts_without_the_library(self):
        self.ok("generate_app_props")
        self.library.unlink()
        self.assertEqual(wgapps_mounts("mount_app_props", self.env), {})

    def test_the_boot_properties_include_the_wrap_lines(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        self.ok("generate_app_props")
        self.ok("write_props", "false")
        props = (self.base / "run/waydroid.prop").read_text().splitlines()
        self.assertIn(f"wrap.{WOLVIC}=LD_PRELOAD=/data/wgapps/props.so WGP={WOLVIC}", props)
        self.assertIn("ro.hardware.gralloc=minigbm_gbm_mesa", props)

    # --- the screen in Android's Settings: import and mirror ---------------------------

    @property
    def shared(self):
        return self.base / "share/device-profiles.conf"

    def test_import_keeps_only_the_valid_lines_and_mirrors_them(self):
        incoming = self.base / "incoming"
        incoming.write_text(
            f"{WOLVIC} model=Quest 3\n"
            f"{WOLVIC} bogus=1\n"
            "com.other.app model=a;b\n"
            "garbage\n"
            "\n"
            "com.other.app brand=Meta\n"
        )
        self.ok("cmd_app", "import", str(incoming))
        self.assertEqual(self.conf_lines(), [f"{WOLVIC} model=Quest 3", "com.other.app brand=Meta"])
        self.assertEqual(self.shared.read_text(), self.conf.read_text())

    def test_import_of_an_empty_file_clears_everything(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        incoming = self.base / "incoming"
        incoming.write_text("")
        self.ok("cmd_app", "import", str(incoming))
        self.assertEqual(self.conf_lines(), [])
        self.assertEqual(list(self.props_d.iterdir()), [])
        self.assertEqual(self.shared.read_text(), "")

    def test_import_keeps_the_last_line_per_package_and_key(self):
        incoming = self.base / "incoming"
        incoming.write_text(f"{WOLVIC} model=First\n{WOLVIC} brand=Meta\n{WOLVIC} model=Second\n")
        self.ok("cmd_app", "import", str(incoming))
        self.assertEqual(self.conf_lines(), [f"{WOLVIC} brand=Meta", f"{WOLVIC} model=Second"])

    def test_import_regenerates_the_per_package_files(self):
        self.ok("cmd_app", "set", "com.old.app", "model", "Old")
        incoming = self.base / "incoming"
        incoming.write_text(f"{WOLVIC} model=Quest 3\n")
        self.ok("cmd_app", "import", str(incoming))
        self.assertEqual([p.name for p in self.props_d.iterdir()], [WOLVIC])

    def test_import_tells_similar_package_names_apart(self):
        # Only a package whose lines changed is touched; "." is not a wildcard in a name.
        self.conf.write_text("com.x.y model=A\ncomAx.y model=B\n")
        incoming = self.base / "incoming"
        incoming.write_text("com.x.y model=A\ncomAx.y model=C\n")
        done = self.ok("cmd_app", "import", str(incoming))
        self.assertIn("imported 1 changed package(s)", done.stderr)

    def test_import_ignores_oversized_and_binary_files(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        for content in (
            b"com.x.y model=" + b"v" * 70000,
            b"com.x.y model=ok\x00\n",
            b"\xff\xfe\x00",
        ):
            incoming = self.base / "incoming"
            incoming.write_bytes(content)
            done = self.call("cmd_app", "import", str(incoming))
            self.assertNotEqual(done.returncode, 0)
            self.assertEqual(self.conf_lines(), [f"{WOLVIC} model=Quest 3"])

    def test_import_of_a_missing_file_changes_nothing(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        self.assertNotEqual(self.call("cmd_app", "import", str(self.base / "nope")).returncode, 0)
        self.assertEqual(self.conf_lines(), [f"{WOLVIC} model=Quest 3"])

    def test_set_and_unset_mirror_to_the_shared_file(self):
        self.ok("cmd_app", "set", WOLVIC, "model", "Quest 3")
        self.assertEqual(self.shared.read_text(), f"{WOLVIC} model=Quest 3\n")
        self.assertEqual(os.stat(self.shared).st_mode & 0o777, 0o644)
        self.ok("cmd_app", "unset", WOLVIC)
        self.assertEqual(self.shared.read_text(), "")
        self.assertEqual(
            sorted(p.name for p in self.shared.parent.iterdir()),
            ["app-kinds.conf", "app-mode.conf", "device-profiles.conf"],
        )

    def test_export_with_no_settings_writes_an_empty_file(self):
        self.ok("export_profiles")
        self.assertEqual(self.shared.read_text(), "")

    # --- the system app in Android's Settings --------------------------------------------

    def test_mounts_the_settings_app_as_a_system_app(self):
        apk = self.base / "lib/WgappsSettings.apk"
        apk.write_text("")
        self.assertEqual(
            wgapps_mounts("mount_settings_app", self.env),
            {"/system/priv-app/WgappsSettings/WgappsSettings.apk": (str(apk), "ro")},
        )

    def test_no_settings_app_mount_without_the_file(self):
        self.assertEqual(wgapps_mounts("mount_settings_app", self.env), {})


if __name__ == "__main__":
    unittest.main()
