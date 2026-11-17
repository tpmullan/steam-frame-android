"""Image flavor: GAPPS (default) or VANILLA, chosen at install."""

import pathlib
import subprocess
import tempfile
import unittest

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"


def call(base, *args):
    return subprocess.run(
        ["bash", str(BIN / "wgapps"), *args],
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(base), "WGAPPS_BASE": str(base)},
        capture_output=True,
        text=True,
        check=False,
    )


class FlavorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name)

    def test_gsf_id_explains_itself_on_a_vanilla_install(self):
        (self.base / "flavor").write_text("VANILLA\n")
        done = call(self.base, "gsf-id")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no Google apps", done.stderr)

    def test_install_rejects_unknown_options_before_doing_anything(self):
        done = call(self.base, "install", "--nope")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("usage: wgapps install", done.stderr)
        self.assertFalse((self.base / "flavor").exists())


if __name__ == "__main__":
    unittest.main()
