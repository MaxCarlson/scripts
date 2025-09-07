# file: tests/test_apply_report.py
from pathlib import Path
import json
import os
import video_dedupe as vd

def make_temp_files(tmp_path: Path):
    a = tmp_path / "A" / "keep1.mp4"
    b = tmp_path / "A" / "lose1.mp4"
    c = tmp_path / "B" / "lose2.mp4"
    a.parent.mkdir(parents=True, exist_ok=True)
    c.parent.mkdir(parents=True, exist_ok=True)
    a.write_bytes(b"x"*10)
    b.write_bytes(b"y"*20)
    c.write_bytes(b"z"*30)
    return a, b, c

def test_apply_report_dry_run(tmp_path: Path):
    a, b, c = make_temp_files(tmp_path)
    report = {
        "summary": {"groups": 1, "losers": 2, "size_bytes": 50},
        "groups": {
            "hash:deadbeef": {
                "keep": str(a),
                "losers": [str(b), str(c)]
            }
        }
    }
    rp = tmp_path / "report.json"
    rp.write_text(json.dumps(report), encoding="utf-8")

    # Dry run should not remove files; should return counts/sizes
    count, total = vd.apply_report(rp, dry_run=True, force=False, backup=None, base_root=None)
    assert count == 2
    assert total == b.stat().st_size + c.stat().st_size
    assert b.exists() and c.exists()

def test_apply_report_real_delete(tmp_path: Path):
    a, b, c = make_temp_files(tmp_path)
    rp = tmp_path / "report2.json"
    rp.write_text(json.dumps({
        "summary": {},
        "groups": {"g": {"keep": str(a), "losers": [str(b), str(c)]}}
    }), encoding="utf-8")

    count, total = vd.apply_report(rp, dry_run=False, force=True, backup=None, base_root=None)
    assert count == 2
    assert not b.exists() and not c.exists()
    # Total should be size of deleted files
    assert total > 0

def test_apply_report_backup_preserves_structure(tmp_path: Path):
    a, b, c = make_temp_files(tmp_path)
    rp = tmp_path / "report3.json"
    rp.write_text(json.dumps({
        "summary": {},
        "groups": {"g": {"keep": str(a), "losers": [str(b), str(c)]}}
    }), encoding="utf-8")

    backup = tmp_path / "Q"
    count, total = vd.apply_report(rp, dry_run=False, force=True, backup=backup, base_root=None)
    assert count == 2
    # Should move files into backup with same relative layout
    assert (backup / b.relative_to(tmp_path)).exists()
    assert (backup / c.relative_to(tmp_path)).exists()
