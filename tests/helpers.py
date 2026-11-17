"""Load the extensionless scripts in bin/ as modules; run functions of bin/wgapps."""

import importlib.machinery
import importlib.util
import pathlib
import subprocess
import sys

# CI runs Python 3.12. An older python3 (macOS ships 3.9 as /usr/bin/python3) fails with dozens of
# confusing errors (union types, tarfile filters), so say what is wrong once.
if sys.version_info < (3, 12):
    raise ImportError(f"these tests need Python 3.12 or newer; this is {sys.version.split()[0]}")

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"


def load(name):
    path = BIN / name
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# ${ARGS[@]+...}: an empty array counts as unset under `set -u` before bash 4.4.
MOUNTS_SCRIPT = 'source "$1"; ARGS=(); "$2"; printf "%s\\n" ${ARGS[@]+"${ARGS[@]}"}'


def wgapps_mounts(function, env):
    """Run a bin/wgapps function that adds podman bind mounts; return
    {destination: (source, options)}."""
    out = subprocess.run(
        ["bash", "-c", MOUNTS_SCRIPT, "bash", str(BIN / "wgapps"), function],
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", **env},
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    found = {}
    for flag, spec in zip(out[::2], out[1::2], strict=True):
        kind, source, destination, options = spec.split(",", 3)
        if (flag, kind) != ("--mount", "type=bind"):
            raise AssertionError(f"not a bind mount: {flag} {spec}")
        found[destination.removeprefix("destination=")] = (
            source.removeprefix("source="),
            options,
        )
    return found


def wgapps_call(env, function, *args):
    """Run a bin/wgapps function with arguments; return the finished process (not checked)."""
    return subprocess.run(
        ["bash", "-c", 'source "$1"; shift; "$@"', "bash", str(BIN / "wgapps"), function, *args],
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", **env},
        check=False,
        capture_output=True,
        text=True,
    )
