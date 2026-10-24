"""Privacy filtering, credential sanitization, URL scrubbing, and argument truncation."""
from __future__ import annotations

import hashlib
import json
import urllib.parse
from typing import List, Tuple

SENSITIVE_FLAG_NAMES = {
    "token",
    "password",
    "passwd",
    "secret",
    "api-key",
    "apikey",
    "auth",
    "access-token",
    "bearer",
    "key",
    "header",
    "cookie",
}

SENSITIVE_SUFFIXES = (
    "-token",
    "-password",
    "-passwd",
    "-secret",
    "-api-key",
    "-apikey",
)

SENSITIVE_QUERY_PARAMS = {
    "token",
    "key",
    "secret",
    "auth",
    "pass",
    "password",
    "apikey",
    "api-key",
    "access-token",
}


def _is_sensitive_flag(flag: str) -> bool:
    """Check if a flag name matches sensitive credential patterns."""
    if not (flag.startswith("-") or flag.startswith("/")):
        return False
    name = flag.lstrip("-/").lower().replace("_", "-")
    if name in SENSITIVE_FLAG_NAMES:
        return True
    return any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)


def _redact_url(arg: str) -> Tuple[str, bool]:
    """Scrub userinfo password and sensitive query parameters from a URL."""
    if "://" not in arg:
        return arg, False

    try:
        parsed = urllib.parse.urlsplit(arg)
    except Exception:
        return arg, False

    if not (parsed.scheme and parsed.netloc):
        return arg, False

    modified = False
    new_netloc = parsed.netloc

    # Check for credentials in userinfo
    if "@" in parsed.netloc:
        userinfo, at, hostpart = parsed.netloc.rpartition("@")
        if ":" in userinfo:
            user, _, _ = userinfo.partition(":")
            new_userinfo = f"{user}:[REDACTED]"
            new_netloc = f"{new_userinfo}{at}{hostpart}"
            modified = True
        else:
            new_userinfo = "[REDACTED]"
            new_netloc = f"{new_userinfo}{at}{hostpart}"
            modified = True

    # Check for sensitive query parameters
    new_query = parsed.query
    if parsed.query:
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        new_pairs: List[str] = []
        for k, v in pairs:
            k_norm = k.lower().replace("_", "-")
            if k_norm in SENSITIVE_QUERY_PARAMS or any(k_norm.endswith(s) for s in ("-token", "-key", "-secret")):
                new_pairs.append(f"{k}=[REDACTED]")
                modified = True
            else:
                new_pairs.append(f"{k}={v}")
        new_query = "&".join(new_pairs)

    if modified:
        return urllib.parse.urlunsplit((parsed.scheme, new_netloc, parsed.path, new_query, parsed.fragment)), True
    return arg, False


def _apply_cmd_len_truncation(argv: List[str], max_cmd_len: int) -> Tuple[List[str], bool]:
    """Truncate arguments if cumulative command character length exceeds max_cmd_len."""
    total_len = sum(len(a) for a in argv) + max(0, len(argv) - 1)
    if total_len <= max_cmd_len:
        return argv, False

    result: List[str] = []
    current_len = 0

    for idx, arg in enumerate(argv):
        separator_len = 1 if result else 0
        if current_len + separator_len + len(arg) <= max_cmd_len:
            result.append(arg)
            current_len += separator_len + len(arg)
        else:
            available = max_cmd_len - current_len - separator_len
            marker_prefix = "[TRUNCATED:"
            if available > len(marker_prefix) + 12:
                keep_len = max(0, available - 22)
                excess = len(arg) - keep_len
                marker = f"[TRUNCATED:chars={excess}]"
                result.append(arg[:keep_len] + marker)
            else:
                excess_args = len(argv) - idx
                result.append(f"[TRUNCATED:count={excess_args}]")
            break

    return result, True


def redact_argv(
    argv: Tuple[str, ...],
    *,
    max_args: int = 256,
    max_cmd_len: int = 8192,
) -> Tuple[Tuple[str, ...], bool]:
    """Redact sensitive credentials, URLs, and apply explicit bounds truncation."""
    redacted: List[str] = []
    is_redacted = False
    redact_next = False

    for arg in argv:
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            is_redacted = True
            continue

        # Check for --flag=value
        if "=" in arg and (arg.startswith("-") or arg.startswith("/")):
            flag_part, eq, _ = arg.partition("=")
            if _is_sensitive_flag(flag_part):
                redacted.append(f"{flag_part}{eq}[REDACTED]")
                is_redacted = True
                continue

        # Check for --flag value (spaced)
        if _is_sensitive_flag(arg):
            redacted.append(arg)
            redact_next = True
            continue

        # Check for URL scrubbing
        url_scrubbed, url_modified = _redact_url(arg)
        if url_modified:
            redacted.append(url_scrubbed)
            is_redacted = True
            continue

        redacted.append(arg)

    # Max arguments count truncation
    if len(redacted) > max_args:
        excess_count = len(redacted) - max_args
        redacted = redacted[:max_args] + [f"[TRUNCATED:count={excess_count}]"]
        is_redacted = True

    # Max command character length truncation
    redacted, len_truncated = _apply_cmd_len_truncation(redacted, max_cmd_len)
    if len_truncated:
        is_redacted = True

    return tuple(redacted), is_redacted


def normalize_argv_json(redacted_argv: Tuple[str, ...]) -> str:
    """Serialize argv tuple to deterministic JSON format."""
    return json.dumps(list(redacted_argv), ensure_ascii=False)


def compute_pattern_id(program_id: str, redacted_argv: Tuple[str, ...]) -> str:
    """Calculate deterministic SHA-256 fingerprint for a program and command pattern."""
    payload = f"{program_id}\0{normalize_argv_json(redacted_argv)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
