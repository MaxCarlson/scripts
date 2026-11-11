"""Integration tests for OutboxWorker dynamic provider dispatch and CLI operations."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from notifications.cli import main
from notifications.delivery.registry import get_registered_providers
from notifications.delivery.telegram import TelegramProvider
from notifications.delivery.telegram_credentials import TelegramCredentials, save_telegram_credentials
from notifications.lifecycle import IncidentLifecycleEngine
from notifications.models import EventEnvelopeV1
from notifications.outbox import OutboxWorker
from notifications.storage import StorageEngine


def _make_event(summary: str = "Outbox integration test") -> EventEnvelopeV1:
    return EventEnvelopeV1(
        schema_version=1,
        event_id=str(uuid.uuid4()),
        source="integration_test",
        kind="test.outbox",
        incident_key="test:outbox:key",
        severity="critical",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        summary=summary,
        lifecycle="open",
    )


@pytest.mark.asyncio
async def test_outbox_telegram_dispatch_success(tmp_path: Path):
    db_file = tmp_path / "outbox.db"
    secrets_file = tmp_path / "telegram.json"
    storage = StorageEngine(db_file)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage)

    # 1. Enroll valid credentials
    token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789"
    chat_id = "987654321"
    creds = TelegramCredentials(bot_token=token, chat_id=chat_id)
    save_telegram_credentials(creds, path=secrets_file)

    # 2. Publish an event targeted for telegram
    event = _make_event("Database high connection count")
    result = lifecycle.process_event(event, providers=["telegram"])
    assert result.outbox_queued is True

    pending = storage.list_pending_outbox()
    assert len(pending) == 1
    assert pending[0].provider_id == "telegram"
    assert pending[0].status == "pending"

    # 3. Setup mock HTTP transport for Telegram Bot API
    recorded_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 999888}})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    with patch("notifications.delivery.registry.load_telegram_credentials", return_value=creds):
        providers = get_registered_providers(storage)
        assert "telegram" in providers
        # Inject mock client to prevent external calls
        providers["telegram"]._client = mock_client
        providers["telegram"].rate_limit_delay = 0.0

        worker = OutboxWorker(storage, providers=providers)
        processed = await worker.process_pending_once()

    assert processed == 1
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert req.url.path == f"/bot{token}/sendMessage"
    payload = json.loads(req.content.decode("utf-8"))
    assert payload["chat_id"] == chat_id
    assert "Database high connection count" in payload["text"]

    # 4. Check outbox item status and delivery attempts table
    assert len(storage.list_pending_outbox()) == 0

    item = storage.get_outbox_item(pending[0].outbox_id)
    assert item is not None
    assert item.status == "provider_accepted"

    attempts = storage.list_delivery_attempts(item.outbox_id)
    assert len(attempts) == 1
    assert attempts[0].status == "provider_accepted"
    assert attempts[0].provider_message_id == "999888"


@pytest.mark.asyncio
async def test_outbox_unconfigured_telegram_records_terminal_error(tmp_path: Path):
    db_file = tmp_path / "outbox.db"
    storage = StorageEngine(db_file)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage)

    # Publish targeted for telegram when unconfigured
    event = _make_event("Unconfigured provider test")
    lifecycle.process_event(event, providers=["telegram"])

    with patch("notifications.delivery.registry.load_telegram_credentials", return_value=None):
        providers = get_registered_providers(storage)
        assert "telegram" in providers

        worker = OutboxWorker(storage, providers=providers)
        processed = await worker.process_pending_once()

    assert processed == 1
    assert len(storage.list_pending_outbox()) == 0

    item = storage.get_outbox_item(1)
    assert item is not None
    assert item.status == "terminal_error"

    attempts = storage.list_delivery_attempts(1)
    assert len(attempts) == 1
    assert attempts[0].status == "terminal_error"
    assert attempts[0].error_category == "unconfigured_provider"


def test_cli_outbox_run_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    db_file = tmp_path / "cli.db"
    storage = StorageEngine(db_file)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage)

    event = _make_event("CLI outbox run test")
    lifecycle.process_event(event, providers=["fake_provider"])
    assert len(storage.list_pending_outbox()) == 1

    rc = main(["outbox", "run", "-d", str(db_file), "-j"])
    assert rc == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["ok"] is True
    assert captured["processed"] == 1
    assert len(storage.list_pending_outbox()) == 0


def test_cli_telegram_enroll_via_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789"
    chat_id = "987654321"
    secrets_file = tmp_path / "telegram.json"

    monkeypatch.setenv("NOTIFY_TELEGRAM_BOT_TOKEN", token)

    with patch("notifications.delivery.telegram_credentials.default_telegram_credentials_path", return_value=secrets_file):
        rc = main(["telegram", "enroll", "-c", chat_id, "-a", "-j"])
        assert rc == 0
        captured = json.loads(capsys.readouterr().out)
        assert captured["ok"] is True
        assert captured["status"] == "enrolled"
        assert captured["chat_id"] == chat_id
        assert secrets_file.is_file()
