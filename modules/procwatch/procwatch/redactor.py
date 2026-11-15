"""Pre-output and pre-persistence secret redaction utilities for ProcWatch."""

from __future__ import annotations

import re
from typing import Any

REDACTED_TOKEN = "[REDACTED]"
REDACTION_ERROR_STUB = "[REDACTION_ERROR:DROPPED]"

# Compiled redaction rules: (name, pattern, replacement)
_DEFAULT_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    # Authorization headers / Bearer tokens
    (
        "bearer_token",
        re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-+/=]{8,}"),
        rf"\1{REDACTED_TOKEN}",
    ),
    # URI userinfo: scheme://user:password@host
    (
        "uri_userinfo",
        re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://[^:/@\s]+:)([^@\s]+)(@)"),
        rf"\1{REDACTED_TOKEN}\3",
    ),
    # Known provider token prefixes
    (
        "known_prefixes",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_\-]{12,}|gh[pousr]_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z\-_]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,})\b"
        ),
        REDACTED_TOKEN,
    ),
    # CLI flags with = or space: --password=foo, --token foo, /token:foo, -key:foo
    (
        "cli_secret_flags",
        re.compile(
            r"(?i)((?:--?|/)(?:password|passwd|pwd|token|api[-_]?key|secret|client[-_]?secret|access[-_]?token|auth[-_]?token|key)\s*(?:=|:|\s+)\s*)(\"[^\"]*\"|'[^']*'|[^\s\"']+)"
        ),
        rf"\1{REDACTED_TOKEN}",
    ),
    # Key=value or Key: value in env/config/JSON strings
    (
        "kv_secrets",
        re.compile(
            r"(?i)(\b(?:password|passwd|secret|token|api_key|apikey|access_token|refresh_token|client_secret|aws_secret_access_key|github_token|openai_api_key|anthropic_api_key|gemini_api_key)\b\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;\"']+)"
        ),
        rf"\1{REDACTED_TOKEN}",
    ),
)


def escape_control_chars(text: str) -> str:
    """Escape NUL and non-printable control characters for safe terminal/JSONL display."""
    if not text:
        return ""
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch in ("\n", "\r", "\t"):
            out.append({"\\n": "\\n", "\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\x{code:02x}")
        else:
            out.append(ch)
    return "".join(out)


class Redactor:
    """Fail-closed secret redactor for command lines, decoded payloads, and log fields."""

    def __init__(self, extra_patterns: tuple[re.Pattern[str], ...] = ()) -> None:
        self._rules = _DEFAULT_RULES
        self._extra_patterns = extra_patterns

    def redact_text(self, text: str | None, *, escape_controls: bool = False) -> str | None:
        """Redact sensitive values from text. Fails closed on unexpected errors."""
        if text is None:
            return None
        try:
            result = str(text)
            for _name, pattern, replacement in self._rules:
                result = pattern.sub(replacement, result)
            for pattern in self._extra_patterns:
                result = pattern.sub(REDACTED_TOKEN, result)
            if escape_controls:
                result = escape_control_chars(result)
            return result
        except Exception:
            return REDACTION_ERROR_STUB

    def redact_value(self, value: Any) -> Any:
        """Recursively redact strings inside dicts, lists, and tuples."""
        sensitive_keys = {
            "password",
            "passwd",
            "pwd",
            "secret",
            "token",
            "api_key",
            "apikey",
            "access_token",
            "refresh_token",
            "client_secret",
            "auth_token",
        }
        try:
            if isinstance(value, str):
                return self.redact_text(value)
            if isinstance(value, dict):
                out: dict[Any, Any] = {}
                for k, v in value.items():
                    if isinstance(k, str) and k.lower() in sensitive_keys and isinstance(v, str) and v:
                        out[k] = REDACTED_TOKEN
                    else:
                        out[k] = self.redact_value(v)
                return out
            if isinstance(value, list):
                return [self.redact_value(item) for item in value]
            if isinstance(value, tuple):
                return tuple(self.redact_value(item) for item in value)
            return value
        except Exception:
            return REDACTION_ERROR_STUB


_DEFAULT_REDACTOR = Redactor()


def redact_text(text: str | None, *, escape_controls: bool = False) -> str | None:
    """Convenience wrapper using the default Redactor."""
    return _DEFAULT_REDACTOR.redact_text(text, escape_controls=escape_controls)


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Convenience wrapper to redact a dictionary recursively."""
    redacted = _DEFAULT_REDACTOR.redact_value(data)
    return redacted if isinstance(redacted, dict) else {"error": REDACTION_ERROR_STUB}
