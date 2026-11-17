"""Window mode (`wgapps windows`) and the per-app launch kind (`wgapps apps kind`)."""

import pathlib
import shutil
import tempfile
import unittest

from helpers import BIN, wgapps_call

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
            (base / "run/waydroid.prop").write_text("ro.hardware.egl=mesa\nandroid_id=abc123\n")
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


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class ComposerEglTests(unittest.TestCase):
    VENDOR = "vendor/etc/init/android.hardware.graphics.composer@2.1-service.rc"
    OWN = "system/etc/init/z_wgapps.rc"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name) / "base"
        for rc, text in (
            (self.VENDOR, "service vendor.hwcomposer-2-1 /vendor/bin/x\n    user system\n"),
            (
                self.OWN,
                "service other /x\n    user root\n"
                "service vendor.hwcomposer-2-1 /vendor/bin/y\n    override\n    user root\n",
            ),
        ):
            path = self.base / "rootfs" / rc
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        (self.base / "lib").mkdir()
        (self.base / "lib/libwgapps_props.so").write_text("elf")
        (self.base / "run").mkdir()
        self.env = {"HOME": tmp.name, "WGAPPS_BASE": str(self.base)}

    def mount(self, mode):
        if mode:
            (self.base / "gpu-egl").write_text(mode + "\n")
        done = wgapps_call(self.env, "eval", "prepare_composer_egl; mount_composer_egl")
        self.assertEqual(done.returncode, 0, done.stderr)

    def patched(self, rc):
        return (self.base / "run" / ("composer-" + rc.replace("/", "_"))).read_text()

    def test_angle_gives_the_composer_mesa_in_every_rc_that_defines_it(self):
        self.mount("angle")
        for rc in (self.VENDOR, self.OWN):
            text = self.patched(rc)
            service, _, rest = text.partition("service vendor.hwcomposer-2-1")
            self.assertIn("setenv LD_PRELOAD /vendor/lib64/libwgapps_props.so", rest, rc)
            self.assertIn("setenv WGP wgapps.composer", rest, rc)
            self.assertNotIn("setenv", service, rc)  # not on the other service
        self.assertEqual(
            (self.base / "run/props.d/wgapps.composer").read_text().strip(), "ro.hardware.egl=mesa"
        )

    def test_an_override_of_the_rc_is_what_gets_patched(self):
        path = self.base / "overrides" / self.OWN
        path.parent.mkdir(parents=True)
        path.write_text(
            "service vendor.hwcomposer-2-1 /vendor/bin/z\n    override\n    user root\n"
        )
        self.mount("angle")
        self.assertIn("/vendor/bin/z", self.patched(self.OWN))
        self.assertIn("setenv WGP wgapps.composer", self.patched(self.OWN))

    def test_a_file_the_overrides_bind_is_not_bound_a_second_time(self):
        # podman refuses two mounts on one destination; the overrides loop binds
        # the patched copy instead, so this function must skip that file.
        path = self.base / "overrides" / self.OWN
        path.parent.mkdir(parents=True)
        path.write_text("service vendor.hwcomposer-2-1 /vendor/bin/z\n")
        script = "prepare_composer_egl; mount_composer_egl; printf '%s\\n' \"${ARGS[@]}\""
        (self.base / "gpu-egl").write_text("angle\n")
        done = wgapps_call(self.env, "eval", script)
        self.assertEqual(done.returncode, 0, done.stderr)
        destinations = [line for line in done.stdout.splitlines() if "destination=" in line]
        self.assertEqual(len(destinations), len(set(destinations)))
        self.assertFalse(any("z_wgapps.rc" in d for d in destinations))
        self.assertTrue(any("composer@2.1-service.rc" in d for d in destinations))

    def test_mesa_leaves_the_composer_alone_and_removes_a_stale_file(self):
        (self.base / "run/props.d").mkdir()
        (self.base / "run/props.d/wgapps.composer").write_text("ro.hardware.egl=mesa\n")
        self.mount("mesa")
        self.assertFalse((self.base / "run/props.d/wgapps.composer").exists())
        self.assertEqual(list((self.base / "run").glob("composer-*")), [])

    def test_the_composer_file_is_not_a_per_app_override(self):
        self.mount("angle")
        done = wgapps_call(self.env, "app_wrap_props")
        self.assertNotIn("wgapps.composer", done.stdout)
        wgapps_call(self.env, "generate_app_props")
        self.assertTrue((self.base / "run/props.d/wgapps.composer").exists())

    def test_the_preload_accepts_the_composer_file_name(self):
        # props-override ignores a WGP with anything but letters, digits, _ and .;
        # a hyphen in the name made the whole override a silent no-op.
        import re

        match = re.search(r"COMPOSER_PROPS=(\S+)", (BIN / "wgapps").read_text())
        self.assertIsNotNone(match)
        self.assertRegex(match.group(1), r"^[A-Za-z0-9_][A-Za-z0-9_.]*$")
