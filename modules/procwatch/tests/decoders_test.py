"""Unit tests for procwatch.correlator.decoders."""

from __future__ import annotations

import base64

from procwatch.correlator.decoders import decode_command_payload
from procwatch.redactor import REDACTED_TOKEN


def _b64_utf16le(text: str) -> str:
    return base64.b64encode(text.encode("utf-16-le")).decode("ascii")


def test_decode_powershell_encoded_command_utf16le() -> None:
    inner = "Write-Host 'hello'; Invoke-RestMethod -Headers @{Authorization='Bearer secret_token_12345'}"
    cmdline = f"powershell.exe -NoProfile -EncodedCommand {_b64_utf16le(inner)}"
    res = decode_command_payload(cmdline)
    assert res is not None
    assert res.wrapper_type == "powershell_encoded"
    assert res.error is None
    assert "Write-Host 'hello'" in (res.redacted_text or "")
    assert "secret_token_12345" not in (res.redacted_text or "")
    assert REDACTED_TOKEN in (res.redacted_text or "")


def test_decode_nested_cmd_and_powershell_encoded() -> None:
    inner = "python.exe worker.py --api-key=sk-proj1234567890abcdef"
    ps_cmd = f"pwsh.exe -enc {_b64_utf16le(inner)}"
    cmdline = f'cmd.exe /c "{ps_cmd}"'
    res = decode_command_payload(cmdline)
    assert res is not None
    assert res.wrapper_type == "cmd_wrapper>powershell_encoded"
    assert res.layers == 2
    assert "sk-proj1234567890abcdef" not in (res.redacted_text or "")
    assert REDACTED_TOKEN in (res.redacted_text or "")


def test_decode_invalid_base64_and_odd_utf16_handled_safely() -> None:
    res_bad = decode_command_payload("powershell.exe -EncodedCommand !!!not_base64!!!")
    assert res_bad is None  # regex does not match non-base64 chars

    # Valid base64 but odd number of bytes (cannot be valid UTF-16LE)
    odd_b64 = base64.b64encode(b"abc").decode("ascii")
    res_odd = decode_command_payload(f"powershell.exe -EncodedCommand {odd_b64}")
    assert res_odd is not None
    assert res_odd.error == "invalid_utf16le_odd_byte_length"
    assert res_odd.redacted_text is None


def test_decode_wsl_exec_and_control_char_escaping() -> None:
    res = decode_command_payload("wsl.exe -d Ubuntu -e bash -lc 'echo hi\x00\x07'")
    assert res is not None
    assert res.wrapper_type == "wsl_exec"
    assert "\\x00" in (res.redacted_text or "")
    assert "\\x07" in (res.redacted_text or "")


def test_decode_non_wrapper_returns_none() -> None:
    assert decode_command_payload(None) is None
    assert decode_command_payload("") is None
    assert decode_command_payload("python.exe script.py --verbose") is None
