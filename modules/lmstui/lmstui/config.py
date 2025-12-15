from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse


def _strip_trailing_slash(s: str) -> str:
    return s[:-1] if s.endswith("/") else s


def normalize_root_base_url(base_url: str) -> str:
    """
    Normalize user-provided base_url to a "root" like:
        http://host:1234
    Accepts:
        http://host:1234
        http://host:1234/v1
        http://host:1234/api/v0
    """
    base_url = base_url.strip()
    if not base_url:
        raise ValueError("base_url is empty")

    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid base_url: {base_url!r}")

    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    elif path.endswith("/api/v0"):
        path = path[: -len("/api/v0")]

    parsed = parsed._replace(path=path or "")
    return _strip_trailing_slash(urlunparse(parsed))


@dataclass(frozen=True)
class Config:
    base_url_root: str
    timeout_seconds: float = 60.0
    verify_tls: bool = True

    @property
    def rest_base(self) -> str:
        return f"{self.base_url_root}/api/v0"

    @property
    def openai_base(self) -> str:
        return f"{self.base_url_root}/v1"


def load_config(base_url: str | None, timeout_seconds: float | None) -> Config:
    env_base = os.environ.get("LMSTUI_BASE_URL", "").strip()
    env_timeout = os.environ.get("LMSTUI_TIMEOUT", "").strip()

    chosen_base = base_url or env_base or "http://localhost:1234"
    chosen_timeout = timeout_seconds
    if chosen_timeout is None and env_timeout:
        try:
            chosen_timeout = float(env_timeout)
        except ValueError:
            chosen_timeout = None
    if chosen_timeout is None:
        chosen_timeout = 60.0

    return Config(
        base_url_root=normalize_root_base_url(chosen_base),
        timeout_seconds=float(chosen_timeout),
    )
