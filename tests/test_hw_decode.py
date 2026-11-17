"""Hardware video decode in bin/wgapps: when the V4L2 Codec2 service is installed and the host's
decoder node is usable, its files are mounted into Android and the service is declared to it."""

import os
import pathlib
import shutil
import tempfile
import unittest

from helpers import wgapps_call, wgapps_mounts

SERVICE = "vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2-64"
RC = "vendor/etc/init/android.hardware.media.c2@1.0-service-v4l2-64.rc"


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class HwDecodeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        self.base = self.tmp / "base"
        self.dir = self.base / "lib/v4l2-codec2"
        # A readable, writable character-looking node: a real device is needed only for -c, so the
        # tests point WGAPPS_V4L2_DECODER at /dev/null, which is one.
        self.env = {
            "HOME": tmp.name,
            "WGAPPS_BASE": str(self.base),
            "WGAPPS_V4L2_DECODER": "/dev/null",
        }

    def install(self, service=True, on=True):
        # The add-on is used only when it is turned on (wgapps hwdec on / install).
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "hwdec-enabled").write_text("on\n" if on else "off\n")
        for rel in (RC, "vendor/lib64/libv4l2_codec2_components.so", "vendor/lib64/libchrome.so"):
            path = self.dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")
        if service:
            path = self.dir / SERVICE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("#!/bin/sh\n")
            path.chmod(0o755)

    def call(self, script, **env):
        return wgapps_call({**self.env, **env}, "eval", script)

    def test_nothing_changes_without_the_installed_service(self):
        self.assertEqual(wgapps_mounts("mount_hw_decode", self.env), {})
        self.install(service=False)
        self.assertEqual(wgapps_mounts("mount_hw_decode", self.env), {})
        props = self.call("hw_decode_enabled && echo on || echo off")
        self.assertEqual(props.stdout.strip(), "off")

    def test_an_installed_decoder_that_is_turned_off_is_not_used(self):
        self.install(on=False)
        self.assertEqual(wgapps_mounts("mount_hw_decode", self.env), {})
        self.assertEqual(
            self.call("hw_decode_enabled && echo on || echo off").stdout.strip(), "off"
        )
        (self.base / "hwdec-enabled").unlink()  # no file means off too
        self.assertEqual(wgapps_mounts("mount_hw_decode", self.env), {})

    def test_nothing_changes_without_a_usable_decoder_node(self):
        self.install()
        env = {**self.env, "WGAPPS_V4L2_DECODER": str(self.tmp / "missing")}
        self.assertEqual(wgapps_mounts("mount_hw_decode", env), {})
        done = wgapps_call(env, "eval", "mount_hw_decode; echo node=[$HW_DECODE_NODE]")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("node=[]", done.stdout)
        self.assertIn("no usable V4L2 decoder node", done.stderr)

    def test_the_built_files_are_mounted_read_only_over_vendor(self):
        self.install()
        mounts = wgapps_mounts("mount_hw_decode", self.env)
        self.assertEqual(mounts["/" + SERVICE], (str(self.dir / SERVICE), "ro"))
        self.assertEqual(
            mounts["/vendor/lib64/libv4l2_codec2_components.so"],
            (str(self.dir / "vendor/lib64/libv4l2_codec2_components.so"), "ro"),
        )
        self.assertIn("/vendor/lib64/libchrome.so", mounts)

    def test_the_decoder_is_visible_as_one_of_the_nodes_the_service_probes(self):
        # V4L2Device probes /dev/video and /dev/video0..15 only; the host's decoder is video22.
        self.install()
        self.assertEqual(
            wgapps_mounts("mount_hw_decode", self.env)["/dev/video0"], ("/dev/null", "rw")
        )

    def test_the_service_is_declared_with_our_own_init_file_manifest_and_codec_list(self):
        self.install()
        mounts = wgapps_mounts("mount_hw_decode", self.env)
        run = self.base / "run"
        # The build's own init file (user media) is replaced, not mounted.
        self.assertEqual(mounts["/" + RC], (str(run / "hwdec.rc"), "ro"))
        self.assertEqual(
            mounts["/vendor/etc/vintf/manifest/android.hardware.media.c2.v4l2.xml"][0],
            str(run / "hwdec-manifest.xml"),
        )
        self.assertEqual(
            mounts["/vendor/etc/media_codecs_c2.xml"][0], str(run / "media_codecs_c2.xml")
        )
        rc = (run / "hwdec.rc").read_text()
        self.assertIn("user root", rc)
        self.assertIn("/" + SERVICE, rc)
        self.assertNotIn("user media", rc)
        manifest = (run / "hwdec-manifest.xml").read_text()
        for text in ("android.hardware.media.c2", "IComponentStore", "default", "hwbinder"):
            self.assertIn(text, manifest)
        codecs = (run / "media_codecs_c2.xml").read_text()
        for name in ("c2.v4l2.avc.decoder", "c2.v4l2.hevc.decoder", "c2.v4l2.vp9.decoder"):
            self.assertIn(name, codecs)
        self.assertIn("4096x4096", codecs)

    def test_the_client_side_plugin_store_is_mounted_into_the_system_image(self):
        self.install()
        client = self.dir / "system/lib64/libc2plugin_store.so"
        client.parent.mkdir(parents=True)
        client.write_text("x")
        mounts = wgapps_mounts("mount_hw_decode", self.env)
        self.assertEqual(mounts["/system/lib64/libc2plugin_store.so"], (str(client), "ro"))

    def test_the_extension_policy_allows_the_calls_the_v4l2_code_needs(self):
        self.install()
        mounts = wgapps_mounts("mount_hw_decode", self.env)
        source, options = mounts["/vendor/etc/seccomp_policy/codec2.vendor.ext.policy"]
        self.assertEqual(options, "ro")
        lines = pathlib.Path(source).read_text().splitlines()
        allowed = {line.split(":")[0] for line in lines if line and not line.startswith("#")}
        self.assertTrue({"eventfd2", "fcntl", "epoll_pwait", "clock_nanosleep"} <= allowed)
        for line in lines:
            if line and not line.startswith("#"):
                self.assertRegex(line, r"^[a-z0-9_]+: 1$")

    def test_the_node_is_passed_into_the_container(self):
        self.install()
        done = self.call("mount_hw_decode; echo node=$HW_DECODE_NODE")
        self.assertEqual(done.stdout.strip(), "node=/dev/null")
        text = (pathlib.Path(__file__).resolve().parent.parent / "bin/wgapps").read_text()
        self.assertIn('devices+=("$HW_DECODE_NODE")', text)

    def test_properties_enable_the_v4l2_buffer_pools_only_with_the_service(self):
        script = (
            'HOST_UID=1000; ADB_PORT=5555; RUNDIR="$BASE/run"; windows_mode() { echo single; };'
            " app_wrap_props() { :; }; gpu_egl() { echo mesa; };"
            ' write_props false; grep -E "c2-poolmask|v4l2_codec2" "$RUNDIR/waydroid.prop"'
        )
        before = self.call(script).stdout.split()
        self.assertEqual(before, ["debug.stagefright.c2-poolmask=851968"])
        self.install()
        after = self.call(script).stdout.split()
        mask = (1 << 16) | (1 << 18) | (1 << 19) | (1 << 20) | (1 << 21)
        self.assertIn(
            f"debug.stagefright.c2-poolmask={mask}",
            after,
        )
        self.assertIn("ro.vendor.v4l2_codec2.decode_concurrent_instances=8", after)
        self.assertIn("ro.vendor.v4l2_codec2.min_input_buffer_size=17694720", after)

    def test_node_check_needs_a_character_device_the_user_can_use(self):
        regular = self.tmp / "regular"
        regular.write_text("")
        self.assertNotEqual(
            self.call("hw_decode_node", WGAPPS_V4L2_DECODER=str(regular)).stdout.strip(),
            str(regular),
        )
        self.assertEqual(os.stat("/dev/null").st_mode & 0o020000, 0o020000)
        self.assertEqual(self.call("hw_decode_node").stdout.strip(), "/dev/null")


if __name__ == "__main__":
    unittest.main()
