"""wgapps-hwdec: checksum and safe unpacking of the optional hardware decode add-on."""

import hashlib
import io
import lzma
import pathlib
import tarfile
import tempfile
import unittest

import helpers

hwdec = helpers.load("wgapps-hwdec")
SERVICE = hwdec.SERVICE


def make_archive(entries):
    """entries: (name, bytes or None, kind) with kind "file", "link", "dir" or "dev"."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == "file":
                info.size = len(data)
                info.mode = 0o755 if name == SERVICE else 0o644
                tar.addfile(info, io.BytesIO(data))
            elif kind == "link":
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tar.addfile(info)
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                info.type = tarfile.CHRTYPE
                tar.addfile(info)
    return lzma.compress(raw.getvalue())


GOOD = [
    (SERVICE, b"#!service\n", "file"),
    ("vendor/lib64/libv4l2_codec2_components.so", b"lib", "file"),
    ("system/lib64/libc2plugin_store.so", b"plug", "file"),
]


class HwdecHelperTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        self.pkg = self.root / "hwdec"
        self.pkg.mkdir()
        self.dest = self.root / "lib/v4l2-codec2"

    def package(self, entries=GOOD, tamper=False, sums=True):
        data = make_archive(entries)
        (self.pkg / hwdec.ARCHIVE).write_bytes(data + (b"x" if tamper else b""))
        if sums:
            (self.pkg / "SHA256SUMS").write_text(
                f"{hashlib.sha256(data).hexdigest()}  {hwdec.ARCHIVE}\n"
            )

    def run_main(self, *args):
        return hwdec.main(["wgapps-hwdec", *map(str, args)])

    def test_a_good_package_is_unpacked_with_modes_and_a_marker(self):
        self.package()
        self.assertEqual(self.run_main("install", self.pkg, self.dest), 0)
        self.assertEqual((self.dest / SERVICE).read_bytes(), b"#!service\n")
        self.assertTrue((self.dest / SERVICE).stat().st_mode & 0o111)
        self.assertFalse(
            (self.dest / "vendor/lib64/libv4l2_codec2_components.so").stat().st_mode & 0o111
        )
        digest = hashlib.sha256((self.pkg / hwdec.ARCHIVE).read_bytes()).hexdigest()
        self.assertEqual((self.dest / hwdec.MARKER).read_text().strip(), digest)

    def test_a_changed_archive_or_missing_checksum_is_refused_and_nothing_is_written(self):
        self.package(tamper=True)
        self.assertEqual(self.run_main("install", self.pkg, self.dest), 1)
        self.assertFalse(self.dest.exists())
        self.package(sums=False)
        (self.pkg / "SHA256SUMS").unlink()
        self.assertEqual(self.run_main("install", self.pkg, self.dest), 1)
        (self.pkg / "SHA256SUMS").write_text("nonsense\n")
        self.assertEqual(self.run_main("install", self.pkg, self.dest), 1)
        self.assertFalse(self.dest.exists())

    def test_a_release_without_the_archive_says_so(self):
        self.assertEqual(self.run_main("install", self.pkg, self.dest), 1)
        self.assertEqual(self.run_main("verify", self.pkg), 1)

    def test_hostile_archives_are_refused_whatever_their_checksum(self):
        bad = {
            "dot dot": [*GOOD, ("vendor/../../evil", b"x", "file")],
            "absolute": [*GOOD, ("/etc/evil", b"x", "file")],
            "other top directory": [*GOOD, ("etc/evil", b"x", "file")],
            "symlink": [*GOOD, ("vendor/lib64/link.so", None, "link")],
            "directory entry": [*GOOD, ("vendor/lib64", None, "dir")],
            "device": [*GOOD, ("vendor/lib64/dev", None, "dev")],
            "odd characters": [*GOOD, ("vendor/lib64/a b;rm.so", b"x", "file")],
            "no service": [GOOD[1], GOOD[2]],
        }
        for label, entries in bad.items():
            self.package(entries)
            self.assertEqual(self.run_main("install", self.pkg, self.dest), 1, label)
            self.assertFalse(self.dest.exists(), label)
            self.assertFalse(self.dest.with_name(self.dest.name + ".new").exists(), label)

    def test_a_failed_reinstall_leaves_the_working_one_alone(self):
        self.package()
        self.run_main("install", self.pkg, self.dest)
        self.package([*GOOD, ("vendor/../x", b"x", "file")])
        self.assertEqual(self.run_main("install", self.pkg, self.dest), 1)
        self.assertEqual((self.dest / SERVICE).read_bytes(), b"#!service\n")

    def test_a_reinstall_replaces_the_files_and_drops_the_old_ones(self):
        self.package()
        self.run_main("install", self.pkg, self.dest)
        self.package([(SERVICE, b"#!v2\n", "file")])
        self.assertEqual(self.run_main("install", self.pkg, self.dest), 0)
        self.assertEqual((self.dest / SERVICE).read_bytes(), b"#!v2\n")
        self.assertFalse((self.dest / "system").exists())

    def test_status_tells_package_installed_and_whether_the_install_is_current(self):
        out = io.StringIO()
        import contextlib

        def status():
            out.seek(0)
            out.truncate()
            with contextlib.redirect_stdout(out):
                self.run_main("status", self.pkg, self.dest)
            return dict(line.split("=") for line in out.getvalue().split())

        self.assertEqual(status(), {"package": "missing", "installed": "no", "current": "n/a"})
        self.package()
        self.assertEqual(status(), {"package": "ok", "installed": "no", "current": "n/a"})
        self.run_main("install", self.pkg, self.dest)
        self.assertEqual(status(), {"package": "ok", "installed": "yes", "current": "yes"})
        self.package([(SERVICE, b"newer", "file")])
        self.assertEqual(status(), {"package": "ok", "installed": "yes", "current": "no"})
        self.package(tamper=True)
        self.assertEqual(status()["package"], "bad")

    def test_the_shipped_package_matches_its_checksum_and_unpacks(self):
        shipped = pathlib.Path(__file__).resolve().parent.parent / "hwdec"
        self.assertEqual(self.run_main("verify", shipped), 0)
        self.assertEqual(self.run_main("install", shipped, self.dest), 0)
        self.assertTrue((self.dest / SERVICE).is_file())
        self.assertEqual(
            len([p for p in self.dest.rglob("*") if p.is_file()]), 23
        )  # 22 files and the marker


if __name__ == "__main__":
    unittest.main()
