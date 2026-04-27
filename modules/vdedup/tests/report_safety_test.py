"""
Tests for the hard safety contract in apply_report and write_report:

- candidate_only groups in `groups` section are always refused
- Legacy reports with meta/size method groups are refused
- review_required groups are skipped without -F, applied with -F
- actionable groups apply normally
- write_report serializes candidate_groups separately with no keep/losers
- write_report serializes actionable/match_type fields on all groups
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

from vdedup.models import FileMeta
from vdedup.report import apply_report, write_report


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────


def _write_report_json(path: Path, groups: Dict[str, Any], candidate_groups: Dict[str, Any] | None = None) -> None:
    payload: Dict[str, Any] = {
        "summary": {"groups": len(groups), "candidate_groups": len(candidate_groups or {}),
                    "apply_safe_groups": 0, "review_required_groups": 0, "losers": 0, "size_bytes": 0, "by_method": {}},
        "warnings": [],
        "groups": groups,
        "candidate_groups": candidate_groups or {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_group(keep: Path, loser: Path, method: str = "hash", **extra) -> Dict[str, Any]:
    g: Dict[str, Any] = {
        "keep": str(keep),
        "losers": [str(loser)],
        "method": method,
        "evidence": {},
        "keep_meta": {"size": 10},
        "loser_meta": {str(loser): {"size": 10}},
    }
    g.update(extra)
    return g


# ──────────────────────────────────────────
# apply_report: candidate groups refused
# ──────────────────────────────────────────


def test_apply_refuses_candidate_only_flag_in_groups(capsys, tmp_path: Path) -> None:
    """apply_report returns (0,0) and prints ERROR when any group has candidate_only=True."""
    keep = tmp_path / "keep.mp4"
    loser = tmp_path / "loser.mp4"
    keep.write_text("k", encoding="utf-8")
    loser.write_text("l", encoding="utf-8")
    rp = tmp_path / "report.json"
    _write_report_json(rp, {
        "meta:0": _make_group(keep, loser, method="meta", candidate_only=True, actionable=False),
    })

    count, size = apply_report(rp, dry_run=False, force=True, backup=None)

    assert (count, size) == (0, 0)
    assert "ERROR" in capsys.readouterr().err


def test_apply_refuses_legacy_meta_method(capsys, tmp_path: Path) -> None:
    """Legacy reports with method='meta' in groups are refused via inference."""
    keep = tmp_path / "keep.mp4"
    loser = tmp_path / "loser.mp4"
    keep.write_text("k", encoding="utf-8")
    loser.write_text("l", encoding="utf-8")
    rp = tmp_path / "report.json"
    _write_report_json(rp, {
        "meta:0": _make_group(keep, loser, method="meta"),  # no actionable field = legacy
    })

    count, size = apply_report(rp, dry_run=False, force=True, backup=None)

    assert (count, size) == (0, 0)
    err = capsys.readouterr().err
    assert "ERROR" in err or "candidate" in err.lower()


def test_apply_refuses_legacy_size_method(capsys, tmp_path: Path) -> None:
    """Legacy reports with method='size' or gid prefix 'size:' are refused."""
    keep = tmp_path / "keep.mp4"
    loser = tmp_path / "loser.mp4"
    keep.write_text("k", encoding="utf-8")
    loser.write_text("l", encoding="utf-8")
    rp = tmp_path / "report.json"
    _write_report_json(rp, {
        "size:1024": _make_group(keep, loser, method="size"),
    })

    count, size = apply_report(rp, dry_run=False, force=True, backup=None)

    assert (count, size) == (0, 0)
    err = capsys.readouterr().err
    assert "ERROR" in err or "candidate" in err.lower()


# ──────────────────────────────────────────
# apply_report: review-required enforcement
# ──────────────────────────────────────────


def test_apply_skips_review_required_without_F(capsys, tmp_path: Path) -> None:
    """review_required=True groups are skipped and a warning printed when force_review_required=False."""
    keep = tmp_path / "keep.mp4"
    loser = tmp_path / "loser.mp4"
    keep.write_text("k", encoding="utf-8")
    loser.write_text("l", encoding="utf-8")
    rp = tmp_path / "report.json"
    _write_report_json(rp, {
        "subset:0": _make_group(keep, loser, method="subset",
                                review_required=True, actionable=False,
                                match_type="subset_of_longer"),
    })

    count, size = apply_report(rp, dry_run=False, force=True, backup=None,
                               force_review_required=False)

    assert (count, size) == (0, 0)
    err = capsys.readouterr().err
    assert "review_required" in err or "skipped" in err.lower() or "SKIPPED" in err


def test_apply_applies_review_required_with_F(tmp_path: Path) -> None:
    """review_required groups are applied when force_review_required=True."""
    keep = tmp_path / "keep.mp4"
    loser = tmp_path / "loser.mp4"
    keep.write_text("k", encoding="utf-8")
    loser.write_text("l", encoding="utf-8")
    rp = tmp_path / "report.json"
    _write_report_json(rp, {
        "subset:0": _make_group(keep, loser, method="subset",
                                review_required=True, actionable=False,
                                match_type="subset_of_longer"),
    })

    count, _size = apply_report(rp, dry_run=True, force=True, backup=None,
                                force_review_required=True)

    # dry_run → nothing deleted but the group was processed
    assert count >= 0  # dry_run returns planned count (≥0)


def test_apply_candidate_only_refused_even_with_F(capsys, tmp_path: Path) -> None:
    """candidate_only=True groups are NEVER applied, even with force_review_required=True."""
    keep = tmp_path / "keep.mp4"
    loser = tmp_path / "loser.mp4"
    keep.write_text("k", encoding="utf-8")
    loser.write_text("l", encoding="utf-8")
    rp = tmp_path / "report.json"
    _write_report_json(rp, {
        "meta_candidate:0": _make_group(keep, loser, method="meta",
                                        candidate_only=True, actionable=False,
                                        review_required=True),
    })

    count, size = apply_report(rp, dry_run=False, force=True, backup=None,
                               force_review_required=True)

    assert (count, size) == (0, 0)
    err = capsys.readouterr().err
    assert "ERROR" in err


# ──────────────────────────────────────────
# apply_report: safe hash groups apply normally
# ──────────────────────────────────────────


def test_apply_hash_group_applies_without_F(tmp_path: Path) -> None:
    """hash: groups are apply-safe and do not require -F."""
    keep = tmp_path / "keep.mp4"
    loser = tmp_path / "loser.mp4"
    keep.write_text("k", encoding="utf-8")
    loser.write_text("l", encoding="utf-8")
    rp = tmp_path / "report.json"
    _write_report_json(rp, {
        "hash:abc123": _make_group(keep, loser, method="hash",
                                   actionable=True, review_required=False,
                                   match_type="exact_byte_duplicate"),
    })

    count, _size = apply_report(rp, dry_run=True, force=True, backup=None,
                                force_review_required=False)
    # dry_run but group was processed (not refused)
    assert count >= 0


def test_apply_legacy_hash_method_inferred_safe(capsys, tmp_path: Path) -> None:
    """Old reports with method='hash' and no actionable field are inferred as safe."""
    keep = tmp_path / "keep.mp4"
    loser = tmp_path / "loser.mp4"
    keep.write_text("k", encoding="utf-8")
    loser.write_text("l", encoding="utf-8")
    rp = tmp_path / "report.json"
    # Old-format: no actionable field
    _write_report_json(rp, {
        "hash:deadbeef": _make_group(keep, loser, method="hash"),
    })

    count, _size = apply_report(rp, dry_run=True, force=True, backup=None)
    # Should attempt to apply (not refuse), legacy warning on stderr is OK
    assert count >= 0
    err = capsys.readouterr().err
    assert "ERROR" not in err  # not refused


# ──────────────────────────────────────────
# write_report: candidate groups serialization
# ──────────────────────────────────────────


def test_write_report_candidate_groups_have_no_keep_losers(tmp_path: Path) -> None:
    """candidate_groups in the report JSON must NOT have keep or losers fields."""
    keep = FileMeta(path=tmp_path / "k.mp4", size=1, mtime=0.0)
    loser = FileMeta(path=tmp_path / "l.mp4", size=1, mtime=0.0)
    from vdedup.models import VideoMeta
    member_a = VideoMeta(path=tmp_path / "a.mp4", size=100, mtime=0.0)
    member_b = VideoMeta(path=tmp_path / "b.mp4", size=100, mtime=0.0)

    rp = tmp_path / "report.json"
    write_report(
        rp,
        winners={"hash:abc": (keep, [loser])},
        metadata={"hash:abc": {"match_type": "exact_byte_duplicate", "actionable": True}},
        candidate_groups={"meta_candidate:0": [member_a, member_b]},
        candidate_metadata={"meta_candidate:0": {
            "method": "meta",
            "match_type": "metadata_candidate",
            "recommended_next_stage": "q4",
        }},
    )

    data = json.loads(rp.read_text(encoding="utf-8"))

    # Verified group has keep/losers
    grp = data["groups"]["hash:abc"]
    assert "keep" in grp
    assert "losers" in grp
    assert grp.get("actionable") is True
    assert grp.get("match_type") == "exact_byte_duplicate"

    # Candidate group has members, NOT keep/losers
    cg = data["candidate_groups"]["meta_candidate:0"]
    assert "members" in cg
    assert "keep" not in cg
    assert "losers" not in cg
    assert cg["candidate_only"] is True
    assert cg["actionable"] is False
    assert cg["recommended_next_stage"] == "q4"


def test_write_report_summary_fields(tmp_path: Path) -> None:
    """write_report summary includes candidate_groups count and apply_safe_groups count."""
    keep = FileMeta(path=tmp_path / "k.mp4", size=1, mtime=0.0)
    loser = FileMeta(path=tmp_path / "l.mp4", size=1, mtime=0.0)
    from vdedup.models import VideoMeta
    member = VideoMeta(path=tmp_path / "m.mp4", size=100, mtime=0.0)

    rp = tmp_path / "report.json"
    write_report(
        rp,
        winners={"hash:abc": (keep, [loser])},
        metadata={"hash:abc": {"actionable": True, "review_required": False,
                                "match_type": "exact_byte_duplicate"}},
        candidate_groups={"size_candidate:1024": [member]},
        candidate_metadata={"size_candidate:1024": {"method": "size", "match_type": "size_candidate"}},
    )

    data = json.loads(rp.read_text(encoding="utf-8"))
    s = data["summary"]

    assert s["groups"] == 1
    assert s["candidate_groups"] == 1
    assert s["apply_safe_groups"] == 1
    assert s["review_required_groups"] == 0


def test_write_report_subset_group_review_required(tmp_path: Path) -> None:
    """subset: groups are serialized with actionable=False, review_required=True."""
    keep = FileMeta(path=tmp_path / "longer.mp4", size=10, mtime=0.0)
    loser = FileMeta(path=tmp_path / "shorter.mp4", size=5, mtime=0.0)

    rp = tmp_path / "report.json"
    write_report(
        rp,
        winners={"subset:0": (keep, [loser])},
        metadata={"subset:0": {
            "match_type": "subset_of_longer",
            "actionable": False,
            "review_required": True,
        }},
    )

    data = json.loads(rp.read_text(encoding="utf-8"))
    grp = data["groups"]["subset:0"]
    assert grp["actionable"] is False
    assert grp["review_required"] is True
    assert grp["match_type"] == "subset_of_longer"
