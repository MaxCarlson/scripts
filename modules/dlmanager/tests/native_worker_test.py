# -*- coding: utf-8 -*-
import dlmanager.workers.native_worker as native_worker


def test_native_copy_transfers_files(tmp_path, monkeypatch):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    (src / "file1.txt").write_text("hello", encoding="utf-8")
    sub = src / "sub"
    sub.mkdir()
    (sub / "file2.txt").write_text("world", encoding="utf-8")

    emitted = []
    monkeypatch.setattr(native_worker, "emit", lambda **payload: emitted.append(payload))

    spec = {
        "id": "job-1",
        "src": str(src),
        "dst": str(dest),
        "dst_path": str(dest),
        "replace": True,
        "delete_source": False,
        "dry_run": False,
    }

    rc = native_worker.native_copy(spec)
    assert rc == 0
    assert (dest / "file1.txt").exists()
    assert (dest / "sub" / "file2.txt").exists()
    assert emitted[-1]["status"] == "completed"


def test_native_copy_dry_run_no_files_created(tmp_path, monkeypatch):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    (src / "file.txt").write_text("data", encoding="utf-8")

    emitted = []
    monkeypatch.setattr(native_worker, "emit", lambda **payload: emitted.append(payload))

    spec = {
        "id": "job-2",
        "src": str(src),
        "dst": str(dest),
        "dst_path": str(dest),
        "replace": False,
        "delete_source": False,
        "dry_run": True,
    }

    rc = native_worker.native_copy(spec)
    assert rc == 0
    assert not dest.exists()
    assert emitted[0]["status"] == "running"
