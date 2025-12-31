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


class _StubListView:
    def __init__(self):
        self.state = types.SimpleNamespace(detail_selection=0)
        self.refresh_log = []

    def refresh_custom_detail(self, data):
        self.refresh_log.append(data)


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
        opened.append(
            {
                "path": str(path),
                "label": kwargs.get("label"),
                "slot": kwargs.get("slot"),
            }
        )
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
    assert any(entry["path"] == str(keep) for entry in opened)
    assert any(entry["path"] == str(dup) for entry in opened)
    master_entry = next(entry for entry in opened if entry["path"] == str(keep))
    assert "[MASTER]" in (master_entry["label"] or "")
    loser_entry = next(entry for entry in opened if entry["path"] == str(dup))
    assert "[LOSER]" in (loser_entry["label"] or "")


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


def test_detail_view_includes_overlap_provenance(tmp_path):
    keep = report_viewer.FileStats(path=tmp_path / "keep.mp4", size=100, duration=60.0)
    dup = report_viewer.FileStats(path=tmp_path / "dup.mp4", size=50, duration=30.0)
    evidence = {
        "detector": "subset-phash",
        "overlap_ratio": 0.5,
        "overlap_seconds": 12.5,
        "phash_distance": 3.2,
        "phash_step": 2,
        "phash_offset_frames": 4,
        "overlap_hints": {
            str(keep.path): 12.5,
            str(dup.path): 0.0,
        },
    }
    group = report_viewer.DuplicateGroup(
        group_id="g-meta",
        method="subset",
        keep=keep,
        losers=[dup],
        raw_payload={"evidence": evidence},
    )
    detail = report_viewer._build_detail_view_for_group(group)
    assert detail.entries[1].summary == "Overlap provenance"
    body_text = "\n".join(detail.entries[1].body)
    assert "subset-phash" in body_text
    assert "50.0%" in body_text
    assert "dup.mp4" in body_text


def test_selection_markers_follow_manager(tmp_path):
    keep = report_viewer.FileStats(path=tmp_path / "m.mp4", size=10)
    dup = report_viewer.FileStats(path=tmp_path / "n.mp4", size=5)
    manager = report_viewer.DuplicateListManager(
        [
            report_viewer.DuplicateGroup(group_id="gsel", method="hash", keep=keep, losers=[dup]),
        ]
    )
    manager.expand_all()
    rows = manager.visible_rows()
    assert all(not row.selected for row in rows)
    manager.set_selected([rows[0].row_id, rows[1].row_id])
    manager.apply_selection_markers(rows)
    assert all(row.selected for row in rows[:2])


def test_inline_preview_respects_overlap_hint_and_scrub(monkeypatch, tmp_path):
    keep = report_viewer.FileStats(path=tmp_path / "keep.mp4", size=10, duration=40.0, overlap_hint=18.0)
    dup = report_viewer.FileStats(path=tmp_path / "dup.mp4", size=9, duration=20.0, overlap_hint=0.0)
    group = report_viewer.DuplicateGroup(group_id="gprev", method="subset", keep=keep, losers=[dup])
    rows = [
        report_viewer.DuplicateListRow(
            group_id="gprev",
            method="subset",
            path=keep.path,
            depth=0,
            is_keep=True,
            size=keep.size,
            size_delta=0,
            duplicate_count=1,
            reclaimable_bytes=9,
            parent_path=None,
            keep_size=keep.size,
            display_name="keep",
            row_id="gprev|keep",
            overlap_hint=keep.overlap_hint,
        ),
        report_viewer.DuplicateListRow(
            group_id="gprev",
            method="subset",
            path=dup.path,
            depth=1,
            is_keep=False,
            size=dup.size,
            size_delta=dup.size - keep.size,
            duplicate_count=1,
            reclaimable_bytes=9,
            parent_path="gprev",
            keep_size=keep.size,
            display_name="dup",
            row_id="gprev|dup",
            overlap_hint=dup.overlap_hint,
        ),
    ]
    stub_list = _StubListView()
    monkeypatch.setattr(
        report_viewer,
        "_extract_ascii_frame",
        lambda path, timestamp, **kwargs: [f"{Path(path).name}@{timestamp:.1f}"],
    )
    session = report_viewer.InlinePreviewSession(group, rows, stub_list)
    assert session._timestamps[rows[0].path] == 18.0
    detail = session.build_detail_view()
    assert detail.title.startswith("Inline Preview")
    assert "link=OFF" in detail.footer
    stub_list.state.detail_selection = 1
    before = session._timestamps[rows[1].path]
    assert session.handle_key(ord(".")) is True
    assert session._timestamps[rows[1].path] == before + 1.0
    assert stub_list.refresh_log, "Scrub should refresh detail view"
    top_before = session._timestamps[rows[0].path]
    assert session.handle_key(ord("A")) is True
    assert session._timestamps[rows[0].path] == top_before + session._scrub_step
    assert session.handle_key(ord("L")) is True
    assert session._link_all is True
    link_detail = stub_list.refresh_log[-1]
    assert "link=ON" in link_detail.footer
    stub_list.state.detail_selection = 1
    keep_before = session._timestamps[rows[0].path]
    dup_before = session._timestamps[rows[1].path]
    assert session.handle_key(ord(",")) is True
    assert session._timestamps[rows[0].path] == keep_before - 1.0
    assert session._timestamps[rows[1].path] == dup_before - 1.0
