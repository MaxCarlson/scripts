from pathlib import Path
from ytaedl.orchestrator import CountsSnapshot, _is_snapshot_complete, _build_worklist, _Coordinator

def _mk_snap(tmp_path, names=("a","b")):
    files = {}
    for nm in names:
        uf = tmp_path / f"{nm}.txt"
        uf.write_text("http://example.com/1\nhttp://example.com/2\n", encoding="utf-8")
        files[str(uf.resolve())] = {
            "stem": nm,
            "source": "main",
            "out_dir": str((tmp_path/"out"/nm).resolve()),
            "url_count": 2,
            "downloaded": 0,
            "bad": 0,
            "remaining": 2,
            "viable_checked": True,
            "url_mtime": int(uf.stat().st_mtime),
            "url_size": int(uf.stat().st_size),
        }
    snap = CountsSnapshot()
    snap.files = files
    return snap

def test_is_snapshot_complete(tmp_path):
    snap = _mk_snap(tmp_path, names=("a","b","c"))
    assert _is_snapshot_complete(snap, tmp_path, tmp_path) is True
    # Touch a file to change mtime
    (tmp_path/"a.txt").write_text("changed\n", encoding="utf-8")
    assert _is_snapshot_complete(snap, tmp_path, tmp_path) is False

def test_build_worklist_and_coordinator(tmp_path):
    snap = _mk_snap(tmp_path, names=("x","y"))
    work = _build_worklist(snap, {"mp4"})
    # Remaining should be 2 for both
    assert all(w.remaining == 2 for w in work)
    coord = _Coordinator(work)
    first = coord.acquire_next()
    second = coord.acquire_next()
    assert first is not None and second is not None
    assert first.stem != second.stem
    # Release first with one completed
    coord.release(first, remaining_delta=-1)
    # Next acquire should pick the one with remaining=2 (second might still be assigned, so release it)
    coord.release(second, remaining_delta=0)
    nxt = coord.acquire_next()
    assert nxt is not None
