import pathlib
import tempfile
import unittest

from helpers import load

sc = load("steam-shortcuts.py")


class VdfTests(unittest.TestCase):
    def test_round_trip(self):
        shortcuts = {"0": sc.entry("Android", ""), "1": sc.entry("Plex", "com.plexapp.android")}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, "shortcuts.vdf")
            sc.save(path, shortcuts)
            back = sc.load(path)
        self.assertEqual(back["0"]["AppName"], "Android")
        self.assertEqual(back["1"]["LaunchOptions"], "steam com.plexapp.android")
        self.assertEqual(back["1"]["tags"], {"0": "Android"})
        self.assertEqual(back["1"]["appid"], shortcuts["1"]["appid"])

    def test_appid_has_top_bit_set_and_is_stable(self):
        a = sc.appid("/x/wgapps", "Plex")
        self.assertLess(a, 0)
        self.assertEqual(a, sc.appid("/x/wgapps", "Plex"))
        self.assertNotEqual(a, sc.appid("/x/wgapps", "Android"))


if __name__ == "__main__":
    unittest.main()
