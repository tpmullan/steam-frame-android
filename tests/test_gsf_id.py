"""wgapps gsf-id: the GSF ID for google.com/android/uncertified, read with Android's own sqlite3."""

import pathlib
import shutil
import tempfile
import unittest

from helpers import wgapps_call

# asys is Android's shell through podman; the stand-in records the command and answers like sqlite3.
STUBS = (
    "running() { return 0; }\n"
    "image_flavor() { echo GAPPS; }\n"
    'asys() { printf "%s\\n" "$*" >"$CAPTURE"; printf "%s\\r\\n" "$ANSWER"; }\n'
)


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class GsfIdTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        self.capture = self.tmp / "command.txt"
        self.env = {
            "HOME": tmp.name,
            "WGAPPS_BASE": str(self.tmp / "base"),
            "CAPTURE": str(self.capture),
        }

    def call(self, answer):
        env = {**self.env, "ANSWER": answer}
        return wgapps_call(env, "eval", STUBS + "cmd_gsf_id")

    def test_sqlite3_gets_the_environment_android_init_normally_provides(self):
        done = self.call("3955133845382678474")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "3955133845382678474")
        command = self.capture.read_text()
        for variable in (
            "ANDROID_ROOT=/system",
            "ANDROID_DATA=/data",
            "ANDROID_I18N_ROOT=/apex/com.android.i18n",
            "ANDROID_TZDATA_ROOT=/apex/com.android.tzdata",
        ):
            self.assertIn(variable, command)
        self.assertIn("gservices.db", command)

    def test_an_answer_that_is_not_an_id_is_explained_instead_of_printed(self):
        for answer in ("", "Error: no such table"):
            done = self.call(answer)
            self.assertNotEqual(done.returncode, 0, answer)
            self.assertIn("no GSF ID yet", done.stderr)

    def test_a_vanilla_install_says_there_is_no_id(self):
        script = STUBS + "image_flavor() { echo VANILLA; }\ncmd_gsf_id"
        done = wgapps_call({**self.env, "ANSWER": "1"}, "eval", script)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no Google apps", done.stderr)


if __name__ == "__main__":
    unittest.main()
