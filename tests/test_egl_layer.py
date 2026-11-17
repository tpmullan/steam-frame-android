"""The GLES layer (egl-layer/) that answers EGL_BUFFER_AGE_EXT: mount and property."""

import pathlib
import shutil
import tempfile
import unittest

from helpers import wgapps_call, wgapps_mounts

DEST = "/data/local/debug/gles/libwgapps_egl_layer.so"
WRITE_PROPS = (
    'HOST_UID=1000; ADB_PORT=5555; RUNDIR="$BASE/run"; windows_mode() { echo single; };'
    " app_wrap_props() { :; }; gpu_egl() { echo mesa; };"
    ' write_props false; grep "^debug.gles" "$RUNDIR/waydroid.prop"'
)


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class EglLayerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name) / "base"
        self.library = self.base / "lib/libwgapps_egl_layer.so"
        self.library.parent.mkdir(parents=True)
        self.library.write_text("")
        (self.base / "run").mkdir()
        self.env = {"HOME": tmp.name, "WGAPPS_BASE": str(self.base)}

    def props(self, extra=None):
        return wgapps_call({**self.env, **(extra or {})}, "eval", WRITE_PROPS).stdout.strip()

    def test_the_library_is_mounted_where_libegl_looks_for_layers(self):
        mounts = wgapps_mounts("mount_egl_layer", self.env)
        self.assertEqual(mounts, {DEST: (str(self.library), "ro")})

    def test_the_property_names_the_layer(self):
        self.assertEqual(self.props(), "debug.gles.layers=libwgapps_egl_layer.so")

    def test_without_the_library_nothing_is_mounted_or_set(self):
        # A property naming a layer that is not there would only make libEGL log errors.
        self.library.unlink()
        self.assertEqual(wgapps_mounts("mount_egl_layer", self.env), {})
        self.assertEqual(self.props(), "")

    def test_it_can_be_turned_off(self):
        off = {"WGAPPS_EGL_LAYER": "0"}
        self.assertEqual(wgapps_mounts("mount_egl_layer", {**self.env, **off}), {})
        self.assertEqual(self.props(off), "")


if __name__ == "__main__":
    unittest.main()
