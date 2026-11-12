"""Pytest configuration and fixtures for notifications tests."""

import sys
from pathlib import Path

import pytest

# Ensure modules/notifications is on sys.path
package_root = Path(__file__).resolve().parent.parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))


def pytest_configure(config):
    """Ensure basetemp is inside this module's .pytest_tmp_root directory."""
    if not config.option.basetemp:
        basetemp = package_root / ".pytest_tmp_root"
        basetemp.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(basetemp)


@pytest.fixture(autouse=True)
def _isolate_production_credentials_and_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent unit/integration tests from ever reading host production credentials or databases."""
    isolated_dir = tmp_path / "_isolated_host_state"
    secrets_dir = isolated_dir / "secrets"
    monkeypatch.setenv("NOTIFICATIONS_DB_PATH", str(isolated_dir / "events.db"))
    monkeypatch.setenv("NOTIFICATIONS_TOKEN_FILE", str(secrets_dir / "broker-token"))
    monkeypatch.setenv("NOTIFICATIONS_TELEGRAM_SECRETS_FILE", str(secrets_dir / "telegram.json"))
    monkeypatch.setenv("NOTIFY_HEALTHCHECKS_SECRETS_FILE", str(secrets_dir / "healthchecks.json"))
    monkeypatch.delenv("NOTIFY_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("NOTIFY_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("NOTIFY_HEALTHCHECKS_PING_URL", raising=False)
