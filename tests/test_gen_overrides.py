import pathlib
import tempfile
import unittest

from helpers import load

gen = load("wgapps-gen-overrides")

MANIFEST = """<manifest version="1.0" type="device" target-level="5">
    <hal format="hidl">
        <name>android.hardware.audio</name>
        <transport>hwbinder</transport>
    </hal>
    <hal format="hidl">
        <name>android.hardware.media.omx</name>
        <transport>hwbinder</transport>
        <interface>
            <name>IOmxStore</name>
            <instance>default</instance>
        </interface>
    </hal>
    <hal format="hidl">
        <name>android.hardware.memtrack</name>
    </hal>
</manifest>
"""


class StripHalsTests(unittest.TestCase):
    def test_removes_only_the_omx_hal(self):
        out, removed = gen.strip_hals(MANIFEST)
        self.assertEqual(removed, ["android.hardware.media.omx"])
        self.assertNotIn("media.omx", out)
        self.assertNotIn("IOmxStore", out)
        self.assertIn("android.hardware.audio", out)
        self.assertIn("android.hardware.memtrack", out)
        self.assertEqual(out.count("<hal "), 2)

    def test_manifest_without_omx_is_unchanged(self):
        out, removed = gen.strip_hals(MANIFEST.replace("media.omx", "media.c2"))
        self.assertEqual(removed, [])
        self.assertEqual(out, MANIFEST.replace("media.omx", "media.c2"))


class PolicyTests(unittest.TestCase):
    def test_appends_missing_syscalls_once(self):
        base = "# Required by mesa3d\nkcmp: 1\nsched_getparam: 1\n"
        once = gen.extend_policy(base)
        self.assertTrue(once.startswith(base))
        for name in ("sched_setscheduler", "sched_getscheduler", "sched_setparam"):
            self.assertIn(f"{name}: 1\n", once)
        self.assertEqual(once.count("sched_getparam"), 1)
        self.assertEqual(gen.extend_policy(once), once)


class MainTests(unittest.TestCase):
    def test_writes_both_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = pathlib.Path(tmp, "root"), pathlib.Path(tmp, "out")
            (root / "vendor/etc/vintf").mkdir(parents=True)
            (root / gen.MANIFEST).write_text(MANIFEST)
            gen.main([str(root), str(out)])
            self.assertNotIn("media.omx", (out / gen.MANIFEST).read_text())
            self.assertIn("sched_setscheduler: 1", (out / gen.POLICY).read_text())


if __name__ == "__main__":
    unittest.main()
