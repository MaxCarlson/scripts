# -*- coding: utf-8 -*-

import dlmanager.utils as utils
from dlmanager.utils import (
    normalize_path_for_remote,
    is_remote_spec,
    resolve_local_target,
    method_order_by_preference,
    is_local_transfer,
)

def test_normalize_cygwin_drive_backslash():
    p = "C:\\Users\\Max\\Downloads"
    out = normalize_path_for_remote(p, "windows-cygwin")
    assert out == "/cygdrive/c/Users/Max/Downloads"

def test_normalize_cygwin_drive_forwardslash():
    p = "D:/Data/Work"
    out = normalize_path_for_remote(p, "windows-cygwin")
    assert out == "/cygdrive/d/Data/Work"

def test_normalize_linux_nochange():
    p = "/home/max/data"
    out = normalize_path_for_remote(p, "linux")
    assert out == p

def test_auto_nochange():
    p = "relative/path"
    out = normalize_path_for_remote(p, "auto")
    assert out == p


def test_is_remote_spec_variants():
    assert is_remote_spec("user@host")
    assert is_remote_spec("remote:bucket")
    assert not is_remote_spec("C:\\Temp")
    assert not is_remote_spec("/tmp/foo")


def test_is_local_transfer_detection():
    spec = {"dst": r"C:\Backup"}
    assert is_local_transfer(spec)
    assert not is_local_transfer({"dst": "user@host"})


def test_resolve_local_target_prefers_dst_path(tmp_path):
    spec = {"dst": str(tmp_path / "base"), "dst_path": str(tmp_path / "target")}
    resolved = resolve_local_target(spec)
    assert resolved == (tmp_path / "target")


def test_method_order_prefers_native_for_local(monkeypatch):
    def fake_which(cmd: str):
        return {"rsync": None, "rclone": None, "scp": None, "native": "builtin"}.get(cmd, None)

    monkeypatch.setattr(utils, "which_or_none", fake_which)
    order = method_order_by_preference({"dst": "/data"})
    assert order[0] == "native"
    assert "native" in order


def test_method_order_remote_excludes_native(monkeypatch):
    monkeypatch.setattr(utils, "which_or_none", lambda cmd: "/bin/" + cmd)
    order = method_order_by_preference({"dst": "user@remote"})
    assert "native" in order[-1]
    assert order[0] == "rsync"
