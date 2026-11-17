"""The `podman run` argument list that `wgapps start` builds, captured with podman stubbed out.

The Rust launcher (`starforge-launcher start`) must build the same list; its golden file is the
output of this capture (see tests/fixtures/start-args.json and the engine repo's
runtime-rust/launcher/tests/start_args.json). Regenerate with WGAPPS_WRITE_FIXTURE=1.
"""

import json
import os
import pathlib
import socket
import subprocess
import tempfile
import unittest

from helpers import BIN

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures/start-args.json"

# Everything `cmd_start` does besides assembling the arguments is stubbed: preparing generated
# files, mounting optional extras, the helpers, and podman itself (it records its argument list).
STUBS = r"""
running() { return 1; }
export_profiles() { :; }
ensure_idmap() { :; }
generate_overrides() { :; }
generate_app_props() { :; }
write_props() { :; }
prepare_composer_egl() { :; }
bind_overrides() { :; }
mount_xr() { :; }
mount_gbm_lock() { :; }
mount_egl_layer() { :; }
mount_app_props() { :; }
mount_composer_egl() { :; }
mount_settings_app() { :; }
mount_shell_app() { :; }
mount_shares() { :; }
start_helpers() { :; }
write_seccomp() { echo "$RUNDIR/android.seccomp.json"; }
awk() { echo 192.0.2.53; }
podman() {
	case "$1" in
	run) shift; printf '%s\n' "$@" >"$CAPTURE" ;;
	esac
}
export -f podman 2>/dev/null || true
"""


# Device nodes that exist on some hosts and not on others (a Mac has no /dev/full, the Frame has
# /dev/dri): the golden files are compared without them, so a test run on any machine agrees.
HOST_DEPENDENT_DEVICES = {
    "/dev/dri/card0",
    "/dev/dri/renderD128",
    "/dev/full",
    "/dev/fuse",
    "/dev/shm",
    "/dev/snd",
    "/dev/uhid",
    "/dev/net/tun",
}


def without_host_devices(args):
    """The podman argument list minus the bind mounts of host-dependent device nodes."""
    kept, skip = [], False
    for index, arg in enumerate(args):
        if skip:
            skip = False
            continue
        following = args[index + 1] if index + 1 < len(args) else ""
        if arg == "--mount" and any(
            f"source={device},destination={device}," in following
            for device in HOST_DEPENDENT_DEVICES
        ):
            skip = True
            continue
        kept.append(arg)
    return kept


def without_host_devices_spec(text):
    spec = json.loads(text)
    spec["devices"] = [d for d in spec.get("devices", []) if d not in HOST_DEPENDENT_DEVICES]
    return json.dumps(spec)


# A run with optional pieces mounted (what the XR layer and the shell app do), via the real `bind`.
WITH_EXTRAS = r"""
mount_xr() { bind /dev/null /vendor/lib64/extra.so ro; }
mount_shell_app() { bind /dev/zero /system/priv-app/Shell/Shell.apk ro; }
"""


def capture_spec(headless=False, extra_env=None, extras=False):
    """The run specification `wgapps start` hands to the Rust launcher (WGAPPS_LAUNCHER set)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        stub = tmp / "launcher"
        # The stand-in launcher copies the specification it is given.
        stub.write_text(
            '#!/bin/sh\n[ "$1" = start ] && [ "$2" = --spec ] && cp "$3" "$CAPTURED_SPEC"\n'
        )
        stub.chmod(0o755)
        captured = tmp / "spec.json"
        text, _ = capture(
            headless,
            {"WGAPPS_LAUNCHER": str(stub), "CAPTURED_SPEC": str(captured), **(extra_env or {})},
            spec_file=captured,
            extras=extras,
        )
        return without_host_devices_spec(text) if text else text


def capture(headless=False, extra_env=None, spec_file=None, extras=False):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        base = tmp / "base"
        (base / "rootfs/system").mkdir(parents=True)
        (base / "run").mkdir()
        xdg = tmp / "xdg"
        (xdg / "pulse").mkdir(parents=True)
        sock = tmp / "wayland-1"
        server = socket.socket(socket.AF_UNIX)
        server.bind(str(sock))
        out = tmp / "args.txt"
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(tmp),
            "WGAPPS_BASE": str(base),
            "XDG_RUNTIME_DIR": str(xdg),
            "WGAPPS_WAYLAND_SOCKET": str(sock),
            "CAPTURE": str(out),
            **(extra_env or {}),
        }
        script = (
            f'source "{BIN / "wgapps"}"\n{STUBS}\n{WITH_EXTRAS if extras else ""}'
            f"cmd_start {'--headless' if headless else ''} >/dev/null 2>&1\n"
        )
        subprocess.run(["bash", "-c", script], env=env, check=False)
        server.close()
        if spec_file is not None:
            return (
                spec_file.read_text().replace(str(tmp), "<TMP>") if spec_file.exists() else ""
            ), {}
        args = without_host_devices(out.read_text().splitlines()) if out.exists() else []
        # Paths of this run's temporary directory become names the Rust side can reproduce.
        text = json.dumps(args).replace(str(tmp), "<TMP>")
        return json.loads(text), {
            "base": "<TMP>/base",
            "xdg": "<TMP>/xdg",
            "wayland": "<TMP>/wayland-1",
        }


class StartArgsTests(unittest.TestCase):
    def test_the_run_command_has_the_fixed_shape(self):
        args, _ = capture()
        self.assertEqual(args[:2], ["-d", "--replace"])
        self.assertIn("--cap-drop", args)
        self.assertEqual(args[args.index("--rootfs") + 1], "<TMP>/base/rootfs:O")
        self.assertEqual(args[-2:], ["/system/bin/init", "second_stage"])
        self.assertEqual(args.count("--cap-add"), 24)

    def test_headless_has_no_wayland_mount(self):
        windowed, _ = capture()
        headless, _ = capture(headless=True)
        wayland = "destination=/waydroid/xdg/wayland-0"
        self.assertTrue(any(wayland in a for a in windowed))
        self.assertFalse(any(wayland in a for a in headless))

    def test_with_the_launcher_the_spec_is_written_and_podman_is_not_run_by_bash(self):
        text = capture_spec()
        spec = json.loads(text)
        self.assertEqual(spec["name"], "waydroid-gapps")
        self.assertEqual(spec["rootfs"], "<TMP>/base/rootfs")
        self.assertEqual(spec["seccomp"], "<TMP>/base/run/android.seccomp.json")
        self.assertEqual(spec["wayland_socket"], "<TMP>/wayland-1")
        self.assertEqual(spec["cgroups"], "enabled")
        self.assertEqual(spec["extra_mounts"], [])
        self.assertIn("/dev/null", spec["devices"])
        self.assertIsNone(json.loads(capture_spec(headless=True))["wayland_socket"])
        self.assertEqual(
            json.loads(capture_spec(extra_env={"WGAPPS_CGROUPS": "0"}))["cgroups"], "disabled"
        )

    def test_optional_mounts_travel_in_the_spec_in_order(self):
        spec = json.loads(capture_spec(extras=True))
        self.assertEqual(
            spec["extra_mounts"],
            [
                "type=bind,source=/dev/null,destination=/vendor/lib64/extra.so,ro",
                "type=bind,source=/dev/zero,destination=/system/priv-app/Shell/Shell.apk,ro",
            ],
        )

    def test_the_spec_fixture_is_current(self):
        spec = {
            "windowed": json.loads(capture_spec()),
            "headless": json.loads(capture_spec(headless=True)),
            "extras": json.loads(capture_spec(extras=True)),
        }
        path = FIXTURE.with_name("start-spec.json")
        if os.environ.get("WGAPPS_WRITE_FIXTURE"):
            path.write_text(json.dumps(spec, indent=1) + "\n")
        self.assertEqual(
            json.loads(path.read_text()), spec, "regenerate with WGAPPS_WRITE_FIXTURE=1"
        )

    def test_the_fixture_is_current(self):
        args, inputs = capture()
        golden = {
            "inputs": inputs,
            "windowed": args,
            "headless": capture(headless=True)[0],
            "extras": capture(extras=True)[0],
        }
        if os.environ.get("WGAPPS_WRITE_FIXTURE"):
            FIXTURE.parent.mkdir(exist_ok=True)
            FIXTURE.write_text(json.dumps(golden, indent=1) + "\n")
        self.assertEqual(
            json.loads(FIXTURE.read_text()), golden, "regenerate with WGAPPS_WRITE_FIXTURE=1"
        )


if __name__ == "__main__":
    unittest.main()
