"""Safe, bounded command-line payload decoders (never executes decoded text)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import re

from procwatch.redactor import escape_control_chars, redact_text

# Match PowerShell -EncodedCommand / -enc / -e <base64> (requires powershell/pwsh executable)
_PS_ENC_RE = re.compile(
    r"(?:^|\s)(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\b.*?\s-(?:e|ec|enc|encodedcommand)\s+([A-Za-z0-9+/=]{4,})",
    re.IGNORECASE,
)
_PS_ENC_FLAG_ONLY_RE = re.compile(
    r"(?:^|\s)-(?:enc|encodedcommand)\s+([A-Za-z0-9+/=]{8,})(?:\s|$)",
    re.IGNORECASE,
)
_CMD_WRAPPER_RE = re.compile(
    r"^\s*(?:\"[^\"]*\\cmd(?:\.exe)?\"|cmd(?:\.exe)?)\s+/[ck]\s+(.+)$",
    re.IGNORECASE,
)
_PS_CMD_WRAPPER_RE = re.compile(
    r"^\s*(?:\"[^\"]*\\(?:powershell|pwsh)(?:\.exe)?\"|(?:powershell|pwsh)(?:\.exe)?)\b.*?\s-(?:c|command)\s+(.+)$",
    re.IGNORECASE,
)
_WSL_WRAPPER_RE = re.compile(
    r"^\s*(?:\"[^\"]*\\wsl(?:\.exe)?\"|wsl(?:\.exe)?)\b.*?\s(?:-e|--exec)\s+(.+)$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class DecodedPayload:
    """Result of safe command-line payload unwrapping."""

    wrapper_type: str
    raw_decoded: str | None
    redacted_text: str | None
    truncated: bool = False
    error: str | None = None
    layers: int = 0


def _decode_ps_base64(b64_str: str, max_bytes: int) -> tuple[str | None, bool, str | None]:
    """Decode PowerShell UTF-16LE Base64 string safely with size bounds."""
    cleaned = b64_str.strip()
    # Pad base64 if unpadded
    pad_len = (-len(cleaned)) % 4
    if pad_len:
        cleaned = cleaned + ("=" * pad_len)
    try:
        raw_bytes = base64.b64decode(cleaned, validate=True)
    except Exception as exc:
        return None, False, f"invalid_base64: {exc}"

    truncated = False
    if len(raw_bytes) > max_bytes:
        raw_bytes = raw_bytes[: max_bytes - (max_bytes % 2)]
        truncated = True

    if len(raw_bytes) % 2 != 0:
        return None, truncated, "invalid_utf16le_odd_byte_length"

    try:
        decoded = raw_bytes.decode("utf-16-le")
    except UnicodeDecodeError as exc:
        return None, truncated, f"invalid_utf16le: {exc}"

    return decoded, truncated, None


def _strip_outer_quotes(text: str) -> str:
    s = text.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def decode_command_payload(
    cmdline: str | None,
    *,
    max_bytes: int = 16384,
    max_depth: int = 3,
) -> DecodedPayload | None:
    """Safely unwrap cmd /c, PowerShell -EncodedCommand/-Command, and wsl -e wrappers.

    Never executes any decoded text. Always redacts secrets and escapes control chars.
    """
    if not cmdline or not cmdline.strip():
        return None

    current = cmdline[:max_bytes]
    truncated = len(cmdline) > max_bytes
    wrapper_types: list[str] = []
    last_error: str | None = None
    layers = 0

    for _ in range(max_depth):
        # 1. PowerShell -EncodedCommand
        m_ps = _PS_ENC_RE.search(current) or _PS_ENC_FLAG_ONLY_RE.search(current)
        if m_ps:
            decoded, dec_trunc, err = _decode_ps_base64(m_ps.group(1), max_bytes)
            truncated = truncated or dec_trunc
            if err is not None:
                last_error = err
                wrapper_types.append("powershell_encoded")
                break
            assert decoded is not None
            wrapper_types.append("powershell_encoded")
            current = decoded
            layers += 1
            continue

        # 2. cmd.exe /c or /k
        m_cmd = _CMD_WRAPPER_RE.match(current)
        if m_cmd:
            wrapper_types.append("cmd_wrapper")
            current = _strip_outer_quotes(m_cmd.group(1))
            layers += 1
            continue

        # 3. powershell/pwsh -Command
        m_ps_cmd = _PS_CMD_WRAPPER_RE.match(current)
        if m_ps_cmd:
            wrapper_types.append("powershell_command")
            current = _strip_outer_quotes(m_ps_cmd.group(1))
            layers += 1
            continue

        # 4. wsl -e / --exec
        m_wsl = _WSL_WRAPPER_RE.match(current)
        if m_wsl:
            wrapper_types.append("wsl_exec")
            current = m_wsl.group(1).strip()
            layers += 1
            continue

        break

    if not wrapper_types:
        return None

    if last_error and layers == 0:
        return DecodedPayload(
            wrapper_type=">".join(wrapper_types),
            raw_decoded=None,
            redacted_text=None,
            truncated=truncated,
            error=last_error,
            layers=0,
        )

    redacted = redact_text(current, escape_controls=True)
    safe_raw = escape_control_chars(current)
    return DecodedPayload(
        wrapper_type=">".join(wrapper_types),
        raw_decoded=safe_raw,
        redacted_text=redacted,
        truncated=truncated,
        error=last_error,
        layers=layers,
    )
