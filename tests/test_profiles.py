"""wgapps-profiles: notices a change to the file Android's Settings screen writes and has
`wgapps app import` take it over."""

import pathlib
import tempfile
import unittest

import helpers

profiles = helpers.load("wgapps-profiles")


class PollTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.share = pathlib.Path(tmp.name) / "device-profiles.conf"
        self.conf = pathlib.Path(tmp.name) / "apps.conf"
        self.imports = []
        self.import_result = True
        self.state = profiles.new_state()

    def runner(self, path):
        self.imports.append(path.read_bytes())
        return self.import_result

    def poll(self):
        self.state = profiles.poll(self.state, self.share, self.conf, self.runner)

    def test_nothing_happens_while_the_files_agree(self):
        self.share.write_text("a b=c\n")
        self.conf.write_text("a b=c\n")
        for _ in range(4):
            self.poll()
        self.assertEqual(self.imports, [])

    def test_two_missing_files_agree(self):
        for _ in range(4):
            self.poll()
        self.assertEqual(self.imports, [])

    def test_one_differing_poll_is_not_enough(self):
        # The host changes apps.conf a moment before it mirrors the change.
        self.conf.write_text("a b=new\n")
        self.share.write_text("a b=old\n")
        self.poll()
        self.share.write_text("a b=new\n")
        self.poll()
        self.assertEqual(self.imports, [])

    def test_two_differing_polls_import(self):
        self.conf.write_text("a b=old\n")
        self.share.write_text("a b=new\n")
        self.poll()
        self.poll()
        self.assertEqual(self.imports, [b"a b=new\n"])

    def test_an_emptied_share_file_is_imported_too(self):
        self.conf.write_text("a b=old\n")
        self.share.write_text("")
        self.poll()
        self.poll()
        self.assertEqual(self.imports, [b""])

    def test_a_missing_share_file_is_not_imported(self):
        # Android has not written one; the host's settings stand.
        self.conf.write_text("a b=old\n")
        for _ in range(4):
            self.poll()
        self.assertEqual(self.imports, [])

    def test_a_rejected_file_is_not_retried_until_it_changes(self):
        self.import_result = False
        self.conf.write_text("a b=old\n")
        self.share.write_text("garbage")
        for _ in range(6):
            self.poll()
        self.assertEqual(len(self.imports), 1)
        self.share.write_text("garbage2")
        self.poll()
        self.poll()
        self.assertEqual(len(self.imports), 2)

    def test_a_crashing_import_does_not_stop_the_loop(self):
        def boom(_path):
            raise OSError("no")

        self.conf.write_text("a b=old\n")
        self.share.write_text("a b=new\n")
        state = profiles.new_state()
        state = profiles.poll(state, self.share, self.conf, boom)
        state = profiles.poll(state, self.share, self.conf, boom)
        self.assertIsNotNone(state)

    def test_the_command_runs_the_launcher_with_import(self):
        command = profiles.import_command(pathlib.Path("/b/bin"), pathlib.Path("/s/f"))
        self.assertEqual(command, ["/b/bin/wgapps", "app", "import", "/s/f"])


if __name__ == "__main__":
    unittest.main()
