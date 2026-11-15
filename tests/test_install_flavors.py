"""Fresh installs of both image flavors: with Google apps (GAPPS, default) and without (VANILLA).

Nothing is downloaded from the internet: the OTA lookup is a stub and the "images" are local zips.
Covers the real bin/fetch-images.sh.
"""

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import zipfile

from helpers import BIN

HERE = pathlib.Path(__file__).resolve().parent
BUILD = "20260927"

STUB_OTA = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, sys
    args = sys.argv[1:]
    flavor = args[args.index("--flavor") + 1] if "--flavor" in args else "NONE"
    open(sys.argv[0] + ".args", "a").write(" ".join(args) + "\\n")
    meta = json.load(open(sys.argv[0] + ".json"))[flavor]
    print("BUILD=%s" % meta["build"])
    for prefix in ("SYSTEM", "VENDOR"):
        print("%s_URL=%s" % (prefix, meta[prefix.lower()]["url"]))
        print("%s_SHA256=%s" % (prefix, meta[prefix.lower()]["sha"]))
    """
)


def make_zip(path, member, content):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(member, content)
    return {"url": "file://" + str(path), "sha": hashlib.sha256(path.read_bytes()).hexdigest()}


@unittest.skipUnless(shutil.which("bash") and shutil.which("bsdtar"), "needs bash and bsdtar")
class FetchImagesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        self.base = root / "base"
        self.bin = root / "bin"
        self.bin.mkdir()
        shutil.copy(BIN / "fetch-images.sh", self.bin / "fetch-images.sh")
        ota = self.bin / "wgapps-ota"
        ota.write_text(STUB_OTA)
        ota.chmod(0o755)
        vendor = make_zip(root / "vendor.zip", "vendor.img", "VENDOR")
        meta = {}
        for flavor in ("GAPPS", "VANILLA"):
            system = make_zip(root / f"system-{flavor}.zip", "system.img", f"SYSTEM-{flavor}")
            meta[flavor] = {"build": BUILD, "system": system, "vendor": vendor}
        (self.bin / "wgapps-ota.json").write_text(json.dumps(meta))
        self.ota_args = self.bin / "wgapps-ota.args"

    def fetch(self, **env):
        done = subprocess.run(
            ["bash", str(self.bin / "fetch-images.sh")],
            env={
                "PATH": os.environ["PATH"],
                "HOME": str(self.base),
                "WGAPPS_BASE": str(self.base),
                **env,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done.stdout

    def images(self):
        return self.base / "images"

    def test_a_fresh_install_defaults_to_google_apps_and_keeps_the_old_marker(self):
        self.fetch()
        self.assertEqual((self.images() / "system.img").read_text(), "SYSTEM-GAPPS")
        self.assertEqual((self.images() / "vendor.img").read_text(), "VENDOR")
        # Existing installs recorded exactly this; a different format would re-download 1.3 GB.
        self.assertEqual(
            (self.images() / "variant").read_text().strip(), f"waydroid_arm64_only {BUILD}"
        )
        self.assertTrue((self.images() / "DONE").exists())
        self.assertIn("--flavor GAPPS", self.ota_args.read_text())

    def test_a_fresh_vanilla_install_gets_the_vanilla_system_image_and_its_own_marker(self):
        self.fetch(WGAPPS_FLAVOR="VANILLA")
        self.assertEqual((self.images() / "system.img").read_text(), "SYSTEM-VANILLA")
        self.assertEqual(
            (self.images() / "variant").read_text().strip(), f"waydroid_arm64_only VANILLA {BUILD}"
        )
        self.assertIn("--flavor VANILLA", self.ota_args.read_text())

    def test_the_recorded_flavor_is_used_when_the_environment_says_nothing(self):
        self.base.mkdir()
        (self.base / "flavor").write_text("VANILLA\n")
        self.fetch()
        self.assertEqual((self.images() / "system.img").read_text(), "SYSTEM-VANILLA")

    def test_a_second_run_of_the_same_flavor_downloads_nothing(self):
        self.fetch()
        calls = self.ota_args.read_text().count("\n")
        out = self.fetch()
        self.assertIn("already downloaded", out)
        self.assertEqual((self.images() / "system.img").read_text(), "SYSTEM-GAPPS")
        self.assertEqual(self.ota_args.read_text().count("\n"), calls + 1)  # resolved, not fetched

    def test_switching_flavor_in_the_same_base_replaces_the_system_image(self):
        # The bug a one-line edit of wgapps-ota had: the old marker said "already downloaded".
        self.fetch()
        self.fetch(WGAPPS_FLAVOR="VANILLA")
        self.assertEqual((self.images() / "system.img").read_text(), "SYSTEM-VANILLA")
        self.fetch(WGAPPS_FLAVOR="GAPPS")
        self.assertEqual((self.images() / "system.img").read_text(), "SYSTEM-GAPPS")
        self.assertEqual(
            (self.images() / "variant").read_text().strip(), f"waydroid_arm64_only {BUILD}"
        )

    def test_a_corrupt_download_is_not_accepted(self):
        meta = json.loads((self.bin / "wgapps-ota.json").read_text())
        meta["GAPPS"]["system"]["sha"] = "0" * 64
        (self.bin / "wgapps-ota.json").write_text(json.dumps(meta))
        done = subprocess.run(
            ["bash", "-c", f"timeout 8 bash {self.bin / 'fetch-images.sh'}"],
            env={"PATH": os.environ["PATH"], "HOME": str(self.base), "WGAPPS_BASE": str(self.base)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(done.returncode, 0)  # gave up (timed out) rather than marking it done
        self.assertFalse((self.images() / "DONE").exists())


if __name__ == "__main__":
    unittest.main()
