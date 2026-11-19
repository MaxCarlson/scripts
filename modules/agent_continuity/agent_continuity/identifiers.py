"""Identifier generation, validation, and URL/path normalization helpers."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlparse, urlunparse

from .errors import ContinuityError, ErrorCode

_WORKFLOW_ID_RE = re.compile(r"^wf_[0-9a-f]{6,16}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CHATGPT_HOSTS = {"chatgpt.com", "www.chatgpt.com", "chat.openai.com"}
_CHATGPT_CONV_RE = re.compile(r"^(?:/g/[^/]+)?/c/([A-Za-z0-9-]+)/*$")
_WINDOWS_DRIVE_RE = re.compile(r"^([A-Za-z]):(?:[\\/](.*))?$")
_WSL_MNT_RE = re.compile(r"^/mnt/([a-zA-Z])(?:/(.*))?$")


def now_utc_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format with microsecond precision."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def generate_workflow_id(existing_ids: set[str] | None = None) -> str:
    """Generate a unique immutable workflow ID (e.g., wf_7d3a92)."""
    taken = existing_ids or set()
    for nbytes in (3, 3, 3, 4, 5):
        candidate = f"wf_{secrets.token_hex(nbytes)}"
        if candidate not in taken:
            return candidate
    return f"wf_{secrets.token_hex(8)}"


def generate_id(prefix: str) -> str:
    """Generate a unique prefixed identifier."""
    return f"{prefix}_{secrets.token_hex(6)}"


def is_workflow_id(value: str) -> bool:
    """Return True if value matches the immutable workflow ID format."""
    return bool(_WORKFLOW_ID_RE.match(value.strip()))


def validate_slug(raw_slug: str) -> str:
    """Validate and normalize a human-readable workflow slug."""
    slug = raw_slug.strip().lower()
    if not slug or not _SLUG_RE.match(slug):
        raise ContinuityError(
            ErrorCode.INVALID_INPUT,
            f"Invalid workflow slug {raw_slug!r}. Use 1-64 lowercase alphanumeric, '-', or '_' characters.",
            {"slug": raw_slug},
        )
    if slug.startswith("wf_"):
        raise ContinuityError(
            ErrorCode.INVALID_INPUT,
            f"Workflow slug {raw_slug!r} cannot start with reserved prefix 'wf_'.",
            {"slug": raw_slug},
        )
    return slug


def normalize_gui_url(raw_url: str) -> tuple[str, str]:
    """Validate a GUI URL and return (trimmed_url, canonical_url)."""
    cleaned = raw_url.strip()
    if not cleaned:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "GUI conversation URL cannot be empty.")
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ContinuityError(
            ErrorCode.INVALID_INPUT,
            f"Invalid GUI URL {raw_url!r}. Expected an http:// or https:// URL.",
            {"url": raw_url},
        )
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    if host in _CHATGPT_HOSTS:
        match = _CHATGPT_CONV_RE.match(path)
        if match:
            canonical_path = f"/c/{match.group(1)}"
            canonical = urlunparse(("https", "chatgpt.com", canonical_path, "", "", ""))
            return cleaned, canonical
    stripped_path = path.rstrip("/") or "/"
    canonical = urlunparse((parsed.scheme.lower(), host, stripped_path, "", parsed.query, ""))
    return cleaned, canonical


def normalize_path_canonical(raw_path: str | None) -> str | None:
    """
    Normalize a Windows, WSL /mnt/<drive>, or POSIX path into a comparable canonical string.

    Does not require the target path to exist on the current runtime filesystem.
    """
    if raw_path is None:
        return None
    text = raw_path.strip()
    if not text:
        return None

    win_match = _WINDOWS_DRIVE_RE.match(text)
    if win_match:
        drive = win_match.group(1).lower()
        rest = PureWindowsPath(text).as_posix()
        # Convert C:/Users/Foo -> /mnt/c/users/foo? Keep case-preserved tail with lowercase drive root for clarity:
        # Canonical form uses POSIX drive form: win:/c/Users/Foo (or /mnt/c/...) so WSL and Windows match cleanly.
        tail = rest[2:].lstrip("/")
        return f"/{drive}:/{tail}".rstrip("/") if tail else f"/{drive}:"

    wsl_match = _WSL_MNT_RE.match(text)
    if wsl_match:
        drive = wsl_match.group(1).lower()
        tail = (wsl_match.group(2) or "").strip("/")
        return f"/{drive}:/{tail}".rstrip("/") if tail else f"/{drive}:"

    posix = PurePosixPath(text.replace("\\", "/")).as_posix()
    return posix.rstrip("/") or "/"


def normalize_repo_identity(repo_path: str | None) -> str | None:
    """Derive a comparable repository identity string from a path or explicit repo name."""
    if repo_path is None:
        return None
    text = repo_path.strip()
    if not text:
        return None
    canonical = normalize_path_canonical(text)
    if canonical is None:
        return None
    # On Windows/NTFS drive paths, normalize case so C:\Src\Scripts and c:/src/scripts compare identically.
    if re.match(r"^/[a-z]:", canonical):
        return canonical.lower()
    return canonical
