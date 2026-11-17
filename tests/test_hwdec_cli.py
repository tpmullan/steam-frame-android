"""wgapps hwdec and install --hwdec: the optional hardware decode add-on shipped in the release."""

import hashlib
import io
import lzma
import pathlib
import shutil
import tarfile
import tempfile
import unittest

from helpers import wgapps_call

SERVICE = "vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2-64"


def archive(entries):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name == SERVICE else 0o644
            tar.addfile(info, io.BytesIO(data))
    return lzma.compress(raw.getvalue())


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class HwdecCliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name).resolve()
        self.base = self.tmp / "base"
        self.pkg = self.base / "hwdec"
        self.pkg.mkdir(parents=True)
        self.base.joinpath("bin").mkdir()
        shutil.copy(
            pathlib.Path(__file__).resolve().parent.parent / "bin/wgapps-hwdec", self.base / "bin"
        )
        self.env = {
            "HOME": str(self.tmp),
            "WGAPPS_BASE": str(self.base),
            "WGAPPS_V4L2_DECODER": "/dev/null",
        }
        self.write_package([(SERVICE, b"#!service\n"), ("vendor/lib64/a.so", b"a")])

    def write_package(self, entries, tamper=False):
        data = archive(entries)
        (self.pkg / "wgapps-hwdec.tar.xz").write_bytes(data + (b"x" if tamper else b""))
        (self.pkg / "SHA256SUMS").write_text(
            f"{hashlib.sha256(data).hexdigest()}  wgapps-hwdec.tar.xz\n"
        )

    def hwdec(self, *args):
        return wgapps_call(self.env, "cmd_hwdec", *args)

    def flag(self):
        path = self.base / "hwdec-enabled"
        return path.read_text().strip() if path.exists() else None

    def test_install_unpacks_the_checked_package_turns_it_on_and_warns(self):
        done = self.hwdec("install")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.base / "lib/v4l2-codec2" / SERVICE).is_file())
        self.assertEqual(self.flag(), "on")
        self.assertIn("WARNING", done.stderr)
        self.assertIn("wgapps hwdec off", done.stderr)

    def test_a_package_that_fails_its_checksum_installs_nothing(self):
        self.write_package([(SERVICE, b"#!service\n")], tamper=True)
        done = self.hwdec("install")
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse((self.base / "lib/v4l2-codec2").exists())
        self.assertIsNone(self.flag())

    def test_on_and_off_switch_the_flag_and_on_needs_an_install(self):
        self.assertNotEqual(self.hwdec("on").returncode, 0)
        self.assertIsNone(self.flag())
        self.hwdec("install")
        self.hwdec("off")
        self.assertEqual(self.flag(), "off")
        self.assertTrue((self.base / "lib/v4l2-codec2" / SERVICE).is_file())  # off keeps the files
        self.hwdec("on")
        self.assertEqual(self.flag(), "on")

    def test_remove_deletes_the_files_and_the_flag(self):
        self.hwdec("install")
        self.assertEqual(self.hwdec("remove").returncode, 0)
        self.assertFalse((self.base / "lib/v4l2-codec2").exists())
        self.assertIsNone(self.flag())

    def test_status_reports_each_piece(self):
        before = self.hwdec("status").stdout
        self.assertIn("add-on in this release: ok", before)
        self.assertIn("installed:              no", before)
        self.assertIn("used at next start:     no", before)
        self.hwdec("install")
        after = self.hwdec("status").stdout
        self.assertIn("installed:              yes", after)
        self.assertIn("turned on:              yes", after)
        self.assertIn("decoder node:           /dev/null", after)
        self.assertIn("used at next start:     yes", after)
        self.write_package([(SERVICE, b"#!newer\n")])
        self.assertIn("a newer one is in this release", self.hwdec("status").stdout)

    def test_unknown_actions_are_refused(self):
        self.assertNotEqual(self.hwdec("explode").returncode, 0)

    def test_update_carries_over_what_the_user_installed_in_lib(self):
        old, new = self.tmp / "old-lib", self.tmp / "new-lib"
        (old / "v4l2-codec2/vendor").mkdir(parents=True)
        (old / "v4l2-codec2/vendor/x").write_text("decoder")
        (old / "WgappsSettings.apk").write_text("apk")
        (old / ".hidden-file").write_text("h")
        (old / "libgbinder.so.1").write_text("old")
        new.mkdir()
        (new / "libgbinder.so.1").write_text("new")
        done = wgapps_call(self.env, "update_keep_installed_libs", str(old), str(new))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((new / "v4l2-codec2/vendor/x").read_text(), "decoder")
        self.assertEqual((new / "WgappsSettings.apk").read_text(), "apk")
        self.assertEqual((new / ".hidden-file").read_text(), "h")
        self.assertEqual((new / "libgbinder.so.1").read_text(), "new")  # the release's wins

    def test_usage_lists_the_command_and_the_install_flag(self):
        text = (pathlib.Path(__file__).resolve().parent.parent / "bin/wgapps").read_text()
        self.assertIn("hwdec [status|install|on|off|remove]", text)
        self.assertIn("install [--vanilla] [--hwdec]", text)
        self.assertIn('hwdec) cmd_hwdec "$@" ;;', text)
        self.assertNotEqual(wgapps_call(self.env, "cmd_install", "--bogus").returncode, 0)


if __name__ == "__main__":
    unittest.main()
