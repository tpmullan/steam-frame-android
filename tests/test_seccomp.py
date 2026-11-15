"""The seccomp profile wgapps writes when Lepton's is not installed."""

import json
import pathlib
import re
import unittest

SCRIPT = (pathlib.Path(__file__).resolve().parent.parent / "bin/wgapps").read_text()


class SeccompTests(unittest.TestCase):
    def profile(self):
        match = re.search(r"<<'JSON'\n(.*?)\n\s*JSON\n", SCRIPT, re.S)
        self.assertIsNotNone(match, "no embedded profile")
        return json.loads(match.group(1))

    def test_profile_fakes_setpriority_and_denies_modules(self):
        profile = self.profile()
        self.assertEqual(profile["defaultAction"], "SCMP_ACT_ALLOW")
        by_name = {n: rule for rule in profile["syscalls"] for n in rule["names"]}
        for faked in ("setpriority", "nice"):
            self.assertEqual(by_name[faked]["errnoRet"], 0, faked)
        self.assertNotIn("errnoRet", by_name["finit_module"])
        for allowed in ("sched_setscheduler", "ioprio_set", "execve"):
            self.assertNotIn(allowed, by_name)

    def test_start_uses_the_profile_when_lepton_has_none(self):
        self.assertIn('[[ -f "$seccomp" ]] || seccomp="$(write_seccomp)"', SCRIPT)


if __name__ == "__main__":
    unittest.main()
