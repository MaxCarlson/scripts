"""Secure configuration management for independent off-host outage monitoring."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from notifications.config import _secure_path, default_token_path
from notifications.exceptions import SecurityError, ValidationError

logger = logging.getLogger(__name__)

# UUID or slug in Healthchecks ping URLs
_PING_URL_UUID_RE = re.compile(
    r"(https?://[^/\s]+(?:/ping)?/)([a-f0-9-]{16,64}|[A-Za-z0-9_-]{16,64})",
    re.IGNORECASE,
)
_RAW_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def redact_ping_url(text: str) -> str:
    """Safely redact Healthchecks secret ping URLs and UUIDs from text, logs, and traces."""
    if not text:
        return ""
    # Redact URL with token
    redacted = _PING_URL_UUID_RE.sub(r"\1[REDACTED_PING_UUID]", text)
    # Redact any standalone raw UUIDs
    redacted = _RAW_UUID_RE.sub("[REDACTED_UUID]", redacted)
    return redacted


class _PingUrlRedactingFilter(logging.Filter):
    """Ensure httpx/httpcore logs never emit unredacted Healthchecks ping URLs."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            raw_msg = record.getMessage()
            sanitized = redact_ping_url(raw_msg)
            if sanitized != raw_msg:
                record.msg = sanitized
                record.args = ()
        except Exception:
            pass
        return True


_PING_FILTER = _PingUrlRedactingFilter()
for _lg_name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection", "heartbeat-runner"):
    _lg = logging.getLogger(_lg_name)
    if _PING_FILTER not in _lg.filters:
        _lg.addFilter(_PING_FILTER)


def default_healthchecks_config_path() -> Path:
    """Default secure path for Healthchecks configuration."""
    override = os.environ.get("NOTIFY_HEALTHCHECKS_SECRETS_FILE")
    if override:
        return Path(override).expanduser().resolve()
    return default_token_path().parent / "healthchecks.json"


@dataclass(frozen=True)
class HealthchecksConfig:
    """Configuration for independent off-host outage heartbeat monitoring."""

    ping_url: str
    interval_minutes: int = 5
    check_name: str = "Host Alive"
    created_at: Optional[str] = None

    def __post_init__(self) -> None:
        url = self.ping_url.strip()
        parsed = urlparse(url)

        # Allow HTTP only if explicitly permitted for automated local testing
        allow_insecure = os.environ.get("NOTIFICATIONS_ALLOW_INSECURE_PING") == "1"
        if not allow_insecure and parsed.scheme.lower() != "https":
            raise ValidationError("Healthchecks ping URL must use verified HTTPS scheme.")

        if not parsed.netloc:
            raise ValidationError("Invalid Healthchecks ping URL: missing host authority.")

        if "@" in parsed.netloc:
            raise ValidationError("Healthchecks ping URL must not embed user credentials.")

        if self.interval_minutes < 1 or self.interval_minutes > 60:
            raise ValidationError(
                f"Heartbeat interval ({self.interval_minutes}m) must be between 1 and 60 minutes."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ping_url": self.ping_url,
            "interval_minutes": self.interval_minutes,
            "check_name": self.check_name,
            "created_at": self.created_at
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HealthchecksConfig:
        return cls(
            ping_url=str(data["ping_url"]),
            interval_minutes=int(data.get("interval_minutes", 5)),
            check_name=str(data.get("check_name", "Host Alive")),
            created_at=data.get("created_at"),
        )


def load_healthchecks_config(path: Optional[Path] = None) -> Optional[HealthchecksConfig]:
    """Load and validate Healthchecks configuration from environment or secured file."""
    # 1. Environment variable override
    env_url = os.environ.get("NOTIFY_HEALTHCHECKS_PING_URL")
    if env_url:
        env_interval = int(os.environ.get("NOTIFY_HEALTHCHECKS_INTERVAL", "5"))
        env_name = os.environ.get("NOTIFY_HEALTHCHECKS_CHECK_NAME", "Host Alive")
        return HealthchecksConfig(
            ping_url=env_url.strip(),
            interval_minutes=env_interval,
            check_name=env_name.strip(),
        )

    # 2. Secured configuration file
    file_path = path or default_healthchecks_config_path()
    if not file_path.is_file():
        return None

    # Enforce permissions on existing configuration
    _secure_path(file_path)

    try:
        content = file_path.read_text("utf-8").strip()
        data = json.loads(content)
        return HealthchecksConfig.from_dict(data)
    except Exception as exc:
        logger.warning("Failed to load Healthchecks configuration from %s: %s", file_path, exc)
        return None


def save_healthchecks_config(
    config: HealthchecksConfig,
    path: Optional[Path] = None,
) -> Path:
    """Save Healthchecks configuration with owner-restricted filesystem ACLs using fail-secure atomic replacement."""
    import tempfile

    file_path = (path or default_healthchecks_config_path()).resolve()

    # Reject symbolic links and reparse points
    if file_path.is_symlink():
        raise SecurityError(f"Refusing to save configuration to symbolic link: {file_path}")

    parent_dir = file_path.parent
    if parent_dir.is_symlink():
        raise SecurityError(f"Refusing to save configuration in symbolic link directory: {parent_dir}")

    parent_dir.mkdir(parents=True, exist_ok=True)
    _secure_path(parent_dir)

    content = json.dumps(config.to_dict(), indent=2)

    # Write to unpredictable temporary file in same directory for atomic rename
    temp_fd, temp_path_str = tempfile.mkstemp(
        dir=parent_dir,
        prefix=".tmp_healthchecks_",
        suffix=".json",
    )
    temp_path = Path(temp_path_str)

    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            f.write(content)

        # Apply and verify owner-only permissions on the temporary file BEFORE moving into destination
        _secure_path(temp_path)

        # Atomically replace destination, preserving previous file if anything prior failed
        os.replace(temp_path, file_path)
        return file_path
    except Exception:
        # Fail-secure cleanup
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise


def delete_healthchecks_config(path: Optional[Path] = None) -> bool:
    """Revoke and delete Healthchecks configuration file."""
    file_path = path or default_healthchecks_config_path()
    if file_path.is_file():
        try:
            file_path.unlink()
            return True
        except Exception as exc:
            logger.warning("Failed to remove Healthchecks config file: %s", exc)
            return False
    return False
