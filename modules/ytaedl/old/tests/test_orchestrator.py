# tests/test_orchestrator.py
from __future__ import annotations

from pathlib import Path

from ytaedl.orchestrator import (
    CountsSnapshot,
    _is_snapshot_complete,
    _build_worklist,
    _Coordinator,
)


def _mk_url_file(dirpath: Path, name: str, lines: str) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / name
    p.write_text(lines, encoding="utf-8")
    return p


def test_is_snapshot_complete(tmp_path: Path):
    """
    The snapshot is only 'complete' when completed+failed+already >= total_urls
    and there are no active/queued items.
    """
    # Make a tiny, consistent snapshot: 2 total URLs, none done yet.
    snap = CountsSnapshot(
        total_urls=2,
        completed=0,
        failed=0,
        already=0,
        active=0,
        queued=0,
        files={
            str(tmp_path / "a.txt"): {
                "url_file": str(tmp_path / "a.txt"),
                "stem": "a",
                "source": "main",
                "out_dir": str(tmp_path / "out" / "a"),
                "url_count": 2,
                "downloaded": 0,
                "bad": 0,
                "remaining": 2,
                "viable_checked": True,
                "url_mtime": int((tmp_path / "a.txt").stat().st_mtime)
                if (tmp_path / "a.txt").exists()
                else 0,
                "url_size": 42,
            }
        },
    )

    # Incomplete at first (0/2)
    assert _is_snapshot_complete(snap, tmp_path, tmp_path) is False

    # Now mark all done (2/2) -> complete
    snap.completed = 2
    assert _is_snapshot_complete(snap, tmp_path, tmp_path) is True

    # Or equivalent via 'already'
    snap.completed = 0
    snap.already = 2
    assert _is_snapshot_complete(snap, tmp_path, tmp_path) is True

    # If there are active or queued items, it's not complete
    snap.already = 2
    snap.active = 1
    assert _is_snapshot_complete(snap, tmp_path, tmp_path) is False
    snap.active = 0
    snap.queued = 1
    assert _is_snapshot_complete(snap, tmp_path, tmp_path) is False


def test_build_worklist_and_coordinator(tmp_path: Path):
    """
    Build a worklist from real URL files, then ensure the coordinator can
    acquire at least one work item when URLs exist.
    """
    main_url_dir = tmp_path / "main"
    ae_url_dir = tmp_path / "ae"
    out_root = tmp_path / "out"

    # Seed main and AE directories with at least one real URL each
    _mk_url_file(main_url_dir, "x.txt", "http://example.com/one\n")
    _mk_url_file(ae_url_dir, "y.txt", "http://aebn.com/movie#scene-2\n")

    work = _build_worklist(main_url_dir, ae_url_dir, out_root)
    coord = _Coordinator(work)

    wf = coord.acquire_next()
    assert wf is not None, "Coordinator should acquire a work item when URLs exist"

    # Simulate finishing one URL from this file, then release
    coord.release(wf, remaining_delta=-1)

    # If we drain remaining to zero, next acquire may legitimately return None.
    # We won't assert on that here; we just ensure basic wiring works.
