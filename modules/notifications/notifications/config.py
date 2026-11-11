"""Configuration and credentials management for the notifications module."""

from __future__ import annotations

import os
import re
import secrets
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from notifications.exceptions import AuthenticationError, SecurityError

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,}$")


def default_db_path() -> Path:
    override = os.environ.get("NOTIFICATIONS_DB_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".scripts" / "notifications" / "events.db"


def default_token_path() -> Path:
    override = os.environ.get("NOTIFICATIONS_TOKEN_FILE")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".scripts" / "notifications" / "secrets" / "broker-token"


def _windows_user_sid() -> Optional[str]:
    try:
        result = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        match = re.search(r"S-1-[0-9-]+", result.stdout)
        return match.group(0) if match else None
    except Exception:
        return None


def _secure_path(path: Path) -> None:
    """Restrict path ACL to owner and LocalSystem on Windows; 0700/0600 on POSIX."""
    if os.name == "nt":
        sid = _windows_user_sid()
        if not sid:
            raise SecurityError(
                f"Cannot determine Windows user SID to secure '{path}'. "
                "Ensure whoami.exe is accessible or set NOTIFICATIONS_INGEST_TOKEN explicitly."
            )
        is_dir = path.is_dir()
        flags = ("(OI)(CI)" if is_dir else "") + "(F)"
        try:
            res_reset = subprocess.run(
                ["icacls.exe", str(path), "/reset"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res_reset.returncode != 0:
                err_detail = res_reset.stderr.strip() or res_reset.stdout.strip()
                raise SecurityError(
                    f"icacls /reset failed on '{path}': {err_detail}. "
                    "Repair filesystem permissions or run with appropriate Windows privileges."
                )

            res_grant = subprocess.run(
                [
                    "icacls.exe",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    f"*{sid}:{flags}",
                    f"*S-1-5-18:{flags}",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res_grant.returncode != 0:
                err_detail = res_grant.stderr.strip() or res_grant.stdout.strip()
                raise SecurityError(
                    f"icacls permission restriction failed on '{path}': {err_detail}. "
                    f"Run: icacls \"{path}\" /inheritance:r /grant:r \"*{sid}:{flags}\""
                )
        except subprocess.TimeoutExpired as exc:
            raise SecurityError(f"icacls timed out while securing '{path}'.") from exc
        except FileNotFoundError as exc:
            raise SecurityError(f"icacls.exe not found on PATH to secure '{path}'.") from exc
        except SecurityError:
            raise
        except Exception as exc:
            raise SecurityError(f"Unexpected error securing '{path}': {exc}") from exc
    else:
        try:
            path.chmod(0o700 if path.is_dir() else 0o600)
        except OSError as exc:
            raise SecurityError(f"Failed to set POSIX permissions on '{path}': {exc}") from exc


def load_or_create_token(token_file: Optional[Path] = None) -> str:
    """Load the configured ingest token or provision one securely."""
    env_token = os.environ.get("NOTIFICATIONS_INGEST_TOKEN")
    if env_token:
        token = env_token.strip()
        if not _TOKEN_RE.fullmatch(token):
            raise AuthenticationError("NOTIFICATIONS_INGEST_TOKEN environment variable contains invalid characters or length")
        return token

    path = token_file or default_token_path()
    if path.is_file():
        # Ensure existing token file and directory are securely permissioned
        _secure_path(path)
        try:
            token = path.read_text("ascii").strip()
            if _TOKEN_RE.fullmatch(token):
                return token
            raise AuthenticationError(f"Broker token in {path} has invalid format")
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(f"Cannot read broker token from {path}: {exc}") from exc

    # Generate new token
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _secure_path(path.parent)
        token = secrets.token_urlsafe(32)
        temp_file = path.with_name(f"{path.name}.new-{secrets.token_hex(4)}")
        temp_file.write_text(token, "ascii")
        _secure_path(temp_file)
        temp_file.replace(path)
        _secure_path(path)
        return token
    except SecurityError:
        raise
    except Exception as exc:
        raise AuthenticationError(f"Cannot provision broker token file at {path}: {exc}") from exc


@dataclass
class BrokerConfig:
    """Runtime configuration for notification broker and local ingestion."""

    db_path: Path = field(default_factory=default_db_path)
    token_file: Path = field(default_factory=default_token_path)
    host: str = "127.0.0.1"
    port: int = 1236
    auth_token: Optional[str] = None
    default_providers: list[str] = field(default_factory=lambda: ["fake_provider"])
    client_timeout_seconds: float = 2.0

    def get_token(self) -> str:
        if self.auth_token:
            return self.auth_token
        return load_or_create_token(self.token_file)
