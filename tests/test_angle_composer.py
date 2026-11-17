"""Reproductions for docs/bugs/2026-11-15-angle-composer-crash.md.

With ANGLE as Android's GLES driver, the display's composer HAL crashed in ANGLE's
eglCreateImageKHR as soon as the pointer was used on the panel, and Android's display restarted.
Keeping the composer on Mesa's EGL fixed it, but three mistakes had to be found first. Each is
reproduced here so it cannot come back:

1. the crash signature (so a trial run names it instead of "unknown crash"),
2. patching only the vendor's rc, which loses to the `override` definitions of the service,
3. binding the same rc twice, which podman refuses ("duplicate mount destination").

The silent no-op of a preload file name with a hyphen is reproduced in
props-override/test_props_override.c; the name wgapps uses is checked in test_windows.py.
"""

import importlib.util
import pathlib
import re
import shutil
import sys
import tempfile
import unittest

from helpers import wgapps_call

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("gpu_trial", ROOT / "tools/gpu-trial.py")
trial = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = trial  # dataclasses (Python 3.12) look the module up by name
spec.loader.exec_module(trial)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
VENDOR = "vendor/etc/init/android.hardware.graphics.composer@2.1-service.rc"
WAYDROID = "system/etc/init/init.waydroid.rc"
OWN = "system/etc/init/z_wgapps.rc"
SERVICE = "vendor.hwcomposer-2-1"


class CrashSignatureTests(unittest.TestCase):
    def test_the_real_tombstone_is_named_as_the_known_composer_crash(self):
        text = (FIXTURES / "tombstone-composer-angle.txt").read_text()
        self.assertIn("composer-angle-createimage", trial.known_crash(text))

    def test_the_same_composer_crash_without_angle_is_not_that_bug(self):
        text = (FIXTURES / "tombstone-composer-angle.txt").read_text()
        self.assertIsNone(trial.known_crash(text.replace("libGLESv2_angle", "libGLESv2_mesa")))

    def test_an_app_crash_is_not_the_composer_bug(self):
        text = (FIXTURES / "tombstone-hello-xr-null-gl.txt").read_text()
        self.assertNotIn("composer", trial.known_crash(text))
        self.assertIsNone(trial.known_crash("Cmdline: com.example.app\nsignal 11"))


def effective_definition(files):
    """What Android's init uses for a service defined in several rc files, parsed in order.

    A later definition is ignored (an error) unless it says `override`, in which case it
    replaces the earlier one. This is the rule that made patching only the vendor's rc useless.
    """
    chosen = None
    for name, text in files:
        for block in re.split(r"(?m)^(?=service )", text):
            if not block.startswith(f"service {SERVICE} "):
                continue
            lines = [line.strip() for line in block.splitlines()[1:]]
            if chosen is None or "override" in lines:
                chosen = (name, lines)
    return chosen


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class ComposerReproductionTests(unittest.TestCase):
    """A rootfs like Waydroid's: three files define the composer service."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name) / "base"
        files = {
            f"rootfs/{VENDOR}": f"service {SERVICE} /vendor/bin/c\n    user system\n",
            f"rootfs/{WAYDROID}": (
                f"service {SERVICE} /vendor/bin/c --x\n    override\n    user host\n"
            ),
            f"overrides/{OWN}": f"service other /x\n    user root\n"
            f"service {SERVICE} /vendor/bin/c --x\n    override\n    user root\n",
        }
        for rel, text in files.items():
            path = self.base / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        (self.base / "lib").mkdir()
        (self.base / "lib/libwgapps_props.so").write_text("elf")
        (self.base / "run").mkdir()
        (self.base / "gpu-egl").write_text("angle\n")
        self.env = {"HOME": tmp.name, "WGAPPS_BASE": str(self.base)}

    def sources(self):
        """The rc files in the order init reads them: what the container shows Android."""
        return [
            (VENDOR, (self.base / "rootfs" / VENDOR).read_text()),
            (WAYDROID, (self.base / "rootfs" / WAYDROID).read_text()),
            (OWN, (self.base / "overrides" / OWN).read_text()),
        ]

    def as_android_sees(self):
        seen = []
        for rc, text in self.sources():
            patched = self.base / "run" / ("composer-" + rc.replace("/", "_"))
            seen.append((rc, patched.read_text() if patched.exists() else text))
        return seen

    def prepare(self):
        done = wgapps_call(self.env, "eval", "prepare_composer_egl; mount_composer_egl")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_unpatched_files_leave_the_composer_on_the_wrong_egl(self):
        # The reproduction: the definition init uses is the override in z_wgapps.rc, and it has
        # no preload, so the composer loads ANGLE and crashes.
        name, lines = effective_definition(self.sources())
        self.assertEqual(name, OWN)
        self.assertFalse(any(line.startswith("setenv LD_PRELOAD") for line in lines))

    def test_patching_only_the_vendor_rc_is_not_enough(self):
        # The first attempt: the vendor's rc got the lines, the override still won.
        patched = [
            (VENDOR, self.sources()[0][1] + "    setenv LD_PRELOAD /vendor/lib64/p.so\n"),
            *self.sources()[1:],
        ]
        name, lines = effective_definition(patched)
        self.assertEqual(name, OWN)
        self.assertFalse(any(line.startswith("setenv LD_PRELOAD") for line in lines))

    def test_after_the_fix_the_definition_init_uses_loads_the_preload(self):
        self.prepare()
        name, lines = effective_definition(self.as_android_sees())
        self.assertEqual(name, OWN)
        self.assertIn("setenv LD_PRELOAD /vendor/lib64/libwgapps_props.so", lines)
        self.assertIn("setenv WGP wgapps.composer", lines)

    def test_no_file_is_mounted_twice(self):
        # podman: "Error: /system/etc/init/z_wgapps.rc: duplicate mount destination". The
        # overrides loop of cmd_start (bind_overrides) binds each file under overrides/; the
        # composer mounts must not add the same destination again.
        script = (
            "prepare_composer_egl; bind_overrides; mount_composer_egl; "
            "printf '%s\\n' \"${ARGS[@]}\""
        )
        done = wgapps_call(self.env, "eval", script)
        self.assertEqual(done.returncode, 0, done.stderr)
        destinations = re.findall(r"destination=([^,]+)", done.stdout)
        self.assertIn("/" + OWN, destinations)
        self.assertEqual(len(destinations), len(set(destinations)), destinations)

    def test_mesa_changes_nothing_so_the_default_path_is_untouched(self):
        (self.base / "gpu-egl").write_text("mesa\n")
        self.prepare()
        self.assertEqual(list((self.base / "run").glob("composer-*")), [])
        self.assertFalse((self.base / "run/props.d/wgapps.composer").exists())


if __name__ == "__main__":
    unittest.main()
