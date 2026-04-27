import json
import tempfile
from pathlib import Path

from vdedup import report


def _write_report(path: Path, keep: Path, losers: list[Path]) -> None:
    payload = {
        "summary": {"groups": 1, "losers": len(losers), "size_bytes": 0, "by_method": {"hash": 1}},
        "groups": {
            "hash:abc": {
                "keep": str(keep),
                "losers": [str(loser) for loser in losers],
                "method": "hash",
                "evidence": {"sha256": "abc"},
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_apply_report_dry_run_prints_folder_priority_move(capsys, monkeypatch) -> None:
    tmp_dir = tempfile.TemporaryDirectory()
    tmp_path = Path(tmp_dir.name)
    keep = tmp_path / "outside" / "keep.mp4"
    loser = tmp_path / "priority" / "nested" / "lose.mp4"
    keep.parent.mkdir()
    loser.parent.mkdir(parents=True)
    keep.write_text("keep", encoding="utf-8")
    loser.write_text("lose", encoding="utf-8")
    report_path = tmp_path / "report.json"
    _write_report(report_path, keep, [loser])

    monkeypatch.setattr(report.os, "isatty", lambda fd: True)
    monkeypatch.delenv("NO_COLOR", raising=False)

    report.apply_report(
        report_path,
        dry_run=True,
        force=False,
        backup=None,
        folder_priority=tmp_path / "priority",
        verbosity=1,
        full_file_names=True,
    )

    out = capsys.readouterr().out
    assert "\x1b[94m[DRY] MOVING TO\x1b[0m" in out
    assert "keep.mp4 ->" in out
    assert "priority" in out
    assert "keeps moved       : 1 (dry-run planned)" in out
    tmp_dir.cleanup()


def test_apply_report_dry_run_does_not_move_when_keep_is_in_priority(capsys) -> None:
    tmp_dir = tempfile.TemporaryDirectory()
    tmp_path = Path(tmp_dir.name)
    keep = tmp_path / "priority" / "keep.mp4"
    loser = tmp_path / "outside" / "lose.mp4"
    keep.parent.mkdir()
    loser.parent.mkdir()
    keep.write_text("keep", encoding="utf-8")
    loser.write_text("lose", encoding="utf-8")
    report_path = tmp_path / "report.json"
    _write_report(report_path, keep, [loser])

    report.apply_report(
        report_path,
        dry_run=True,
        force=False,
        backup=None,
        folder_priority=tmp_path / "priority",
        verbosity=1,
        full_file_names=True,
    )

    out = capsys.readouterr().out
    assert "[DRY] MOVING TO" not in out
    assert "keeps moved       : 0" in out
    tmp_dir.cleanup()


def test_apply_report_live_moves_keep_to_priority_folder_and_deletes_loser() -> None:
    tmp_dir = tempfile.TemporaryDirectory()
    tmp_path = Path(tmp_dir.name)
    keep = tmp_path / "outside" / "keep.mp4"
    loser = tmp_path / "priority" / "nested" / "lose.mp4"
    keep.parent.mkdir()
    loser.parent.mkdir(parents=True)
    keep.write_text("keep", encoding="utf-8")
    loser.write_text("lose", encoding="utf-8")
    report_path = tmp_path / "report.json"
    _write_report(report_path, keep, [loser])

    count, _ = report.apply_report(
        report_path,
        dry_run=False,
        force=True,
        backup=None,
        folder_priority=tmp_path / "priority",
        verbosity=-1,
        full_file_names=True,
    )

    moved = tmp_path / "priority" / "nested" / "keep.mp4"
    assert count == 1
    assert moved.read_text(encoding="utf-8") == "keep"
    assert not keep.exists()
    assert not loser.exists()
    tmp_dir.cleanup()


def test_apply_report_folder_priority_avoids_destination_collision() -> None:
    tmp_dir = tempfile.TemporaryDirectory()
    tmp_path = Path(tmp_dir.name)
    keep = tmp_path / "outside" / "keep.mp4"
    existing = tmp_path / "priority" / "nested" / "keep.mp4"
    loser = tmp_path / "priority" / "nested" / "lose.mp4"
    keep.parent.mkdir()
    loser.parent.mkdir(parents=True)
    keep.write_text("keep", encoding="utf-8")
    existing.write_text("existing", encoding="utf-8")
    loser.write_text("lose", encoding="utf-8")
    report_path = tmp_path / "report.json"
    _write_report(report_path, keep, [loser])

    report.apply_report(
        report_path,
        dry_run=False,
        force=True,
        backup=None,
        folder_priority=tmp_path / "priority",
        verbosity=-1,
        full_file_names=True,
    )

    moved = tmp_path / "priority" / "nested" / "keep.1.mp4"
    assert existing.read_text(encoding="utf-8") == "existing"
    assert moved.read_text(encoding="utf-8") == "keep"
    assert not keep.exists()
    assert not loser.exists()
    tmp_dir.cleanup()


def test_apply_report_folder_priority_replaces_same_name_loser_before_keep_move() -> None:
    tmp_dir = tempfile.TemporaryDirectory()
    tmp_path = Path(tmp_dir.name)
    keep = tmp_path / "outside" / "keep.mp4"
    loser = tmp_path / "priority" / "nested" / "keep.mp4"
    keep.parent.mkdir()
    loser.parent.mkdir(parents=True)
    keep.write_text("keep", encoding="utf-8")
    loser.write_text("lose", encoding="utf-8")
    report_path = tmp_path / "report.json"
    _write_report(report_path, keep, [loser])

    count, _ = report.apply_report(
        report_path,
        dry_run=False,
        force=True,
        backup=None,
        folder_priority=tmp_path / "priority",
        verbosity=-1,
        full_file_names=True,
    )

    moved = tmp_path / "priority" / "nested" / "keep.mp4"
    assert count == 1
    assert moved.read_text(encoding="utf-8") == "keep"
    assert not keep.exists()
    assert not (tmp_path / "priority" / "nested" / "keep.1.mp4").exists()
    tmp_dir.cleanup()
