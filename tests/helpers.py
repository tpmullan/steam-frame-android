"""Load the extensionless scripts in bin/ as modules."""

import importlib.machinery
import importlib.util
import pathlib

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"


def load(name):
    path = BIN / name
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
