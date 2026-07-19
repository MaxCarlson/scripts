from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .models import InputUrl

_NHENTAI = re.compile(r"^(?:https?://(?:www\.)?nhentai\.net/g/)?(\d+)/?$", re.IGNORECASE)
_HTTP_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_LIST_PREFIX = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")


def canonicalize_url(value: str) -> str:
    value = value.strip()
    if match := _NHENTAI.fullmatch(value):
        return f"https://nhentai.net/g/{match.group(1)}/"
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"not a supported HTTP URL: {value}")
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _strip_comment(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", ";")):
        return ""
    for marker in ("  #", "  ;"):
        if marker in line:
            line = line.split(marker, 1)[0]
    return line.strip()


def _extract_input_value(line: str) -> str:
    """Extract a URL or ID from plain, numbered, bulleted, or pasted text."""
    value = _strip_comment(line)
    if not value:
        return ""
    if match := _HTTP_URL.search(value):
        return match.group(0).rstrip(".,)]}")
    if match := _LIST_PREFIX.fullmatch(value):
        return match.group(1).strip()
    return value


def collect_inputs(files: list[Path], urls: list[str]) -> tuple[list[InputUrl], list[dict[str, object]]]:
    found: list[InputUrl] = []
    rejected: list[dict[str, object]] = []
    seen: set[str] = set()
    values: list[tuple[str, str, int]] = [(url, "<cli>", num) for num, url in enumerate(urls, 1)]
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        values.extend((line, str(path), number) for number, line in enumerate(text.splitlines(), 1))
    for raw, source, line in values:
        value = _extract_input_value(raw)
        if not value:
            continue
        try:
            canonical = canonicalize_url(value)
        except ValueError as exc:
            rejected.append({"value": value, "source": source, "line": line, "reason": str(exc)})
            continue
        if canonical in seen:
            rejected.append({"value": value, "source": source, "line": line, "reason": "duplicate"})
            continue
        seen.add(canonical)
        found.append(InputUrl(value, canonical, source, line))
    return found, rejected
