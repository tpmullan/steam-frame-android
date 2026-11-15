"""Load the extensionless scripts in bin/ as modules."""

import importlib.machinery
import importlib.util
import pathlib
import sys

# CI runs Python 3.12. An older python3 (macOS ships 3.9 as /usr/bin/python3) fails with dozens of
# confusing errors, so say what is wrong once.
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
