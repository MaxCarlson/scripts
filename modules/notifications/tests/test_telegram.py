"""Comprehensive unit and mocked HTTP integration tests for Telegram provider."""

from __future__ import annotations

import asyncio
import json
import ssl
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from notifications.cli import main
from notifications.delivery.telegram import TelegramProvider
from notifications.delivery.telegram_credentials import (
    TelegramCredentials,
    load_telegram_credentials,
    redact_token,
    revoke_telegram_credentials,
    save_telegram_credentials,
)
from notifications.exceptions import SecurityError, ValidationError
from notifications.models import RenderedNotification
from notifications.outbox import OutboxWorker
from notifications.storage import StorageEngine


def _dummy_notification(
    severity: str = "critical",
    title: str = "Database Disk Space Critical",
    body: str = "Root mount /var is at 98% utilization.",
) -> RenderedNotification:
    return RenderedNotification(
        notification_id="notif-tg-001",
        event_id="00000000-0000-4000-8000-000000000001",
        incident_id="inc-tg-001",
        severity=severity,
        title=title,
        body=body,
        created_at="2026-11-11T12:00:00Z",
    )


# ── 1. Credentials & Security Tests ───────────────────────────────────────────


def test_telegram_credentials_validation() -> None:
    # Valid credentials
    valid = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
        dashboard_url="https://dash.example.com/incidents",
    )
    assert valid.bot_token.startswith("123456789:")
    assert valid.chat_id == "987654321"
    assert valid.dashboard_url == "https://dash.example.com/incidents"

    # Reject malformed token
    with pytest.raises(ValidationError):
        TelegramCredentials(bot_token="short_bad_token", chat_id="987654321")

    # Reject zero or invalid chat ID
    with pytest.raises(ValidationError):
        TelegramCredentials(bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789", chat_id="0")
    with pytest.raises(ValidationError):
        TelegramCredentials(bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789", chat_id="invalid_chat")

    # Reject non-https dashboard URL
    with pytest.raises(ValidationError):
        TelegramCredentials(
            bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
            chat_id="987654321",
            dashboard_url="http://insecure.example.com",
        )

    # Reject dashboard URL with embedded credentials
    with pytest.raises(ValidationError):
        TelegramCredentials(
            bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
            chat_id="987654321",
            dashboard_url="https://user:password@dash.example.com",
        )


def test_telegram_credentials_save_load_revoke(tmp_path: Path) -> None:
    secrets_file = tmp_path / "telegram.json"
    creds = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
    )

    # Save
    saved_path = save_telegram_credentials(creds, path=secrets_file)
    assert saved_path == secrets_file
    assert secrets_file.is_file()

    # Load
    loaded = load_telegram_credentials(path=secrets_file)
    assert loaded is not None
    assert loaded.bot_token == creds.bot_token
    assert loaded.chat_id == creds.chat_id

    # Revoke
    revoked = revoke_telegram_credentials(path=secrets_file)
    assert revoked is True
    assert not secrets_file.exists()
    assert load_telegram_credentials(path=secrets_file) is None


def test_telegram_token_redaction() -> None:
    token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    assert token not in redact_token(url, token)
    assert "[REDACTED_TELEGRAM_TOKEN]" in redact_token(url, token)

    # Automatic regex redaction without explicit token passed
    assert token not in redact_token(url)
    assert "[REDACTED_TELEGRAM_TOKEN]" in redact_token(url)


# ── 2. Message Rendering & Truncation Tests ────────────────────────────────────


def test_telegram_render_and_truncation() -> None:
    creds = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
        dashboard_url="https://monitor.example.com/alerts",
    )
    provider = TelegramProvider(credentials=creds)

    # Normal alert rendering
    notif = _dummy_notification()
    text = provider.render(notif)
    assert "[CRITICAL] Database Disk Space Critical" in text
    assert "Root mount /var is at 98% utilization." in text
    assert "Incident: inc-tg-0" in text
    assert "Dashboard: https://monitor.example.com/alerts" in text

    # Strip control characters
    notif_ctrl = _dummy_notification(body="Alert with\x00 null and \x07 bell \x1b escape chars.")
    clean_text = provider.render(notif_ctrl)
    assert "\x00" not in clean_text
    assert "\x07" not in clean_text
    assert "\x1b" not in clean_text

    # Truncate massive message (>4000 characters)
    huge_body = "x" * 6000
    notif_huge = _dummy_notification(body=huge_body)
    rendered_huge = provider.render(notif_huge)
    assert len(rendered_huge) <= 4000
    assert "...[truncated]" in rendered_huge


# ── 3. Quiet Hours & Rate Pacing Tests ─────────────────────────────────────────


def test_telegram_quiet_hours() -> None:
    creds = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
    )
    # Quiet hours from 22:00 to 07:00
    provider = TelegramProvider(credentials=creds, quiet_hours=(22, 7))

    # Nighttime check: 23:30 UTC
    night = datetime(2026, 11, 11, 23, 30, tzinfo=timezone.utc)
    assert provider.is_quiet_hours(now=night) is True

    # Daytime check: 14:00 UTC
    day = datetime(2026, 11, 11, 14, 0, tzinfo=timezone.utc)
    assert provider.is_quiet_hours(now=day) is False


@pytest.mark.asyncio
async def test_telegram_quiet_hours_deferral() -> None:
    creds = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
    )
    provider = TelegramProvider(credentials=creds, quiet_hours=(0, 24))  # All day quiet hours

    # Warning alert during quiet hours must be deferred
    warn_notif = _dummy_notification(severity="warning")
    receipt_warn = await provider.send(warn_notif)
    assert receipt_warn.status == "retryable_error"
    assert receipt_warn.error_category == "quiet_hours_deferred"
    assert receipt_warn.retry_after_seconds == 300.0

    # Critical alert MUST bypass quiet hours
    # Using mock client so no network is attempted
    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": True, "result": {"message_id": 999}})
    )
    provider_bypass = TelegramProvider(
        credentials=creds,
        client=httpx.AsyncClient(transport=mock_transport),
        quiet_hours=(0, 24),
    )
    crit_notif = _dummy_notification(severity="critical")
    receipt_crit = await provider_bypass.send(crit_notif)
    assert receipt_crit.status == "provider_accepted"
    assert receipt_crit.provider_message_id == "999"


# ── 4. Mocked HTTP Transport & Error Scenarios ────────────────────────────────


@pytest.mark.asyncio
async def test_telegram_send_success_200() -> None:
    creds = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["chat_id"] == "987654321"
        assert "[CRITICAL]" in data["text"]
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 12345}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TelegramProvider(credentials=creds, client=client, rate_limit_delay=0.0)

    receipt = await provider.send(_dummy_notification())
    assert receipt.status == "provider_accepted"
    assert receipt.provider_message_id == "12345"


@pytest.mark.asyncio
async def test_telegram_send_429_rate_limit() -> None:
    creds = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 42",
                "parameters": {"retry_after": 42},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TelegramProvider(credentials=creds, client=client, rate_limit_delay=0.0)

    receipt = await provider.send(_dummy_notification())
    assert receipt.status == "retryable_error"
    assert receipt.error_category == "rate_limited_429"
    assert receipt.retry_after_seconds == 42.0


@pytest.mark.asyncio
async def test_telegram_send_401_terminal_error() -> None:
    token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789"
    creds = TelegramCredentials(bot_token=token, chat_id="987654321")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "error_code": 401, "description": f"Unauthorized token {token}"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TelegramProvider(credentials=creds, client=client, rate_limit_delay=0.0)

    receipt = await provider.send(_dummy_notification())
    assert receipt.status == "terminal_error"
    assert receipt.error_category == "unauthorized_credentials"
    # Verify token is redacted in error message
    assert token not in receipt.error_message
    assert "[REDACTED_TELEGRAM_TOKEN]" in receipt.error_message


@pytest.mark.asyncio
async def test_telegram_send_400_bad_request_terminal() -> None:
    creds = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TelegramProvider(credentials=creds, client=client, rate_limit_delay=0.0)

    receipt = await provider.send(_dummy_notification())
    assert receipt.status == "terminal_error"
    assert receipt.error_category == "bad_request_400"
    assert "chat not found" in receipt.error_message


@pytest.mark.asyncio
async def test_telegram_send_500_transient_error() -> None:
    creds = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TelegramProvider(credentials=creds, client=client, rate_limit_delay=0.0)

    receipt = await provider.send(_dummy_notification())
    assert receipt.status == "retryable_error"
    assert receipt.error_category == "server_error_5xx"
    assert receipt.retry_after_seconds == 15.0


@pytest.mark.asyncio
async def test_telegram_send_network_timeout() -> None:
    creds = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Mocked gateway read timeout")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TelegramProvider(credentials=creds, client=client, rate_limit_delay=0.0)

    receipt = await provider.send(_dummy_notification())
    assert receipt.status == "retryable_error"
    assert receipt.error_category == "network_timeout"


@pytest.mark.asyncio
async def test_telegram_send_connection_error() -> None:
    creds = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Mocked DNS failure")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TelegramProvider(credentials=creds, client=client, rate_limit_delay=0.0)

    receipt = await provider.send(_dummy_notification())
    assert receipt.status == "retryable_error"
    assert receipt.error_category == "connection_failure"


# ── 5. Outbox Worker Integration with Telegram ─────────────────────────────────


@pytest.mark.asyncio
async def test_outbox_worker_with_telegram(tmp_path: Path) -> None:
    db = tmp_path / "events.db"
    storage = StorageEngine(db)
    storage.migrate()

    # Enqueue outbox item
    from notifications.lifecycle import IncidentLifecycleEngine
    from notifications.models import EventEnvelopeV1

    engine = IncidentLifecycleEngine(storage)
    event = EventEnvelopeV1(
        event_id="00000000-0000-4000-8000-000000000005",
        schema_version=1,
        source="system",
        kind="system.test",
        incident_key="test.key",
        severity="critical",
        lifecycle="open",
        occurred_at="2026-11-11T12:00:00Z",
        summary="Testing outbox with Telegram provider",
    )
    engine.process_event(event, providers=["telegram"])

    # Prepare mocked Telegram provider
    creds = TelegramCredentials(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
        chat_id="987654321",
    )
    mock_transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"ok": True, "result": {"message_id": 77777}})
    )
    tg_provider = TelegramProvider(
        credentials=creds,
        client=httpx.AsyncClient(transport=mock_transport),
        rate_limit_delay=0.0,
    )

    worker = OutboxWorker(storage=storage, providers={"telegram": tg_provider})
    processed = await worker.process_pending_once()
    assert processed == 1

    # Verify attempt and outbox item in storage
    attempts = storage.list_delivery_attempts(1)
    assert len(attempts) == 1
    assert attempts[0].status == "provider_accepted"
    assert attempts[0].provider_message_id == "77777"


# ── 6. CLI Telegram Subcommand Tests ──────────────────────────────────────────


def test_cli_telegram_subcommands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789"
    chat = "987654321"
    secrets_file = tmp_path / "secrets" / "telegram.json"

    with patch("notifications.delivery.telegram_credentials.default_telegram_credentials_path", return_value=secrets_file):
        # 1. Status unconfigured
        rc_stat0 = main(["telegram", "status", "-j"])
        assert rc_stat0 == 0
        stat0 = json.loads(capsys.readouterr().out)
        assert stat0["enrolled"] is False

        # 2. Enroll dry run
        rc_enr_dry = main(["telegram", "enroll", "-t", token, "-c", chat, "-j"])
        assert rc_enr_dry == 0
        enr_dry = json.loads(capsys.readouterr().out)
        assert enr_dry["dry_run"] is True
        assert not secrets_file.exists()

        # 3. Enroll apply
        rc_enr = main(["telegram", "enroll", "-t", token, "-c", chat, "-a", "-j"])
        assert rc_enr == 0
        enr = json.loads(capsys.readouterr().out)
        assert enr["status"] == "enrolled"
        assert secrets_file.is_file()

        # 4. Status enrolled
        rc_stat1 = main(["telegram", "status", "-j"])
        assert rc_stat1 == 0
        stat1 = json.loads(capsys.readouterr().out)
        assert stat1["enrolled"] is True
        assert stat1["chat_id"] == chat
        assert token not in stat1["bot_token"]  # Must be redacted

        # 5. Test dry-run
        rc_test_dry = main(["telegram", "test", "-j"])
        assert rc_test_dry == 0
        test_dry = json.loads(capsys.readouterr().out)
        assert test_dry["dry_run"] is True

        # 6. Revoke apply
        rc_rev = main(["telegram", "revoke", "-a", "-j"])
        assert rc_rev == 0
        rev = json.loads(capsys.readouterr().out)
        assert rev["revoked"] is True
        assert not secrets_file.exists()
