from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import pytest

from agent_benchmark.cli import main, parser
from agent_benchmark.suite_archive import (
    ArchiveError,
    reconcile_tasks,
    safe_origin,
    sqlite_inspect,
    sqlite_online_backup,
)


def _create_synthetic_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("""
            CREATE TABLE inference_requests (
                request_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                recording_mode TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE inference_contents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL REFERENCES inference_requests(request_id),
                sequence INTEGER,
                kind TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT,
                content_type TEXT NOT NULL DEFAULT 'text/plain',
                source TEXT,
                truncated INTEGER NOT NULL DEFAULT 0,
                observed_at TEXT
            );
        """)
        conn.execute("""
            CREATE TABLE inference_hardware_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL REFERENCES inference_requests(request_id),
                device_id TEXT,
                power_watts REAL
            );
        """)
        # Populate completed requests
        conn.execute("INSERT INTO inference_requests VALUES ('req-1', 'completed', 'content')")
        conn.execute("INSERT INTO inference_requests VALUES ('req-2', 'completed', 'content')")
        conn.execute("INSERT INTO inference_contents (request_id, kind, role, text, truncated) VALUES ('req-1', 'user', 'user', 'hello', 0)")
        conn.execute("INSERT INTO inference_contents (request_id, kind, role, text, truncated) VALUES ('req-1', 'assistant', 'assistant', 'world', 0)")
        conn.execute("INSERT INTO inference_contents (request_id, kind, role, text, truncated) VALUES ('req-2', 'assistant', 'assistant', 'done', 0)")
        conn.execute("INSERT INTO inference_hardware_samples (request_id, device_id, power_watts) VALUES ('req-1', 'gpu-0', 250.0)")
        conn.commit()


def test_safe_origin():
    assert safe_origin("http://127.0.0.1:8789") == "http://127.0.0.1:8789"
    assert safe_origin("http://localhost:8789") == "http://localhost:8789"
    assert safe_origin("http://host.docker.internal:8789/v1") == "http://host.docker.internal:8789"

    with pytest.raises(ArchiveError, match="Monitor API origin must be a local HTTP"):
        safe_origin("http://example.com:8789")

    with pytest.raises(ArchiveError, match="Monitor API origin must be a local HTTP"):
        safe_origin("http://user:pass@127.0.0.1:8789")


def test_sqlite_online_backup_and_inspect(tmp_path: Path):
    src_db = tmp_path / "source.sqlite3"
    _create_synthetic_database(src_db)

    dst_db = tmp_path / "backup.sqlite3"
    sqlite_online_backup(src_db, dst_db)
    assert dst_db.is_file()

    info = sqlite_inspect(dst_db)
    assert info["integrity_ok"] is True
    assert info["foreign_key_violations"] == 0
    assert info["table_counts"]["inference_requests"] == 2
    assert info["table_counts"]["inference_contents"] == 3
    assert info["table_counts"]["inference_hardware_samples"] == 1
    assert info["recording_modes"] == {"content": 2}
    assert info["request_states"] == {"completed": 2}
    assert info["truncated_content_segments"] == 0

    with pytest.raises(ArchiveError, match="Refusing to overwrite"):
        sqlite_online_backup(src_db, dst_db)


def test_reconcile_tasks_coverage_and_gaps(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    _create_synthetic_database(db_path)

    checkpoint = {
        "tasks": [
            {
                "task_id": "task-a",
                "status": "passed",
                "monitor_request_ids": ["req-1"],
            },
            {
                "task_id": "task-b",
                "status": "failed",
                "monitor_request_ids": ["req-2"],
            },
        ]
    }

    reconciliation, gaps = reconcile_tasks(db_path, checkpoint, required_mode="content")
    assert len(reconciliation) == 2
    assert gaps == []
    assert reconciliation[0]["coverage_ok"] is True
    assert reconciliation[1]["coverage_ok"] is True

    # Missing request gap
    checkpoint_missing = {
        "tasks": [
            {
                "task_id": "task-missing",
                "status": "passed",
                "monitor_request_ids": ["non-existent-req"],
            }
        ]
    }
    _, gaps_missing = reconcile_tasks(db_path, checkpoint_missing, required_mode="content")
    assert any("incomplete recorded inference" in g for g in gaps_missing)

    # In-progress / non-terminal task gap
    checkpoint_pending = {
        "tasks": [
            {
                "task_id": "task-pending",
                "status": "running",
                "monitor_request_ids": ["req-1"],
            }
        ]
    }
    _, gaps_pending = reconcile_tasks(db_path, checkpoint_pending, required_mode="content")
    assert any("task is not terminal" in g for g in gaps_pending)

    # Empty content request gap
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO inference_requests VALUES ('req-empty', 'completed', 'content')")
    checkpoint_empty = {
        "tasks": [
            {
                "task_id": "task-empty",
                "status": "passed",
                "monitor_request_ids": ["req-empty"],
            }
        ]
    }
    _, gaps_empty = reconcile_tasks(db_path, checkpoint_empty, required_mode="content")
    assert any("requests missing recorded content" in g for g in gaps_empty)


def test_create_archive_dry_run_vs_execute(tmp_path: Path, capsys):
    run_dir = tmp_path / "reports" / "suite-test-01"
    run_dir.mkdir(parents=True)
    db_path = tmp_path / "monitor.sqlite3"
    _create_synthetic_database(db_path)

    manifest_data = {
        "run_id": "suite-test-01",
        "cohort": "test-cohort",
        "agent": "test-agent",
        "model": "test-model",
        "source_revision": "rev-123",
        "provenance": {
            "recording_required": "content",
            "effective_api_format": "openai_chat_completions",
        },
    }
    checkpoint_data = {
        "state": "finished",
        "recording_configuration": "content",
        "tasks": [
            {
                "task_id": "task-1",
                "status": "passed",
                "monitor_request_ids": ["req-1", "req-2"],
            }
        ],
    }

    (run_dir / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    (run_dir / "checkpoint.json").write_text(json.dumps(checkpoint_data), encoding="utf-8")
    (run_dir / "report.json").write_text(json.dumps({"summary": "ok"}), encoding="utf-8")

    # 1. Dry run
    parsed_args = parser().parse_args([
        "suite", "archive", "-r", str(run_dir), "-d", str(db_path), "-R", str(tmp_path / "reports"), "-F"
    ])
    assert parsed_args.run == str(run_dir)
    exit_code = main(["suite", "archive", "-r", str(run_dir), "-d", str(db_path), "-R", str(tmp_path / "reports"), "-F"])
    out = capsys.readouterr().out
    assert exit_code == 0
    parsed = json.loads(out)
    assert parsed["dry_run"] is True
    assert parsed["run_id"] == "suite-test-01"

    # 2. Execute with offline database and allow-partial (no live monitor)
    archive_out = tmp_path / "archives" / "archive-01"
    exit_code = main([
        "suite", "archive", "-r", str(run_dir), "-d", str(db_path),
        "-R", str(tmp_path / "reports"), "-o", str(archive_out),
        "-x", "-P", "-F",
    ])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["run_id"] == "suite-test-01"
    assert parsed["archive"] == str(archive_out)
    assert (archive_out / "archive_manifest.json").is_file()
    assert (archive_out / "EVIDENCE_INDEX.md").is_file()
    assert (archive_out / "monitor_snapshot.sqlite3").is_file()
    assert (archive_out / "suite_manifest.json").is_file()

    # 3. Offline verify
    exit_code_verify = main([
        "suite", "archive", "verify", "-p", str(archive_out), "-F"
    ])
    verify_out = capsys.readouterr().out
    assert exit_code_verify == 0
    parsed_verify = json.loads(verify_out)
    assert parsed_verify["integrity_ok"] is True
    assert parsed_verify["problems"] == []


def test_verify_detects_hash_tampering(tmp_path: Path, capsys):
    run_dir = tmp_path / "reports" / "suite-test-02"
    run_dir.mkdir(parents=True)
    db_path = tmp_path / "monitor.sqlite3"
    _create_synthetic_database(db_path)

    (run_dir / "manifest.json").write_text(json.dumps({"run_id": "suite-test-02"}), encoding="utf-8")
    (run_dir / "checkpoint.json").write_text(json.dumps({"state": "finished", "tasks": []}), encoding="utf-8")

    archive_out = tmp_path / "archives" / "archive-02"
    main([
        "suite", "archive", "-r", str(run_dir), "-d", str(db_path),
        "-R", str(tmp_path / "reports"), "-o", str(archive_out),
        "-x", "-P",
    ])
    capsys.readouterr()

    # Tamper with suite_manifest.json
    (archive_out / "suite_manifest.json").write_text("tampered content", encoding="utf-8")

    exit_code = main(["suite", "archive", "verify", "-p", str(archive_out), "-F"])
    out = capsys.readouterr().out
    assert exit_code == 1
    parsed = json.loads(out)
    assert parsed["integrity_ok"] is False
    assert any("Hash mismatch: suite_manifest.json" in p for p in parsed["problems"])


def test_credential_exclusion(tmp_path: Path, monkeypatch, capsys):
    secret_cookie = "super_secret_session_cookie_12345"
    secret_auth = "Bearer super_secret_token_67890"
    monkeypatch.setenv("LLM_MONITOR_SESSION_COOKIE", secret_cookie)
    monkeypatch.setenv("LLM_MONITOR_AUTHORIZATION", secret_auth)

    run_dir = tmp_path / "reports" / "suite-test-sec"
    run_dir.mkdir(parents=True)
    db_path = tmp_path / "monitor.sqlite3"
    _create_synthetic_database(db_path)

    (run_dir / "manifest.json").write_text(json.dumps({"run_id": "suite-test-sec"}), encoding="utf-8")
    (run_dir / "checkpoint.json").write_text(json.dumps({"state": "finished", "tasks": []}), encoding="utf-8")

    archive_out = tmp_path / "archives" / "archive-sec"
    main([
        "suite", "archive", "-r", str(run_dir), "-d", str(db_path),
        "-R", str(tmp_path / "reports"), "-o", str(archive_out),
        "-x", "-P",
    ])
    capsys.readouterr()

    manifest_text = (archive_out / "archive_manifest.json").read_text(encoding="utf-8")
    index_text = (archive_out / "EVIDENCE_INDEX.md").read_text(encoding="utf-8")

    assert secret_cookie not in manifest_text
    assert secret_auth not in manifest_text
    assert secret_cookie not in index_text
    assert secret_auth not in index_text
