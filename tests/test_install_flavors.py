"""Fresh installs of both image flavors: with Google apps (GAPPS, default) and without (VANILLA).

Nothing is downloaded from the internet: the OTA lookup is a stub and the "images" are local zips.
Covers the real bin/fetch-images.sh and the install command's flavor handling.
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

from helpers import BIN, wgapps_call

HERE = pathlib.Path(__file__).resolve().parent
LEPTON_FIXTURE = HERE / "fixtures/seccomp-lepton-2026-10-09.json"
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


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class InstallTests(unittest.TestCase):
    """`wgapps install` end to end except the parts that need a Frame."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = pathlib.Path(tmp.name)
        self.base = self.home / "base"
        (self.base / "bin").mkdir(parents=True)
        stub = self.base / "bin/fetch-images.sh"
        stub.write_text('#!/bin/bash\necho "$WGAPPS_FLAVOR" >"$WGAPPS_BASE/fetch-flavor"\n')
        stub.chmod(0o755)
        # An installed Lepton with the profile that broke Android's boot.
        lepton = self.home / ".local/share/Steam/steamapps/common/Lepton/liblepton"
        lepton.mkdir(parents=True)
        shutil.copy(LEPTON_FIXTURE, lepton / "lepton.seccomp.json")
        self.env = {
            "HOME": str(self.home),
            "WGAPPS_BASE": str(self.base),
            "WGAPPS_SKIP_SHORTCUTS": "1",
        }

    def install(self, *args):
        script = "check_prereqs() { :; }; cmd_prepare() { :; }; cmd_install " + " ".join(args)
        done = wgapps_call(self.env, "eval", script)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stderr

    def fetched(self):
        return (self.base / "fetch-flavor").read_text().strip()

    def test_the_default_install_is_with_google_apps_and_says_how_to_sign_in(self):
        err = self.install()
        self.assertEqual((self.base / "flavor").read_text().strip(), "GAPPS")
        self.assertEqual(self.fetched(), "GAPPS")
        self.assertIn("GAPPS images", err)
        self.assertIn("gsf-id", err)
        self.assertIn("google.com/android/uncertified", err)

    def test_install_gapps_is_the_same_as_the_default(self):
        self.install("--gapps")
        self.assertEqual(self.fetched(), "GAPPS")

    def test_install_vanilla_has_no_google_step_and_remembers_the_choice(self):
        err = self.install("--vanilla")
        self.assertEqual((self.base / "flavor").read_text().strip(), "VANILLA")
        self.assertEqual(self.fetched(), "VANILLA")
        self.assertIn("without Google apps", err)
        self.assertNotIn("uncertified", err)

    def test_a_plain_reinstall_keeps_the_flavor_chosen_before(self):
        self.install("--vanilla")
        self.install()
        self.assertEqual(self.fetched(), "VANILLA")
        self.install("--gapps")
        self.assertEqual(self.fetched(), "GAPPS")

    def test_install_never_copies_lepton_s_seccomp_profile(self):
        # docs/bugs/2026-11-15-lepton-seccomp-boot.md: with that copy, a fresh install never booted.
        for flavor in ("--gapps", "--vanilla"):
            self.install(flavor)
            self.assertFalse((self.base / "lepton.seccomp.json").exists(), flavor)

    def test_install_removes_a_copy_left_by_an_older_install(self):
        (self.base / "lepton.seccomp.json").write_text("{}")
        err = self.install()
        self.assertFalse((self.base / "lepton.seccomp.json").exists())
        self.assertIn("own profile", err)


if __name__ == "__main__":
    unittest.main()
