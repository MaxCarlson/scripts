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
    allowed_origins: List[str] = field(default_factory=list)
    trusted_proxies: List[str] = field(default_factory=lambda: ["127.0.0.1", "::1"])
    public_origin: Optional[str] = None
    allowed_public_hosts: List[str] = field(default_factory=list)
    trusted_proxy_peers: List[str] = field(default_factory=lambda: ["127.0.0.1", "::1"])
    cookie_security_mode: str = "auto"
    external_exposure_enabled: bool = False
    public_action_policy: str = "conservative"

    def __post_init__(self) -> None:
        if self.public_origin and not self.allowed_public_hosts:
            from urllib.parse import urlparse
            p_host = urlparse(self.public_origin).hostname
            if p_host:
                object.__setattr__(self, "allowed_public_hosts", [p_host])

        combined_hosts = list(self.allowed_hosts)
        for h in self.allowed_public_hosts:
            if h and h not in combined_hosts:
                combined_hosts.append(h)
        object.__setattr__(self, "allowed_hosts", combined_hosts)

        combined_origins = list(self.allowed_origins)
        if self.public_origin and self.public_origin not in combined_origins:
            combined_origins.append(self.public_origin)
        object.__setattr__(self, "allowed_origins", combined_origins)

        combined_proxies = list(self.trusted_proxies)
        for p in self.trusted_proxy_peers:
            if p and p not in combined_proxies:
                combined_proxies.append(p)
        object.__setattr__(self, "trusted_proxies", combined_proxies)
        object.__setattr__(self, "trusted_proxy_peers", combined_proxies)

        if self.external_exposure_enabled:
            object.__setattr__(self, "cookie_security_mode", "strict")
            object.__setattr__(self, "cookie_secure", True)
        elif self.cookie_security_mode == "strict":
            object.__setattr__(self, "cookie_secure", True)

    @classmethod
    def from_env(cls) -> RemoteControlConfig:
        host = os.environ.get("REMOTE_CONTROL_HOST", "127.0.0.1")
        port = int(os.environ.get("REMOTE_CONTROL_PORT", "8443"))

        external_exposure = os.environ.get("REMOTE_CONTROL_EXTERNAL_EXPOSURE", "0").lower() in ("1", "true", "yes")
        public_origin = os.environ.get("REMOTE_CONTROL_PUBLIC_ORIGIN")
        cookie_mode = os.environ.get("REMOTE_CONTROL_COOKIE_SECURITY_MODE", "auto")
        action_policy = os.environ.get("REMOTE_CONTROL_PUBLIC_ACTION_POLICY", "conservative")

        env_secure = os.environ.get("REMOTE_CONTROL_COOKIE_SECURE")
        is_prod = os.environ.get("REMOTE_CONTROL_ENV", "").lower() == "production"
        if env_secure is not None:
            cookie_secure = env_secure.lower() in ("1", "true", "yes")
        else:
            cookie_secure = is_prod or external_exposure or (cookie_mode == "strict")

        allowed = ["127.0.0.1", "localhost", "[::1]"]
        extra_hosts = os.environ.get("REMOTE_CONTROL_ALLOWED_HOSTS")
        if extra_hosts:
            for h in extra_hosts.split(","):
                clean = h.strip()
                if clean and clean not in allowed:
                    allowed.append(clean)

        allowed_public_hosts: List[str] = []
        extra_pub_hosts = os.environ.get("REMOTE_CONTROL_ALLOWED_PUBLIC_HOSTS")
        if extra_pub_hosts:
            allowed_public_hosts = [h.strip() for h in extra_pub_hosts.split(",") if h.strip()]

        allowed_origins: List[str] = []
        extra_origins = os.environ.get("REMOTE_CONTROL_ALLOWED_ORIGINS")
        if extra_origins:
            for o in extra_origins.split(","):
                clean = o.strip()
                if clean and clean not in allowed_origins:
                    allowed_origins.append(clean)

        trusted_proxies = ["127.0.0.1", "::1"]
        extra_proxies = os.environ.get("REMOTE_CONTROL_TRUSTED_PROXIES")
        if extra_proxies:
            trusted_proxies = [p.strip() for p in extra_proxies.split(",") if p.strip()]

        trusted_proxy_peers = list(trusted_proxies)
        extra_peers = os.environ.get("REMOTE_CONTROL_TRUSTED_PROXY_PEERS")
        if extra_peers:
            trusted_proxy_peers = [p.strip() for p in extra_peers.split(",") if p.strip()]

        return cls(
            host=host,
            port=port,
            cookie_secure=cookie_secure,
            allowed_hosts=allowed,
            allowed_origins=allowed_origins,
            trusted_proxies=trusted_proxies,
            public_origin=public_origin,
            allowed_public_hosts=allowed_public_hosts,
            trusted_proxy_peers=trusted_proxy_peers,
            cookie_security_mode=cookie_mode,
            external_exposure_enabled=external_exposure,
            public_action_policy=action_policy,
        )
