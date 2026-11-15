"""mount_xr in bin/wgapps: the podman mounts and generated files that give
Android apps Steam's client libraries and SteamVR as their OpenXR runtime."""

import json
import os
import pathlib
import shutil
import tempfile
import unittest

from helpers import BIN, wgapps_mounts

ZYGOTE_RC = """service zygote /system/bin/app_process64 -Xzygote /system/bin --zygote
    class main
    user root

service zygote_secondary /system/bin/app_process32 -Xzygote /system/bin --zygote
    class main
    user root
"""


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class MountXrTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        self.base = self.tmp / "base"
        self.libs = self.tmp / "androidarm64"
        self.steamvr = self.tmp / "steamvr"
        self.write(self.base / "rootfs/system/etc/public.libraries.txt", "libandroid.so\nlibc.so\n")
        self.write(self.base / "rootfs/system/etc/init/hw/init.zygote64_32.rc", ZYGOTE_RC)
        for lib in ("libsteamclient.so", "libtier0_s.so"):
            self.write(self.libs / lib, "")
        self.write(self.steamvr / "runtime/bin/androidarm64/vrclient.so", "")
        (self.steamvr / "config").mkdir()

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def mounts(self, **extra):
        """Run mount_xr; return {destination: (source, options)}."""
        return wgapps_mounts(
            "mount_xr",
            {
                "HOME": str(self.tmp / "home"),
                "WGAPPS_BASE": str(self.base),
                "WGAPPS_STEAM_ANDROID_LIBS": str(self.libs),
                "WGAPPS_STEAMVR_RUNTIME": str(self.steamvr / "runtime"),
                "WGAPPS_STEAMVR_CONFIG": str(self.steamvr / "config"),
                **extra,
            },
        )

    def test_steam_libraries_are_mounted_and_made_public(self):
        mounts = self.mounts()
        self.assertEqual(
            mounts["/system/lib64/libsteamclient.so"],
            (str(self.libs / "libsteamclient.so"), "ro,U"),
        )
        self.assertIn("/system/lib64/libtier0_s.so", mounts)
        public = pathlib.Path(mounts["/system/etc/public.libraries.txt"][0]).read_text()
        self.assertEqual(
            public, "libandroid.so\nlibc.so\nlibsteamclient.so nopreload\nlibtier0_s.so nopreload\n"
        )

    def test_steamvr_is_the_active_openxr_runtime(self):
        mounts = self.mounts()
        self.assertEqual(mounts["/data/steamvr/runtime"], (str(self.steamvr / "runtime"), "rw"))
        self.assertEqual(mounts["/data/steamvr/config"], (str(self.steamvr / "config"), "ro"))
        manifest = json.loads(
            pathlib.Path(mounts["/vendor/etc/openxr/1/active_runtime.json"][0]).read_text()
        )
        self.assertEqual(
            manifest["runtime"]["library_path"],
            "/data/steamvr/runtime/bin/androidarm64/vrclient.so",
        )
        self.assertIs(manifest["runtime"]["VALVE_runtime_is_steamvr"], True)
        vrpath = json.loads(pathlib.Path(mounts["/vendor/etc/openvrpaths.vrpath"][0]).read_text())
        self.assertEqual(vrpath["runtime"], ["/data/steamvr/runtime"])
        self.assertEqual(vrpath["config"], ["/data/steamvr/config"])
        self.assertEqual(vrpath["log"], ["/data/steamvr/logs"])

    def test_every_app_can_write_its_steamvr_log(self):
        # vrclient refuses to start without a log file, and each app has its own
        # UID, none of them the host user's.
        source, options = self.mounts()["/data/steamvr/logs"]
        self.assertEqual(source, str(self.base / "steamvr-logs"))
        self.assertEqual(options, "rw")
        self.assertEqual(os.stat(source).st_mode & 0o7777, 0o1777)

    def test_gles_layer_is_an_implicit_openxr_layer(self):
        library = self.base / "lib/libwgapps_xr_gles.so"
        self.write(library, "")
        mounts = self.mounts()
        self.assertEqual(mounts["/data/steamvr/layers/libwgapps_xr_gles.so"], (str(library), "ro"))
        source, options = mounts["/vendor/etc/openxr/1/api_layers/implicit.d/wgapps_xr_gles.json"]
        self.assertEqual(options, "ro")
        layer = json.loads(pathlib.Path(source).read_text())["api_layer"]
        self.assertEqual(layer["library_path"], "/data/steamvr/layers/libwgapps_xr_gles.so")
        # The loader hands the layer this name and the layer refuses any other.
        self.assertIn(
            f'#define LAYER_NAME "{layer["name"]}"\n',
            (BIN.parent / "xr-layer/gles_layer.c").read_text(),
        )
        # Loaders skip an implicit layer that cannot be switched off.
        self.assertEqual(layer["disable_environment"], "WGAPPS_XR_NO_GLES_LAYER")

    def test_no_layer_manifest_without_the_layer(self):
        for destination in self.mounts():
            self.assertNotIn("layers", destination)

    def test_every_zygote_gets_the_steamvr_environment(self):
        source, options = self.mounts(SteamAppId="1234")["/system/etc/init/hw/init.zygote64_32.rc"]
        self.assertEqual(options, "ro")
        self.assertEqual(os.stat(source).st_mode & 0o777, 0o644)
        services = pathlib.Path(source).read_text().split("\n\n")
        self.assertEqual(len(services), 2)
        for service, original in zip(services, ZYGOTE_RC.split("\n\n"), strict=True):
            lines = service.rstrip("\n").split("\n")
            self.assertEqual(
                lines[1:6],
                [
                    "    setenv VR_PATHREG_OVERRIDE /vendor/etc/openvrpaths.vrpath",
                    "    setenv VR_CONFIG_PATH /data/steamvr/config",
                    "    setenv VR_LOG_PATH /data/steamvr/logs",
                    "    setenv Steam3Master 172.20.0.1:57343",
                    "    setenv SteamAppId 1234",
                ],
            )
            self.assertEqual(lines[:1] + lines[6:], original.rstrip("\n").split("\n"))

    def test_steam_app_id_is_left_out_when_steam_did_not_set_it(self):
        source = self.mounts()["/system/etc/init/hw/init.zygote64_32.rc"][0]
        self.assertNotIn("SteamAppId", pathlib.Path(source).read_text())

    def test_no_runtime_without_the_android_vrclient(self):
        (self.steamvr / "runtime/bin/androidarm64/vrclient.so").unlink()
        mounts = self.mounts()
        self.assertIn("/system/lib64/libsteamclient.so", mounts)
        for destination in mounts:
            self.assertFalse(
                destination.startswith(("/data/steamvr", "/vendor", "/system/etc/init")),
                destination,
            )

    def test_xr_can_be_disabled(self):
        self.assertEqual(self.mounts(WGAPPS_XR="0"), {})


if __name__ == "__main__":
    unittest.main()
