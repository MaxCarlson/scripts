from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from mangadl.cli import build_parser, main
from mangadl.library_guard import library_write_guard


def test_repair_manager_reentrancy_and_competing_thread(tmp_path):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    with library_write_guard(tmp_path):
        with library_write_guard(gallery):
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(_acquire, gallery)
                with pytest.raises(RuntimeError, match="locked"):
                    future.result()
    _acquire(gallery)


def _acquire(destination):
    with library_write_guard(destination):
        pass


def test_other_process_blocks_download_and_compression_then_releases(tmp_path, monkeypatch):
    from mangadl import cli_core

    child = subprocess.Popen(
        [sys.executable, "-u", "-c",
         "import sys; from pathlib import Path; from mangadl.library_guard import library_write_guard; "
         "\nwith library_write_guard(Path(sys.argv[1])):\n print('owned', flush=True); sys.stdin.read()",
         str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert child.stdout.readline().strip() == "owned"
        args = build_parser().parse_args(["run", "-d", str(tmp_path), "-u", "https://nhentai.net/g/1/", "-N"])
        monkeypatch.setattr(cli_core, "_run_owned", lambda args: 42)
        with pytest.raises(RuntimeError, match="locked"):
            cli_core._run(args)
        assert main(["compress", "apply", "-d", str(tmp_path), "-w", "-N"]) == 2
        # Dry-run bypasses ownership, and cannot launch a writer here.
        args.dry_run = True
        assert cli_core._run(args) == 42
    finally:
        child.kill()
        child.communicate(timeout=10)
    # Persistent inode survives; OS ownership does not survive process death.
    assert (tmp_path / ".mangadl" / "operation.lock").exists()
    _acquire(tmp_path)


def test_analysis_does_not_create_library_controls(tmp_path, capsys):
    from PIL import Image

    Image.new("RGB", (40, 40)).save(tmp_path / "001.png")
    assert main(["compress", "analyze", "-d", str(tmp_path), "-J", "-N"]) == 0
    assert not (tmp_path / ".mangadl").exists()


def test_invalid_write_destination_is_not_created(tmp_path):
    destination = tmp_path / "missing"
    assert main(["compress", "apply", "-d", str(destination), "-w", "-N"]) == 2
    assert not destination.exists()


def test_mangadl_lock_status_and_unlock_cli(tmp_path, capsys, monkeypatch):
    import json
    import sqlite3
    from mangadl.library_guard import library_read_guard, library_write_guard

    monkeypatch.setenv("CROSS_PLATFORM_LOCK_DIR", str(tmp_path / "ext_locks"))
    folder_a = tmp_path / "tmphent3"
    folder_b = tmp_path / "hent1image"
    folder_a.mkdir()
    folder_b.mkdir()

    # 1. Idle folder status
    assert main(["lock", "-s", "-d", str(folder_a), "-j"]) == 0
    idle_data = json.loads(capsys.readouterr().out)
    assert idle_data["engaged"] is False
    assert idle_data["write_locked"] is False
    assert idle_data["read_locked"] is False

    # 2. Active read lock on folder_a does not touch folder_a or lock folder_b
    with library_read_guard(folder_a, operation="mangadl compress -l -D headers"):
        assert list(folder_a.iterdir()) == []
        assert main(["lock", "-s", "-d", str(folder_a), "-j"]) == 0
        read_data = json.loads(capsys.readouterr().out)
        assert read_data["engaged"] is True
        assert read_data["read_locked"] is True
        assert read_data["write_locked"] is False
        assert any(lk["operation"] == "mangadl compress -l -D headers" for lk in read_data["locks"])

        assert main(["lock", "-s", "-d", str(folder_b), "-j"]) == 0
        b_data = json.loads(capsys.readouterr().out)
        assert b_data["engaged"] is False

    # 3. Stale repair.lock and running state row require explicit -u/--unlock
    controls = folder_a / ".mangadl"
    controls.mkdir(parents=True, exist_ok=True)
    repair_lock = controls / "repair.lock"
    repair_lock.write_text("stale-token", encoding="utf-8")
    state_db = controls / "state.sqlite3"
    with sqlite3.connect(state_db) as conn:
        conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, started TEXT, finished TEXT, status TEXT)")
        conn.execute("INSERT INTO runs VALUES ('run-99', '2026-10-16T00:00:00Z', NULL, 'running')")
        conn.commit()

    assert main(["lock", "-s", "-d", str(folder_a), "-j"]) == 0
    stale_status = json.loads(capsys.readouterr().out)
    assert stale_status["engaged"] is False
    assert stale_status["stale_count"] == 2
    assert repair_lock.exists()

    assert main(["lock", "-u", "-d", str(folder_a), "-j"]) == 0
    unlocked_res = json.loads(capsys.readouterr().out)
    assert len(unlocked_res["unlocked"]) == 2
    assert unlocked_res["refused_active"] == []
    assert not repair_lock.exists()

    # 4. Active write lock refuses -u/--unlock
    with library_write_guard(folder_a, operation="mangadl run"):
        assert main(["lock", "-u", "-d", str(folder_a), "-j"]) == 1
        refused = json.loads(capsys.readouterr().out)
        assert len(refused["refused_active"]) >= 1

