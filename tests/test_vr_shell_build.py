"""The VR shell's native and Java halves agree, and the APK declares what the scene needs."""

import pathlib
import re
import unittest

SHELL = pathlib.Path(__file__).resolve().parent.parent / "vr-shell"


class VrShellConsistencyTests(unittest.TestCase):
    def test_the_picture_java_draws_is_the_size_native_uploads(self):
        java = (SHELL / "src/dev/wgapps/shell/VrShellActivity.java").read_text()
        native = (SHELL / "native/shell.c").read_text()
        width = int(re.search(r"int WIDTH = (\d+);", java).group(1))
        height = int(re.search(r"int HEIGHT = (\d+);", java).group(1))
        self.assertEqual(width, int(re.search(r"#define GRID_W (\d+)", native).group(1)))
        self.assertEqual(height, int(re.search(r"#define GRID_H (\d+)", native).group(1)))

    def test_native_calls_the_java_method_that_exists_with_that_signature(self):
        java = (SHELL / "src/dev/wgapps/shell/VrShellActivity.java").read_text()
        native = (SHELL / "native/shell.c").read_text()
        self.assertIn('"gridPixels", "()[I"', native)
        self.assertIn("public static int[] gridPixels()", java)

    def test_rows_are_flipped_for_gl(self):
        # GL's texture origin is bottom-left; without this the shell is upside down (seen on the
        # Frame).
        self.assertIn("GRID_H - 1 - row", (SHELL / "native/shell.c").read_text())

    def test_the_manifest_declares_the_scene(self):
        manifest = (SHELL / "AndroidManifest.xml").read_text()
        self.assertIn('android:name=".VrShellActivity"', manifest)
        self.assertIn('android:value="wgshell"', manifest)  # lib_name of the native library
        self.assertIn("org.khronos.openxr.permission.OPENXR", manifest)
        self.assertIn('android:extractNativeLibs="false"', manifest)
        self.assertIn("org.khronos.openxr.intent.category.IMMERSIVE_HMD", manifest)

    def test_the_build_marks_a_native_build_for_wgapps_to_find(self):
        script = (SHELL.parent / "tools/build-shell.sh").read_text()
        self.assertIn('"$out/WgappsShell.vr"', script)
        self.assertIn("-p 4", script)  # stored libraries are page-aligned


if __name__ == "__main__":
    unittest.main()
