"""Credential storage and security management for Telegram delivery provider."""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from notifications.config import _secure_path, default_token_path
from notifications.exceptions import SecurityError, ValidationError

_BOT_TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{35,}$")
_CHAT_ID_RE = re.compile(r"^-?\d{5,16}$")
_URL_TOKEN_RE = re.compile(r"bot\d{6,12}:[A-Za-z0-9_-]{35,}")


def redact_token(text: str, token: Optional[str] = None) -> str:
    """Safely redact Telegram bot tokens from URLs, messages, and traces."""
    if not text:
        return ""
    redacted = text
    if token:
        redacted = redacted.replace(token, "[REDACTED_TELEGRAM_TOKEN]")
    redacted = _URL_TOKEN_RE.sub("bot[REDACTED_TELEGRAM_TOKEN]", redacted)
    return redacted


def default_telegram_credentials_path() -> Path:
    override = os.environ.get("NOTIFICATIONS_TELEGRAM_SECRETS_FILE")
    if override:
        return Path(override).expanduser().resolve()
    return default_token_path().parent / "telegram.json"


@dataclass(frozen=True)
class TelegramCredentials:
    """Enrollment parameters for the Telegram Bot API."""

    bot_token: str
    chat_id: str
    dashboard_url: Optional[str] = None

    def __post_init__(self) -> None:
        token = self.bot_token.strip()
        chat = self.chat_id.strip()

        if not _BOT_TOKEN_RE.match(token):
            raise ValidationError(
                "Invalid Telegram bot token format. "
                "Tokens must match '<bot_id>:<secret_hash>' issued by @BotFather."
            )

        if not _CHAT_ID_RE.match(chat) or chat == "0":
            raise ValidationError(
                "Invalid Telegram chat_id format. "
                "Chat IDs must be non-zero numeric strings (positive for user, negative for group)."
            )

        if self.dashboard_url:
            parsed = urlparse(self.dashboard_url)
            if parsed.scheme.lower() != "https":
                raise ValidationError("Dashboard URL must use verified HTTPS scheme.")
            if "@" in parsed.netloc:
                raise ValidationError("Dashboard URL must not embed user credentials.")

    def to_dict(self) -> dict[str, str]:
        data = {"bot_token": self.bot_token, "chat_id": self.chat_id}
        if self.dashboard_url:
            data["dashboard_url"] = self.dashboard_url
        return data


def load_telegram_credentials(path: Optional[Path] = None) -> Optional[TelegramCredentials]:
    """Load and validate Telegram credentials from environment or secured file."""
    # 1. Environment variables take precedence
    env_token = os.environ.get("NOTIFY_TELEGRAM_BOT_TOKEN")
    env_chat = os.environ.get("NOTIFY_TELEGRAM_CHAT_ID")
    env_dash = os.environ.get("NOTIFY_TELEGRAM_DASHBOARD_URL")
    if env_token and env_chat:
        return TelegramCredentials(
            bot_token=env_token.strip(),
            chat_id=env_chat.strip(),
            dashboard_url=env_dash.strip() if env_dash else None,
        )

    # 2. Local secrets file
    file_path = path or default_telegram_credentials_path()
    if not file_path.is_file():
        return None

    # Enforce permissions on existing secrets file
    _secure_path(file_path)

    try:
        content = file_path.read_text("utf-8").strip()
        data = json.loads(content)
        return TelegramCredentials(
            bot_token=data["bot_token"],
            chat_id=str(data["chat_id"]),
            dashboard_url=data.get("dashboard_url"),
        )
    except Exception as exc:
        sanitized_err = redact_token(str(exc))
        raise SecurityError(f"Failed to read secure Telegram credentials from {file_path}: {sanitized_err}") from exc


def save_telegram_credentials(creds: TelegramCredentials, path: Optional[Path] = None) -> Path:
    """Save Telegram credentials to an ACL-restricted JSON file atomically."""
    target_path = path or default_telegram_credentials_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _secure_path(target_path.parent)

    temp_path = target_path.with_name(f"{target_path.name}.new-{secrets.token_hex(4)}")
    try:
        payload = json.dumps(creds.to_dict(), indent=2)
        temp_path.write_text(payload, "utf-8")
        _secure_path(temp_path)
        temp_path.replace(target_path)
        _secure_path(target_path)
        return target_path
    except Exception as exc:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        sanitized_err = redact_token(str(exc), creds.bot_token)
        raise SecurityError(f"Failed to save Telegram credentials to {target_path}: {sanitized_err}") from exc


def revoke_telegram_credentials(path: Optional[Path] = None) -> bool:
    """Revoke and delete the local Telegram credentials file."""
    file_path = path or default_telegram_credentials_path()
    if file_path.is_file():
        file_path.unlink()
        return True
    return False
