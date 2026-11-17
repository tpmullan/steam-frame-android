"""wgapps-share: the helper that gives files Android made in a shared folder to the user."""

import pathlib
import tempfile
import unittest

import helpers

share = helpers.load("wgapps-share")


class ShareHelperTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = pathlib.Path(tmp.name).resolve()
        self.base = self.home / "base"
        self.base.mkdir()
        (self.home / "Android-share").mkdir()

    def test_the_built_in_folder_is_always_looked_after_and_added_read_write_ones_too(self):
        work = self.home / "Work"
        work.mkdir()
        (self.base / "shares.conf").write_text(
            f"Work\t{work}\trw\nTunes\t{self.home}\tro\nGone\t{self.home / 'nothing'}\trw\n"
            f"Bad\t{self.home}\tsideways\nHost\t{self.home}\trw\n"
        )
        found = share.rw_shares(self.base, self.home)
        self.assertEqual(found, [(self.home / "Android-share", True), (work, False)])

    def test_the_command_owns_only_what_is_not_the_users(self):
        command = share.fix_command(pathlib.Path("/home/u/Android-share"))
        text = " ".join(command)
        self.assertIn("podman unshare find /home/u/Android-share -xdev ! -user 0", text)
        self.assertIn("-exec chown 0:1023 {} +", text)
        self.assertIn("-exec chmod ug+rwX {} +", text)
        self.assertEqual(command[:3], ["nice", "-n", "19"])

    def test_folders_are_looked_at_on_their_own_schedule(self):
        work = self.home / "Work"
        work.mkdir()
        (self.base / "shares.conf").write_text(f"Work\t{work}\trw\n")
        ran, last = [], {}
        run = ran.append
        first = share.run_once(self.base, self.home, last, 100.0, run)
        self.assertEqual(len(first), 2)
        self.assertEqual(share.run_once(self.base, self.home, last, 103.0, run), [])
        self.assertEqual(
            share.run_once(self.base, self.home, last, 106.0, run),
            [str(self.home / "Android-share")],
        )
        self.assertEqual(
            share.run_once(self.base, self.home, last, 170.0, run),
            [str(self.home / "Android-share"), str(work)],
        )


if __name__ == "__main__":
    unittest.main()
