import importlib


def test_import_package():
    pkg = importlib.import_module("ytaedl")
    assert hasattr(pkg, "__version__")


def test_import_modules():
    dls = importlib.import_module("ytaedl.dlscript")
    dlm = importlib.import_module("ytaedl.dlmanager")
    assert hasattr(dls, "make_parser")
    assert hasattr(dlm, "make_parser")

