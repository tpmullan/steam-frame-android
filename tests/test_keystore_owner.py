"""keystore2 aborts at boot when /data/misc/keystore holds root-owned files.

docs/bugs/2026-11-15-keystore-owner.md: a boot under Lepton's 2026-10-09 seccomp profile (setuid and
chown faked) leaves persistent.sqlite owned by root. Under wgapps' own profile keystore2 runs as
uid 1017, open() fails with EACCES, keystore2 panics "Failed to attach database persistent", and
Android loops. Reported on issue 2 by a user who reinstalled over data from that era.
"""

import pathlib
import subprocess
import tempfile
import unittest

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin/wgapps"


def run_repair(args, tmp):
    """Run `wgapps _repair-keystore` with chown replaced by a recorder."""
    stub = pathlib.Path(tmp) / "stub"
    stub.mkdir(exist_ok=True)
    log = pathlib.Path(tmp) / "chown.log"
    chown = stub / "chown"
    chown.write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    chown.chmod(0o755)
    env = {"PATH": f"{stub}:/usr/bin:/bin", "HOME": tmp, "WGAPPS_BASE": f"{tmp}/base"}
    subprocess.run(["bash", str(BIN), "_repair-keystore", *args], env=env, check=True)
    return log.read_text().split() if log.exists() else []


class KeystoreOwnerTests(unittest.TestCase):
    def test_files_not_owned_by_keystore_are_handed_to_uid_1017(self):
        with tempfile.TemporaryDirectory() as tmp:
            ks = pathlib.Path(tmp) / "keystore"
            ks.mkdir()
            (ks / "persistent.sqlite").write_text("x")  # owned by us, i.e. "not 1017"
            calls = run_repair([str(ks)], tmp)
            self.assertIn("-h", calls)
            self.assertIn("1017:1017", calls)
            self.assertIn(str(ks / "persistent.sqlite"), calls)

    def test_a_missing_directory_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run_repair([f"{tmp}/none"], tmp), [])

    def test_start_repairs_before_android_boots_and_inside_the_user_namespace(self):
        script = BIN.read_text()
        start = script[script.index("cmd_start() {") :]
        self.assertIn('podman unshare "$0" _repair-keystore "$DATA/misc/keystore"', start)
        self.assertLess(start.index("_repair-keystore"), start.index('podman "${ARGS[@]}"'))

    def test_uid_is_android_s_keystore_aid(self):
        self.assertIn("AID_KEYSTORE=1017", BIN.read_text())


if __name__ == "__main__":
    unittest.main()
