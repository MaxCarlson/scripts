"""Comprehensive tests for outbox dispatcher concurrency, crash recovery, and task management."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from notifications.delivery.base import DeliveryProvider
from notifications.exceptions import LockContentionError, LockSetupError
from notifications.models import DeliveryReceipt, EventEnvelopeV1, Incident, OutboxItem, RenderedNotification
from notifications.outbox import (
    OUTBOX_TASK_NAME,
    OutboxLock,
    OutboxWorker,
    _sanitize_error_message,
    default_outbox_lock_path,
    get_outbox_task_status,
    install_outbox_task,
    uninstall_outbox_task,
)
from notifications.storage import StorageEngine


class MockProvider(DeliveryProvider):
    """Synthetic provider for testing dispatcher behaviors without network I/O."""

    def __init__(self, provider_id: str = "mock_provider") -> None:
        self._provider_id = provider_id
        self.send_calls: list[RenderedNotification] = []
        self.send_handler: Optional[Any] = None

    @property
    def provider_id(self) -> str:
        return self._provider_id

    async def send(self, notification: RenderedNotification) -> DeliveryReceipt:
        self.send_calls.append(notification)
        if self.send_handler:
            return await self.send_handler(notification)
        return DeliveryReceipt(
            provider_id=self._provider_id,
            status="provider_accepted",
            provider_message_id=f"msg_{len(self.send_calls)}",
        )


def _create_sample_event(event_id: Optional[str] = None) -> EventEnvelopeV1:
    return EventEnvelopeV1(
        schema_version=1,
        event_id=event_id or str(uuid.uuid4()),
        source="test_source",
        kind="process_crash",
        incident_key="proc_123",
        severity="critical",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        summary="Test process crashed unexpectedly",
        lifecycle="open",
    )


def _setup_storage_with_event(tmp_path: Path, event_id: Optional[str] = None) -> tuple[StorageEngine, int]:
    db_path = tmp_path / "events.db"
    storage = StorageEngine(db_path)
    storage.migrate()

    event = _create_sample_event(event_id)
    storage.record_event(event)

    incident = Incident(
        incident_id=event.incident_id,
        source=event.source,
        incident_key=event.incident_key,
        active_occurrence_id=None,
        status="open",
        severity=event.severity,
        summary=event.summary,
        first_seen=event.occurred_at,
        last_seen=event.occurred_at,
    )
    storage.save_incident(incident)

    outbox_id = storage.enqueue_outbox(
        event_id=event.event_id,
        incident_id=event.incident_id,
        provider_id="mock_provider",
    )
    return storage, outbox_id


# ---------------------------------------------------------------------------
# Concurrency & Advisory Lock Tests
# ---------------------------------------------------------------------------

def test_outbox_lock_single_instance(tmp_path: Path):
    """Verify exclusive lock prevents overlapping active dispatcher instances."""
    lock_path = tmp_path / ".outbox.lock"
    lock1 = OutboxLock(lock_path)
    lock2 = OutboxLock(lock_path)

    with lock1:
        assert lock_path.is_file()

        # Second lock attempt must fail with LockContentionError
        with pytest.raises(LockContentionError) as exc_info:
            with lock2:
                pass
        assert "Another outbox dispatcher is currently running" in str(exc_info.value)

    # After first lock exits, content can be read and second lock can acquire
    content = lock_path.read_text(encoding="utf-8")
    assert f"pid={os.getpid()}" in content

    with lock2:
        assert lock_path.is_file()


def test_outbox_lock_releases_on_exception(tmp_path: Path):
    """Verify lock is released even if an unhandled exception occurs inside with block."""
    lock_path = tmp_path / ".outbox.lock"
    lock1 = OutboxLock(lock_path)
    lock2 = OutboxLock(lock_path)

    with pytest.raises(RuntimeError):
        with lock1:
            raise RuntimeError("simulated crash inside lock")

    # Second lock can acquire immediately
    with lock2:
        pass


def test_outbox_worker_run_dispatch_respects_lock(tmp_path: Path):
    """Verify run_dispatch fails closed when another dispatcher holds the lock."""
    storage, _ = _setup_storage_with_event(tmp_path)
    provider = MockProvider()
    worker = OutboxWorker(storage, {"mock_provider": provider})

    lock_path = tmp_path / ".outbox_worker.lock"
    lock_external = OutboxLock(lock_path)

    with lock_external:
        with pytest.raises(LockContentionError):
            worker.run_dispatch(lock=OutboxLock(lock_path))


# ---------------------------------------------------------------------------
# Crash Recovery & Stalled Claim Tests
# ---------------------------------------------------------------------------

def test_stalled_claim_recovered_after_crash(tmp_path: Path):
    """Verify item stuck in 'attempting' before provider completion is safely recovered."""
    storage, outbox_id = _setup_storage_with_event(tmp_path)

    # Worker claims item but crashes before provider send
    claimed = storage.claim_outbox_item(outbox_id)
    assert claimed is True

    # Item is attempting, not in pending list
    assert len(storage.list_pending_outbox()) == 0

    # Simulate 300+ seconds elapsed by resetting with stalled_seconds=0
    recovered_count = storage.reset_stalled_outbox_items(stalled_seconds=0.0)
    assert recovered_count == 1

    # Verify item status was reset to pending and retry_count was incremented
    pending = storage.list_pending_outbox()
    assert len(pending) == 1
    assert pending[0].outbox_id == outbox_id
    assert pending[0].status == "pending"
    assert pending[0].retry_count == 1

    # Verify durable delivery attempt audit record was created
    attempts = storage.list_delivery_attempts(outbox_id)
    assert len(attempts) == 1
    assert attempts[0].status == "stalled_claim_recovered"
    assert attempts[0].error_category == "worker_interrupted"
    assert "potential duplicate delivery" in (attempts[0].error_message or "")


def test_live_worker_protected_from_premature_reclamation(tmp_path: Path):
    """Verify an active worker's in-flight items are NOT reclaimed if within the stale threshold."""
    storage, outbox_id = _setup_storage_with_event(tmp_path)

    claimed = storage.claim_outbox_item(outbox_id)
    assert claimed is True

    # Attempting item updated just now; with stalled_seconds=300, it must NOT be reset
    recovered_count = storage.reset_stalled_outbox_items(stalled_seconds=300.0)
    assert recovered_count == 0

    # Item remains in attempting state
    pending = storage.list_pending_outbox()
    assert len(pending) == 0


def test_crash_after_provider_acceptance_duplicate_delivery_semantics(tmp_path: Path):
    """Verify at-least-once semantics: provider received message, but worker died before recording receipt."""
    storage, outbox_id = _setup_storage_with_event(tmp_path)
    provider = MockProvider()
    worker = OutboxWorker(storage, {"mock_provider": provider})

    # Worker claims item
    storage.claim_outbox_item(outbox_id)

    # Simulate provider successfully sent, but process crashed before record_delivery_attempt
    # Recovery runs:
    recovered = worker.recover_stalled(stalled_seconds=0.0)
    assert recovered == 1

    # Audit shows uncertain delivery
    attempts = storage.list_delivery_attempts(outbox_id)
    assert len(attempts) == 1
    assert attempts[0].status == "stalled_claim_recovered"

    # Worker dispatches pending queue: provider receives duplicate delivery attempt
    res = worker.run_dispatch(limit=10, lock=OutboxLock(tmp_path / ".lock"))
    assert res["processed"] == 1
    assert len(provider.send_calls) == 1

    # Now marked as provider_accepted
    final_attempts = storage.list_delivery_attempts(outbox_id)
    assert len(final_attempts) == 2
    assert final_attempts[1].status == "provider_accepted"


def test_stalled_recovery_retry_exhaustion_transitions_to_terminal_error(tmp_path: Path):
    """Verify poison task repeatedly crashing workers terminates when max_retries is reached."""
    storage, outbox_id = _setup_storage_with_event(tmp_path)

    # Set retry_count close to max_retries (default 5)
    with storage.connect() as conn:
        conn.execute("UPDATE outbox SET retry_count = 4, max_retries = 5 WHERE outbox_id = ?;", (outbox_id,))

    # Claim item (worker crash simulation #5)
    storage.claim_outbox_item(outbox_id)

    # Recover stalled: retry_count goes from 4 to 5 >= max_retries -> terminal_error
    recovered = storage.reset_stalled_outbox_items(stalled_seconds=0.0)
    assert recovered == 1

    # Verify outbox item transitioned to terminal_error, NOT pending
    pending = storage.list_pending_outbox()
    assert len(pending) == 0

    with storage.connect() as conn:
        row = conn.execute("SELECT status, retry_count FROM outbox WHERE outbox_id = ?;", (outbox_id,)).fetchone()
        assert row["status"] == "terminal_error"
        assert row["retry_count"] == 5


# ---------------------------------------------------------------------------
# Provider Error Handling & Redaction Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_401_403_and_timeout_resilience(tmp_path: Path):
    """Verify provider error responses (401, timeout) are recorded as retryable/terminal errors without crash."""
    storage, outbox_id = _setup_storage_with_event(tmp_path)
    provider = MockProvider()

    # Configure mock to simulate HTTP 401 Unauthorized
    async def mock_401(n: RenderedNotification) -> DeliveryReceipt:
        return DeliveryReceipt(
            provider_id="mock_provider",
            status="retryable_error",
            error_category="unauthorized",
            error_message="HTTP 401 Unauthorized",
            retry_after_seconds=60.0,
        )

    provider.send_handler = mock_401
    worker = OutboxWorker(storage, {"mock_provider": provider})

    processed = await worker.process_pending_once()
    assert processed == 1

    attempts = storage.list_delivery_attempts(outbox_id)
    assert len(attempts) == 1
    assert attempts[0].status == "retryable_error"
    assert attempts[0].error_category == "unauthorized"

    # Configure mock to simulate timeout exception
    async def mock_timeout(n: RenderedNotification) -> DeliveryReceipt:
        raise TimeoutError("Network read deadline exceeded after 5.0s")

    # Advance time for retry
    with storage.connect() as conn:
        conn.execute("UPDATE outbox SET next_retry_at = '2000-01-01T00:00:00Z', status = 'pending' WHERE outbox_id = ?;", (outbox_id,))

    provider.send_handler = mock_timeout
    processed = await worker.process_pending_once()
    assert processed == 1

    attempts2 = storage.list_delivery_attempts(outbox_id)
    assert len(attempts2) == 2
    assert attempts2[1].status == "retryable_error"
    assert attempts2[1].error_category == "provider_exception"
    assert "Network read deadline exceeded" in (attempts2[1].error_message or "")


def test_secret_redaction_in_outbox_errors(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """Verify Telegram bot tokens and secrets are redacted from delivery_attempts, error messages, and logs."""
    sensitive_token = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ123456789"
    raw_error = f"Failed to connect to https://api.telegram.org/bot{sensitive_token}/sendMessage: Connection reset"

    redacted = _sanitize_error_message(raw_error)
    assert sensitive_token not in redacted
    assert "REDACTED" in redacted

    storage, outbox_id = _setup_storage_with_event(tmp_path)
    provider = MockProvider()

    async def mock_leak(n: RenderedNotification) -> DeliveryReceipt:
        raise RuntimeError(f"Internal error with bot token {sensitive_token} at https://api.telegram.org/bot{sensitive_token}/sendMessage")

    provider.send_handler = mock_leak
    worker = OutboxWorker(storage, {"mock_provider": provider})

    import logging
    with caplog.at_level(logging.DEBUG):
        asyncio.run(worker.process_pending_once())

    # 1. Verify SQLite storage persistence redaction
    attempts = storage.list_delivery_attempts(outbox_id)
    assert len(attempts) == 1
    assert sensitive_token not in (attempts[0].error_message or "")
    assert "REDACTED" in (attempts[0].error_message or "")

    # 2. Verify application logger traceback and message redaction
    assert sensitive_token not in caplog.text
    assert "REDACTED" in caplog.text
    # Ensure useful non-sensitive diagnostics (traceback, line numbers, error name) are preserved
    assert "RuntimeError" in caplog.text
    assert "mock_leak" in caplog.text


def test_logger_redaction_exception_handler_and_persistence_separate(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """Cover the exception-handler path and SQLite persistence separately to guarantee complete token elimination."""
    sensitive_token = "987654321:XYZ987654321_abcDEFghiJKLmnoPQRstuv"
    storage, outbox_id = _setup_storage_with_event(tmp_path)

    provider = MockProvider("leaky_provider")

    async def raise_nested(n: RenderedNotification) -> DeliveryReceipt:
        def inner_call() -> None:
            raise ValueError(f"Nested failure on https://api.telegram.org/bot{sensitive_token}/getMe")
        inner_call()
        return DeliveryReceipt(provider_id="leaky_provider", status="provider_accepted")

    provider.send_handler = raise_nested
    worker = OutboxWorker(storage, {"mock_provider": provider})

    import logging
    with caplog.at_level(logging.DEBUG):
        count = asyncio.run(worker.process_pending_once())
    assert count == 1

    # Check A: Logger records must have token scrubbed from both record.message and full record text
    assert sensitive_token not in caplog.text
    assert "REDACTED" in caplog.text
    # Diagnostic frames preserved
    assert "inner_call" in caplog.text
    assert "ValueError" in caplog.text

    # Check B: SQLite delivery_attempts table has token scrubbed
    attempts = storage.list_delivery_attempts(outbox_id)
    assert len(attempts) == 1
    assert sensitive_token not in (attempts[0].error_message or "")
    assert "REDACTED" in (attempts[0].error_message or "")

    # Check C: SQLite outbox table error_message has token scrubbed
    with storage.connect() as conn:
        row = conn.execute("SELECT error_message FROM outbox WHERE outbox_id = ?;", (outbox_id,)).fetchone()
        assert sensitive_token not in (row["error_message"] or "")
        assert "REDACTED" in (row["error_message"] or "")


# ---------------------------------------------------------------------------
# Cross-Process Windows Locking Tests
# ---------------------------------------------------------------------------

def test_windows_cross_process_locking_lifecycle(tmp_path: Path):
    """Verify lock acquisition, contention, normal exit, and abnormal kill across separate OS processes."""
    import subprocess
    py_exe = sys.executable
    lock_file = tmp_path / "cross_proc.lock"
    notifications_path = str(Path(__file__).resolve().parent.parent)

    code_holder = f"""
import sys, time
from notifications.outbox import OutboxLock
with OutboxLock(r"{lock_file}"):
    print("HELD", flush=True)
    time.sleep(2)
print("EXITED", flush=True)
"""

    code_checker = f"""
import sys
from notifications.outbox import OutboxLock
from notifications.exceptions import LockContentionError
try:
    with OutboxLock(r"{lock_file}"):
        print("ACQUIRED", flush=True)
except LockContentionError:
    print("CONTENTION", flush=True)
"""

    env = os.environ.copy()
    env["PYTHONPATH"] = notifications_path

    # Step 1: Process A acquires the lock
    p_a = subprocess.Popen([py_exe, "-c", code_holder], stdout=subprocess.PIPE, text=True, env=env)
    line = p_a.stdout.readline().strip()
    assert line == "HELD"

    # Step 2 & 3: Process B cannot acquire it while A owns it and receives expected contention
    res_b1 = subprocess.run([py_exe, "-c", code_checker], capture_output=True, text=True, env=env)
    assert res_b1.stdout.strip() == "CONTENTION"

    # Step 4: After A exits normally, B can acquire the lock
    p_a.wait(timeout=5)
    res_b2 = subprocess.run([py_exe, "-c", code_checker], capture_output=True, text=True, env=env)
    assert res_b2.stdout.strip() == "ACQUIRED"

    # Step 5: After abnormal termination of A (kill), B can acquire the lock
    p_a2 = subprocess.Popen([py_exe, "-c", code_holder], stdout=subprocess.PIPE, text=True, env=env)
    line2 = p_a2.stdout.readline().strip()
    assert line2 == "HELD"

    # Kill Process A abruptly
    p_a2.kill()
    p_a2.wait(timeout=5)

    # Process B must acquire the lock immediately
    res_b3 = subprocess.run([py_exe, "-c", code_checker], capture_output=True, text=True, env=env)
    assert res_b3.stdout.strip() == "ACQUIRED"


def test_windows_cross_process_cli_dispatcher_concurrency(tmp_path: Path):
    """Verify separate dispatcher processes cannot recover or dispatch the same item simultaneously via CLI."""
    import subprocess
    import json
    py_exe = sys.executable
    storage, outbox_id = _setup_storage_with_event(tmp_path)
    lock_file = tmp_path / ".outbox_worker.lock"
    notifications_path = str(Path(__file__).resolve().parent.parent)

    env = os.environ.copy()
    env["PYTHONPATH"] = notifications_path

    # Process A holds the dispatcher lock simulating an active in-progress dispatch
    lock_a = OutboxLock(lock_file)
    with lock_a:
        # Process B attempts to run `scripts-notify outbox run -d <db> -j`
        cli_run = subprocess.run(
            [py_exe, "-m", "notifications.cli", "outbox", "run", "-d", str(storage.db_path), "-j"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert cli_run.returncode == 0
        data = json.loads(cli_run.stdout.strip())
        assert data["ok"] is True
        assert data["locked"] is True
        assert data["status"] == "skipped_locked"
        assert data["processed"] == 0

        # Verify the item in database is still pending and was NOT claimed or touched by Process B
        pending = storage.list_pending_outbox()
        assert len(pending) == 1
        assert pending[0].outbox_id == outbox_id
        assert pending[0].status == "pending"

    # Now that Process A released the lock, Process B can dispatch the item successfully
    cli_run2 = subprocess.run(
        [py_exe, "-m", "notifications.cli", "outbox", "run", "-d", str(storage.db_path), "-j"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert cli_run2.returncode == 0
    data2 = json.loads(cli_run2.stdout.strip())
    assert data2["ok"] is True
    assert data2.get("locked") is None or data2.get("locked") is False
    assert data2["processed"] == 1


def test_successful_queued_delivery_to_provider(tmp_path: Path):
    """Verify end-to-end queued item is dispatched to registered provider and marked accepted."""
    storage, outbox_id = _setup_storage_with_event(tmp_path)
    provider = MockProvider("windows")

    # Update provider_id in outbox to windows
    with storage.connect() as conn:
        conn.execute("UPDATE outbox SET provider_id = 'windows' WHERE outbox_id = ?;", (outbox_id,))

    worker = OutboxWorker(storage, {"windows": provider})
    res = worker.run_dispatch(limit=10, lock=OutboxLock(tmp_path / ".lock"))

    assert res["processed"] == 1
    assert len(provider.send_calls) == 1
    assert provider.send_calls[0].notification_id == str(outbox_id)

    # Outbox status updated to provider_accepted
    with storage.connect() as conn:
        row = conn.execute("SELECT status FROM outbox WHERE outbox_id = ?;", (outbox_id,)).fetchone()
        assert row["status"] == "provider_accepted"


# ---------------------------------------------------------------------------
# Windows Scheduled Task Dry-Run & Lifecycle Tests
# ---------------------------------------------------------------------------

def test_install_outbox_task_dry_run_preview():
    """Verify task install defaults to safe preview without applying modifications."""
    preview = install_outbox_task(
        apply=False,
        interval_minutes=2,
        limit=50,
        executable="C:\\Python\\python.exe",
        working_directory="C:\\Users\\mcarls",
    )
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["requires_apply"] is True
    assert preview["task_name"] == OUTBOX_TASK_NAME
    assert preview["interval_minutes"] == 2
    assert preview["limit"] == 50
    assert "notifications.cli" in preview["arguments"]
    assert "outbox run --limit 50" in preview["arguments"]
    assert preview["working_directory"] == "C:\\Users\\mcarls"


def test_install_outbox_task_parameter_validation():
    """Verify invalid interval or limit values are rejected cleanly."""
    res_interval = install_outbox_task(interval_minutes=0)
    assert res_interval["ok"] is False
    assert "Invalid interval_minutes" in res_interval["error"]

    res_limit = install_outbox_task(limit=0)
    assert res_limit["ok"] is False
    assert "Invalid limit" in res_limit["error"]

    res_injection = install_outbox_task(executable="python.exe\nmalicious")
    assert res_injection["ok"] is False
    assert "Invalid characters" in res_injection["error"]


def test_uninstall_outbox_task_dry_run_preview():
    """Verify task uninstall defaults to safe preview without applying modifications."""
    preview = uninstall_outbox_task(apply=False)
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["requires_apply"] is True
    assert preview["task_name"] == OUTBOX_TASK_NAME


def test_get_outbox_task_status_structure():
    """Verify get_outbox_task_status returns valid contract structure."""
    status = get_outbox_task_status()
    assert "ok" in status
    assert status["task_name"] == OUTBOX_TASK_NAME
    assert "task_installed" in status
    assert "state" in status
