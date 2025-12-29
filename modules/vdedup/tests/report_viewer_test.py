import json
from pathlib import Path

import types

from vdedup import report_viewer


class _StubSystem:
    def __init__(self, *, win=False, mac=False, termux=False, wsl=False):
        self._win = win
        self._mac = mac
        self._termux = termux
        self._wsl = wsl

    def is_windows(self) -> bool:
        return self._win

    def is_darwin(self) -> bool:
        return self._mac

    def is_termux(self) -> bool:
        return self._termux

    def is_wsl2(self) -> bool:
        return self._wsl


def test_open_media_windows_uses_shell(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_text("x")
    invoked = {}

    def fake_startfile(path):
        invoked["path"] = path

    monkeypatch.setattr(report_viewer.os, "startfile", fake_startfile, raising=False)
    monkeypatch.setattr(report_viewer.shutil, "which", lambda _: None)
    monkeypatch.setattr(report_viewer, "SystemUtils", lambda: _StubSystem(win=True))
    assert report_viewer._open_media(clip)
    assert invoked["path"] == str(Path(clip).resolve())


def test_open_media_linux_prefers_xdg(monkeypatch, tmp_path):
    clip = tmp_path / "clip2.mp4"
    clip.write_text("x")
    invoked = []

    def fake_popen(cmd, **kwargs):
        invoked.append(cmd)
        return types.SimpleNamespace()

    monkeypatch.setattr(report_viewer, "SystemUtils", lambda: _StubSystem())
    monkeypatch.setattr(report_viewer.shutil, "which", lambda _: None)
    monkeypatch.setattr(report_viewer.subprocess, "Popen", fake_popen)
    assert report_viewer._open_media(clip)
    assert invoked[0][0] == "xdg-open"


def test_open_media_termux_falls_back(monkeypatch, tmp_path):
    clip = tmp_path / "clip3.mp4"
    clip.write_text("x")
    attempts = []

    def fake_popen(cmd, **kwargs):
        attempts.append(cmd[0])
        if cmd[0] == "termux-open":
            raise FileNotFoundError("missing")
        return types.SimpleNamespace()

    monkeypatch.setattr(report_viewer, "SystemUtils", lambda: _StubSystem(termux=True))
    monkeypatch.setattr(report_viewer.shutil, "which", lambda _: None)
    monkeypatch.setattr(report_viewer.subprocess, "Popen", fake_popen)
    assert report_viewer._open_media(clip)
    assert attempts == ["termux-open", "xdg-open"]


def test_launch_multi_preview_adds_master(monkeypatch, tmp_path):
    keep = tmp_path / "keep.mp4"
    dup = tmp_path / "dup.mp4"
    keep.write_text("k")
    dup.write_text("d")
    group = report_viewer.DuplicateGroup(
        group_id="g1",
        method="subset",
        keep=report_viewer.FileStats(path=keep, size=10, duration=40.0),
        losers=[report_viewer.FileStats(path=dup, size=5, duration=10.0)],
    )
    manager = report_viewer.DuplicateListManager([group])
    opened = []

    def fake_open(path, **kwargs):
        opened.append(str(path))
        return True

    monkeypatch.setattr(report_viewer, "_open_media", fake_open)
    row = report_viewer.DuplicateListRow(
        group_id="g1",
        method="subset",
        path=dup,
        depth=1,
        is_keep=False,
        size=5,
        size_delta=0,
        duplicate_count=1,
        reclaimable_bytes=5,
        parent_path="g1",
        keep_size=10,
        row_id="g1|dup",
    )
    report_viewer._launch_multi_preview([row], manager)
    assert str(keep) in opened
    assert str(dup) in opened


def test_promote_to_master_updates_report(tmp_path):
    keep = tmp_path / "keep.mp4"
    dup = tmp_path / "dup.mp4"
    keep.write_text("k")
    dup.write_text("d")
    data = {
        "groups": {
            "g1": {
                "method": "subset",
                "keep": str(keep),
                "losers": [str(dup)],
                "keep_meta": {"size": 10},
                "loser_meta": {str(dup): {"size": 5}},
            }
        }
    }
    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(data))
    docs = report_viewer.load_report_documents([report_file])
    manager = report_viewer.DuplicateListManager(docs[0].groups)
    assert manager.promote_to_master("g1", dup) is True
    saved = json.loads(report_file.read_text())
    assert saved["groups"]["g1"]["keep"] == str(dup)
    assert saved["groups"]["g1"]["losers"][0] == str(keep)


def test_launch_multi_preview_prefers_overlap_hint(monkeypatch, tmp_path):
    keep = tmp_path / "keep.mp4"
    dup = tmp_path / "dup.mp4"
    keep.write_text("A")
    dup.write_text("B")
    group = report_viewer.DuplicateGroup(
        group_id="g2",
        method="subset",
        keep=report_viewer.FileStats(path=keep, size=10, duration=40.0, overlap_hint=15.0),
        losers=[report_viewer.FileStats(path=dup, size=5, duration=10.0, overlap_hint=0.0)],
    )
    manager = report_viewer.DuplicateListManager([group])
    starts = []

    def fake_open(path, **kwargs):
        starts.append(kwargs.get("start"))
        return True

    monkeypatch.setattr(report_viewer, "_open_media", fake_open)
    rows = [
        report_viewer.DuplicateListRow(
            group_id="g2",
            method="subset",
            path=dup,
            depth=1,
            is_keep=False,
            size=5,
            size_delta=0,
            duplicate_count=1,
            reclaimable_bytes=5,
            parent_path="g2",
            keep_size=10,
            row_id="g2|dup",
        ),
        report_viewer.DuplicateListRow(
            group_id="g2",
            method="subset",
            path=keep,
            depth=0,
            is_keep=True,
            size=10,
            size_delta=0,
            duplicate_count=1,
            reclaimable_bytes=5,
            parent_path=None,
            keep_size=10,
            row_id="g2|keep",
        ),
    ]
    report_viewer._launch_multi_preview(rows, manager)
    assert starts[0] == 15.0  # master honored overlap hint
    assert starts[1] == 0.0   # loser starts at overlap origin
