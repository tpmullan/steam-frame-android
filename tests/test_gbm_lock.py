"""mount_gbm_lock in bin/wgapps: our lock (gbm-lock/) preloaded into Android's
graphics allocator service."""

import os
import pathlib
import shutil
import tempfile
import unittest

from helpers import wgapps_mounts

RC = "vendor/etc/init/android.hardware.graphics.allocator@4.0-service.minigbm_gbm_mesa.rc"
SERVICE = (
    "service vendor.graphics.allocator-4-0"
    " /vendor/bin/hw/android.hardware.graphics.allocator@4.0-service.minigbm_gbm_mesa\n"
)
REST = """    class hal animation
    user system
    disabled

on early-init && property:ro.hardware.gralloc=minigbm_gbm_mesa
    enable vendor.graphics.allocator-4-0
"""


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class MountGbmLockTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name) / "base"
        self.library = self.base / "lib/libwgapps_gbm_lock.so"
        self.rc = self.base / "rootfs" / RC
        for path, text in ((self.library, ""), (self.rc, "# License\n\n" + SERVICE + REST)):
            path.parent.mkdir(parents=True)
            path.write_text(text)

    def mounts(self):
        return wgapps_mounts(
            "mount_gbm_lock", {"HOME": str(self.base / "home"), "WGAPPS_BASE": str(self.base)}
        )

    def test_the_allocator_service_preloads_the_lock(self):
        mounts = self.mounts()
        self.assertEqual(set(mounts), {"/vendor/lib64/libwgapps_gbm_lock.so", "/" + RC})
        self.assertEqual(mounts["/vendor/lib64/libwgapps_gbm_lock.so"], (str(self.library), "ro"))
        source, options = mounts["/" + RC]
        self.assertEqual(options, "ro")
        self.assertEqual(os.stat(source).st_mode & 0o777, 0o644)
        self.assertEqual(
            pathlib.Path(source).read_text(),
            "# License\n\n"
            + SERVICE
            + "    setenv LD_PRELOAD /vendor/lib64/libwgapps_gbm_lock.so\n"
            + REST,
        )

    def test_no_preload_without_the_library(self):
        # The service cannot start with a preload that is not there.
        self.library.unlink()
        self.assertEqual(self.mounts(), {})

    def test_nothing_for_an_image_with_another_allocator(self):
        self.rc.unlink()
        self.assertEqual(self.mounts(), {})


if __name__ == "__main__":
    unittest.main()
