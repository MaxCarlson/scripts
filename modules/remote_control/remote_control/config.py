"""Configuration and environment settings for remote_control service."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


def default_auth_db_path() -> Path:
    override = os.environ.get("REMOTE_CONTROL_AUTH_DB_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".scripts" / "remote_control" / "auth.db"


def default_notifications_db_path() -> Path:
    override = os.environ.get("NOTIFICATIONS_DB_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".scripts" / "notifications" / "events.db"


def default_healthchecks_config_path() -> Path:
    override = os.environ.get("NOTIFY_HEALTHCHECKS_SECRETS_FILE")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".scripts" / "notifications" / "secrets" / "healthchecks.json"


@dataclass(frozen=True)
class RemoteControlConfig:
    """Runtime configuration for remote control dashboard service."""

    host: str = "127.0.0.1"
    port: int = 8443
    auth_db_path: Path = field(default_factory=default_auth_db_path)
    notifications_db_path: Path = field(default_factory=default_notifications_db_path)
    healthchecks_config_path: Path = field(default_factory=default_healthchecks_config_path)
    cookie_secure: bool = False
    cookie_samesite: str = "strict"
    session_max_age_seconds: int = 7 * 86400  # 7 days
    session_idle_timeout_seconds: int = 2 * 86400  # 48 hours
    max_login_attempts: int = 5
    lockout_duration_seconds: int = 900  # 15 minutes
    allowed_hosts: List[str] = field(default_factory=lambda: ["127.0.0.1", "localhost", "[::1]"])

    @classmethod
    def from_env(cls) -> RemoteControlConfig:
        host = os.environ.get("REMOTE_CONTROL_HOST", "127.0.0.1")
        port = int(os.environ.get("REMOTE_CONTROL_PORT", "8443"))

        env_secure = os.environ.get("REMOTE_CONTROL_COOKIE_SECURE")
        is_prod = os.environ.get("REMOTE_CONTROL_ENV", "").lower() == "production"
        cookie_secure = (env_secure == "1") or is_prod

        allowed = ["127.0.0.1", "localhost", "[::1]"]
        extra_hosts = os.environ.get("REMOTE_CONTROL_ALLOWED_HOSTS")
        if extra_hosts:
            for h in extra_hosts.split(","):
                clean = h.strip()
                if clean and clean not in allowed:
                    allowed.append(clean)

        return cls(
            host=host,
            port=port,
            cookie_secure=cookie_secure,
            allowed_hosts=allowed,
        )
