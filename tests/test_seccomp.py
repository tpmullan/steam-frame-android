"""The seccomp profile wgapps gives Android, and why it must never fake identity calls.

docs/bugs/2026-11-15-lepton-seccomp-boot.md: Valve's Lepton profile of 2026-10-09 answers setuid,
setgid, setgroups and chown with fake success. In our container init then thinks it became a
service's user (logd) while it is still root, the exec of the 0550 binary owned by that user fails
with "Permission denied", and Android never boots (no logd, zygote restarting, no logcat).
"""

import json
import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = (HERE.parent / "bin/wgapps").read_text()
LEPTON_FIXTURE = HERE / "fixtures/seccomp-lepton-2026-10-09.json"

# Calls a service launcher makes to become another user; faking them leaves the caller root.
IDENTITY_CALLS = {"setuid", "setgid", "setgroups", "chown", "fchown", "fchownat", "lchown"}
# Calls a rootless container cannot make but Android makes at boot; they must succeed (fake).
MUST_SUCCEED = {"setpriority", "nice"}


def faked(profile, names):
    """The names among NAMES that the profile answers with success without doing anything."""
    out = set()
    for rule in profile["syscalls"]:
        if rule["action"] == "SCMP_ACT_ERRNO" and rule.get("errnoRet") == 0:
            out |= names & set(rule["names"])
    return out


def own_profile():
    match = re.search(r"<<'JSON'\n(.*?)\n\s*JSON\n", SCRIPT, re.S)
    assert match, "no embedded profile"
    return json.loads(match.group(1))


def exec_allowed(mode, owner, caller_uid, caller_has_dac_override):
    """Can the caller exec a file of MODE (e.g. 0o550) owned by OWNER (group = owner)?"""
    if caller_has_dac_override:
        return mode & 0o111 != 0
    if caller_uid == owner:
        return mode & 0o100 != 0
    return mode & 0o001 != 0  # not the owner, not in the group: "other" bits


class LeptonProfileReproductionTests(unittest.TestCase):
    def test_lepton_2026_10_09_fakes_the_identity_calls(self):
        # The reproduction: this is the shape of the profile that broke every install on a Frame
        # with a current Lepton.
        profile = json.loads(LEPTON_FIXTURE.read_text())
        self.assertEqual(faked(profile, IDENTITY_CALLS), IDENTITY_CALLS)

    def test_the_mechanism_a_faked_setuid_leaves_init_unable_to_exec_logd(self):
        logd = {"mode": 0o550, "owner": 1036}
        # Real setuid(1036): the service runs as its own user and can exec its binary.
        self.assertTrue(exec_allowed(**logd, caller_uid=1036, caller_has_dac_override=False))
        # Faked setuid: still root, and init has dropped the capabilities it kept for itself.
        self.assertFalse(exec_allowed(**logd, caller_uid=0, caller_has_dac_override=False))

    def test_our_profile_never_fakes_the_identity_calls(self):
        self.assertEqual(faked(own_profile(), IDENTITY_CALLS), set())

    def test_our_profile_still_fakes_what_android_needs_at_boot(self):
        self.assertEqual(faked(own_profile(), MUST_SUCCEED), MUST_SUCCEED)

    def test_our_profile_is_a_valid_allow_by_default_profile_that_denies_modules(self):
        profile = own_profile()
        self.assertEqual(profile["defaultAction"], "SCMP_ACT_ALLOW")
        by_name = {n: rule for rule in profile["syscalls"] for n in rule["names"]}
        self.assertNotIn("errnoRet", by_name["finit_module"])
        for allowed in ("sched_setscheduler", "ioprio_set", "execve"):
            self.assertNotIn(allowed, by_name)


class StartUsesOurProfileTests(unittest.TestCase):
    def test_start_always_passes_our_profile_and_never_lepton_s(self):
        self.assertIn('--security-opt "seccomp=$(write_seccomp)"', SCRIPT)
        self.assertNotIn("seccomp=$BASE/lepton", SCRIPT)
        self.assertNotIn('cp "$LEPTON_SECCOMP"', SCRIPT)  # install no longer copies Valve's

    def test_a_copy_left_by_an_older_install_is_removed(self):
        self.assertGreaterEqual(SCRIPT.count('rm -f "$BASE/lepton.seccomp.json"'), 2)


if __name__ == "__main__":
    unittest.main()
