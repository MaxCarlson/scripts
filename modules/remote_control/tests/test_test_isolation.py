"""Guard test runs from reading enrolled provider secrets."""

from __future__ import annotations

import os
from pathlib import Path

from notifications.delivery.telegram_credentials import load_telegram_credentials
from notifications.monitoring.config import load_healthchecks_config


def test_default_paths_are_isolated_from_user_home(tmp_path: Path) -> None:
    telegram_path = Path(os.environ["NOTIFICATIONS_TELEGRAM_SECRETS_FILE"])
    healthchecks_path = Path(os.environ["NOTIFY_HEALTHCHECKS_SECRETS_FILE"])

    assert telegram_path == tmp_path / "test-telegram-secrets.json"
    assert healthchecks_path == tmp_path / "test-healthchecks-secrets.json"
    assert Path(os.environ["REMOTE_CONTROL_AUTH_DB_PATH"]) == tmp_path / "test-auth.db"
    assert not telegram_path.exists()
    assert not healthchecks_path.exists()
    assert not Path(os.environ["REMOTE_CONTROL_AUTH_DB_PATH"]).exists()
    assert load_telegram_credentials() is None
    assert load_healthchecks_config() is None
    assert "NOTIFY_TELEGRAM_BOT_TOKEN" not in os.environ
    assert "NOTIFY_TELEGRAM_CHAT_ID" not in os.environ
    assert "NOTIFY_HEALTHCHECKS_PING_URL" not in os.environ
