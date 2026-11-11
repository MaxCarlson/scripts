"""Comprehensive unit, integration, and security tests for Windows desktop notifications (Phase 03).

Covers:
- N09: Multi-provider isolation (Windows offline cannot suppress Telegram, Telegram rate limited cannot suppress Windows)
- N10: Windows IPC authorization, injection resistance (XML tags, quotes, backticks, surrogates, oversized bodies)
- N11: Desktop session availability semantics (Session 0 detection, missing helper, token absence)
- CLI windows subcommands (status, install, uninstall, test) with dry-run default.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from notifications.cli import main
from notifications.delivery.fake import FakeProvider
from notifications.delivery.windows import WindowsDeliveryProvider
from notifications.lifecycle import IncidentLifecycleEngine
from notifications.models import EventEnvelopeV1, RenderedNotification
from notifications.outbox import OutboxWorker
from notifications.storage import StorageEngine
from notifications.windows_helper.service import (
    get_helper_script_path,
    get_helper_status,
    install_scheduled_task,
    send_test_toast,
    uninstall_scheduled_task,
)


def _make_notification(
    title: str = "Host Storage Alert",
    body: str = "Drive C: free space is below 5%.",
    severity: str = "critical",
    deep_link: str | None = "https://dash.example.com/incidents/inc-1234",
) -> RenderedNotification:
    return RenderedNotification(
        notification_id="win-notif-001",
        event_id="00000000-0000-4000-8000-000000000001",
        incident_id="inc-win-001",
        severity=severity,
        title=title,
        body=body,
        deep_link=deep_link,
        created_at="2026-11-11T12:00:00Z",
    )


def _make_event(summary: str = "Test event", severity: str = "critical") -> EventEnvelopeV1:
    return EventEnvelopeV1(
        schema_version=1,
        event_id=str(uuid.uuid4()),
        source="test_runner",
        kind="test.desktop",
        incident_key="test:desktop:key",
        severity=severity,
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        summary=summary,
        lifecycle="open",
    )


# ── 1. N10: Windows Provider HTTP Transport & Security ──────────────────────────


@pytest.mark.asyncio
async def test_windows_provider_success(tmp_path: Path):
    token_file = tmp_path / "token"
    token_file.write_text("secret_test_token_12345", encoding="utf-8")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer secret_test_token_12345"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["title"] == "Host Storage Alert"
        assert payload["severity"] == "critical"
        return httpx.Response(200, json={"ok": True, "status": "display_requested", "toast_id": "toast-abc12345"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = WindowsDeliveryProvider(token_path=token_file, client=client)

    notif = _make_notification()
    receipt = await provider.send(notif)

    assert receipt.status == "provider_accepted"
    assert receipt.provider_message_id == "toast-abc12345"
    assert receipt.error_category is None


@pytest.mark.asyncio
async def test_windows_provider_unauthorized(tmp_path: Path):
    token_file = tmp_path / "token"
    token_file.write_text("bad_token", encoding="utf-8")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "error": "unauthorized"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = WindowsDeliveryProvider(token_path=token_file, client=client)

    receipt = await provider.send(_make_notification())
    assert receipt.status == "terminal_error"
    assert receipt.error_category == "unauthorized"


@pytest.mark.asyncio
async def test_windows_provider_bad_payload(tmp_path: Path):
    token_file = tmp_path / "token"
    token_file.write_text("valid_token", encoding="utf-8")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "error": "missing_required_fields"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = WindowsDeliveryProvider(token_path=token_file, client=client)

    receipt = await provider.send(_make_notification())
    assert receipt.status == "terminal_error"
    assert receipt.error_category == "bad_payload"


# ── 2. N11: Desktop Session Availability Semantics ──────────────────────────────


@pytest.mark.asyncio
async def test_windows_provider_missing_token_file(tmp_path: Path):
    missing_file = tmp_path / "nonexistent_token"
    provider = WindowsDeliveryProvider(token_path=missing_file)

    receipt = await provider.send(_make_notification())
    assert receipt.status == "retryable_error"
    assert receipt.error_category == "session_unavailable"
    assert "token file not found" in receipt.error_message


@pytest.mark.asyncio
async def test_windows_provider_helper_offline(tmp_path: Path):
    token_file = tmp_path / "token"
    token_file.write_text("valid_token", encoding="utf-8")

    def mock_handler(request: httpx.Request):
        raise httpx.ConnectError("Connection refused by localhost:1238")

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = WindowsDeliveryProvider(token_path=token_file, client=client)

    receipt = await provider.send(_make_notification())
    assert receipt.status == "retryable_error"
    assert receipt.error_category == "session_unavailable"
    assert "unavailable or session is inactive" in receipt.error_message


@pytest.mark.asyncio
async def test_windows_provider_helper_timeout(tmp_path: Path):
    token_file = tmp_path / "token"
    token_file.write_text("valid_token", encoding="utf-8")

    def mock_handler(request: httpx.Request):
        raise httpx.TimeoutException("Timed out")

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = WindowsDeliveryProvider(token_path=token_file, client=client, timeout=0.5)

    receipt = await provider.send(_make_notification())
    assert receipt.status == "retryable_error"
    assert receipt.error_category == "session_unavailable"
    assert "timed out" in receipt.error_message


@pytest.mark.asyncio
async def test_windows_provider_session_0_reported_by_helper(tmp_path: Path):
    token_file = tmp_path / "token"
    token_file.write_text("valid_token", encoding="utf-8")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": False,
                "status": "session_unavailable",
                "error": "Interactive user session not active (Session 0)",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = WindowsDeliveryProvider(token_path=token_file, client=client)

    receipt = await provider.send(_make_notification())
    assert receipt.status == "retryable_error"
    assert receipt.error_category == "session_unavailable"
    assert "Session 0" in receipt.error_message


# ── 3. N09: Multi-Provider Isolation ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_provider_windows_offline_does_not_suppress_telegram(tmp_path: Path):
    """N09: Windows helper being offline must not prevent Telegram delivery."""
    db_file = tmp_path / "multi.db"
    storage = StorageEngine(db_file)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage)

    # Windows provider configured to fail (helper offline)
    win_token = tmp_path / "token"
    win_token.write_text("tok", encoding="utf-8")
    win_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("Refused")))
    )
    win_provider = WindowsDeliveryProvider(token_path=win_token, client=win_client)

    # Fake Telegram provider configured to succeed
    fake_tg = FakeProvider(provider_id="telegram", mode="success")

    providers = {"windows": win_provider, "telegram": fake_tg}
    worker = OutboxWorker(storage, providers=providers)

    # Publish event targeted to BOTH providers
    event = _make_event("Power supply degraded", severity="critical")
    res = lifecycle.process_event(event, providers=["windows", "telegram"])
    assert res.outbox_queued is True

    # 2 outbox items queued
    pending = storage.list_pending_outbox()
    assert len(pending) == 2
    providers_queued = {p.provider_id for p in pending}
    assert providers_queued == {"windows", "telegram"}

    # Process outbox once
    processed = await worker.process_pending_once()
    assert processed == 2

    # Verify independent states:
    # 1. Telegram succeeded!
    assert len(fake_tg.sent_notifications) == 1
    # 2. Telegram outbox is provider_accepted (no longer pending)
    # 3. Windows outbox is retryable_error (still in DB with retryable status)
    win_item = [item for item in [storage.get_outbox_item(1), storage.get_outbox_item(2)] if item.provider_id == "windows"][0]
    tg_item = [item for item in [storage.get_outbox_item(1), storage.get_outbox_item(2)] if item.provider_id == "telegram"][0]

    assert win_item.status == "retryable_error"
    assert win_item.retry_count == 1
    assert tg_item.status == "provider_accepted"


@pytest.mark.asyncio
async def test_multi_provider_telegram_rate_limited_does_not_suppress_windows(tmp_path: Path):
    """N09: Telegram 429 rate limit must not prevent Windows desktop delivery."""
    db_file = tmp_path / "multi2.db"
    storage = StorageEngine(db_file)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage)

    # Windows helper succeeds
    win_token = tmp_path / "token"
    win_token.write_text("tok", encoding="utf-8")
    win_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"ok": True, "status": "display_requested", "toast_id": "toast-win-99"})
        )
    )
    win_provider = WindowsDeliveryProvider(token_path=win_token, client=win_client)

    # Telegram rate limited
    fake_tg = FakeProvider(provider_id="telegram", mode="rate_limited", retry_after_seconds=60.0)

    providers = {"windows": win_provider, "telegram": fake_tg}
    worker = OutboxWorker(storage, providers=providers)

    event = _make_event("Thermal threshold exceeded", severity="critical")
    lifecycle.process_event(event, providers=["telegram", "windows"])

    processed = await worker.process_pending_once()
    assert processed == 2

    win_item = [item for item in [storage.get_outbox_item(1), storage.get_outbox_item(2)] if item.provider_id == "windows"][0]
    tg_item = [item for item in [storage.get_outbox_item(1), storage.get_outbox_item(2)] if item.provider_id == "telegram"][0]

    assert win_item.status == "provider_accepted"
    assert tg_item.status == "retryable_error"


# ── 4. N10: Injection Resistance & Formatting ───────────────────────────────────


@pytest.mark.asyncio
async def test_windows_provider_payload_sanitization(tmp_path: Path):
    """N10: Malicious or oversized fields are truncated and safely structured."""
    token_file = tmp_path / "token"
    token_file.write_text("tok", encoding="utf-8")

    captured_payload: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"ok": True, "toast_id": "t-1"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = WindowsDeliveryProvider(token_path=token_file, client=client)

    # Extremely long title and body with XML characters and command injection strings
    evil_title = "<script>alert('xss')</script> " + ("A" * 300)
    evil_body = "Quotes: \"hello\" & 'world' > < `powershell -c whoami`\n\r\t" + ("B" * 2000)

    notif = _make_notification(title=evil_title, body=evil_body)
    receipt = await provider.send(notif)
    assert receipt.status == "provider_accepted"

    # Verify bounds before sending to helper
    assert len(captured_payload["title"]) <= 128
    assert len(captured_payload["body"]) <= 512
    assert "<script>" in captured_payload["title"]  # Plain string passed; XML escaping happens at XML render stage in helper


# ── 5. Helper Script & Service Tests ───────────────────────────────────────────


def test_helper_script_path_discovery():
    path = get_helper_script_path()
    assert path.is_file()
    assert path.name == "helper.ps1"


def test_helper_status_when_offline(tmp_path: Path):
    status = get_helper_status(port=59999, token_path=tmp_path / "none")
    assert status["ok"] is True
    assert status["helper_running"] is False
    assert status["helper_port"] == 59999


def test_install_scheduled_task_dry_run():
    preview = install_scheduled_task(port=1238, apply=False)
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert "ScriptsNotificationsToastHelper" in preview["task_name"]
    assert "warning" in preview


def test_uninstall_scheduled_task_dry_run():
    preview = uninstall_scheduled_task(port=1238, apply=False)
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert "warning" in preview


def test_send_test_toast_dry_run():
    preview = send_test_toast(port=1238, apply=False)
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert "warning" in preview


# ── 6. CLI Windows Subcommand Integration Tests ─────────────────────────────────


def test_cli_windows_subcommands(capsys: pytest.CaptureFixture[str]):
    # 1. status
    rc_stat = main(["windows", "status", "-j"])
    assert rc_stat == 0
    stat_out = json.loads(capsys.readouterr().out)
    assert stat_out["ok"] is True
    assert "task_installed" in stat_out

    # 2. install dry-run
    rc_inst_dry = main(["windows", "install", "-j"])
    assert rc_inst_dry == 0
    inst_dry = json.loads(capsys.readouterr().out)
    assert inst_dry["dry_run"] is True

    # 3. test dry-run
    rc_test_dry = main(["windows", "test", "-j"])
    assert rc_test_dry == 0
    test_dry = json.loads(capsys.readouterr().out)
    assert test_dry["dry_run"] is True

    # 4. uninstall dry-run
    rc_uninst_dry = main(["windows", "uninstall", "-j"])
    assert rc_uninst_dry == 0
    uninst_dry = json.loads(capsys.readouterr().out)
    assert uninst_dry["dry_run"] is True


def test_cli_providers_test_windows_dry_run(capsys: pytest.CaptureFixture[str]):
    rc = main(["providers", "test", "-p", "windows", "-j"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["provider"] == "windows"


# ── 7. Phase 03 Hardening Tests (Request Limits, Safe Interpolation, Token Security) ──


@pytest.mark.asyncio
async def test_windows_provider_payload_too_large_413(tmp_path: Path):
    token_file = tmp_path / "token"
    token_file.write_text("valid_token", encoding="utf-8")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(413, json={"ok": False, "error": "payload_too_large", "max_bytes": 32768})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = WindowsDeliveryProvider(token_path=token_file, client=client)

    receipt = await provider.send(_make_notification())
    assert receipt.status == "terminal_error"
    assert receipt.error_category == "bad_payload"
    assert "payload_too_large" in receipt.error_message


@pytest.mark.asyncio
async def test_windows_provider_request_timeout_408(tmp_path: Path):
    token_file = tmp_path / "token"
    token_file.write_text("valid_token", encoding="utf-8")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(408, json={"ok": False, "error": "request_timeout"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    provider = WindowsDeliveryProvider(token_path=token_file, client=client)

    receipt = await provider.send(_make_notification())
    assert receipt.status == "retryable_error"
    assert receipt.error_category == "session_unavailable"


def test_install_scheduled_task_safe_path_handling(tmp_path: Path):
    """Verify paths with spaces, apostrophes, parentheses, Unicode and metacharacters preview safely."""
    complex_token_path = tmp_path / "John's Dir (x86)" / "Über_Token$1;foo"
    preview = install_scheduled_task(port=1238, token_path=complex_token_path, apply=False)

    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert str(complex_token_path) in preview["arguments"]
    assert "John's Dir (x86)" in preview["arguments"]


def test_helper_forwarding_shim():
    """Verify that the top-level windows_helper/helper.ps1 exists as a forwarding runner."""
    top_helper = Path(__file__).resolve().parent.parent / "windows_helper" / "helper.ps1"
    assert top_helper.is_file()
    content = top_helper.read_text(encoding="utf-8")
    assert "Forwarding launcher" in content
    assert "target" in content


def test_helper_script_elevation_guard():
    """Verify helper.ps1 contains an explicit non-elevation guard."""
    authoritative_helper = Path(__file__).resolve().parent.parent / "notifications" / "windows_helper" / "helper.ps1"
    assert authoritative_helper.is_file()
    content = authoritative_helper.read_text(encoding="utf-8")
    assert "Administrator" in content
    assert "Security Refusal" in content or "must NOT run as Administrator" in content

