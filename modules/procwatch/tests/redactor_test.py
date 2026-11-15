"""Unit tests for procwatch.redactor."""

from __future__ import annotations

from procwatch.redactor import REDACTED_TOKEN, REDACTION_ERROR_STUB, Redactor, escape_control_chars, redact_dict, redact_text


def test_redact_cli_flags_and_tokens() -> None:
    cmd = (
        "python.exe sync.py --password=my_secret_pw --token ghp_1234567890abcdef123456 "
        "/token:tok_val -key:key_val https://alice:s3cr3tPass@example.com/api"
    )
    out = redact_text(cmd)
    assert out is not None
    for secret in ("my_secret_pw", "ghp_1234567890abcdef123456", "tok_val", "key_val", "s3cr3tPass"):
        assert secret not in out
    assert out.count(REDACTED_TOKEN) >= 5


def test_redact_bearer_and_provider_prefixes() -> None:
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 key=AIzaSyDummyKeyValue1234567890"
    out = redact_text(text)
    assert out is not None
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in out
    assert "AIzaSyDummyKeyValue1234567890" not in out


def test_redact_dict_recursive() -> None:
    payload = {
        "cmd": "tool.exe --api-key sk-secret1234567890abcdef",
        "nested": [{"password": "hunter2"}],
    }
    res = redact_dict(payload)
    assert "sk-secret1234567890abcdef" not in res["cmd"]
    assert res["nested"][0]["password"] == REDACTED_TOKEN


def test_fail_closed_redaction_on_bad_pattern() -> None:
    class _BrokenPattern:
        def sub(self, *_args: object) -> str:
            raise RuntimeError("boom")

    r = Redactor(extra_patterns=(_BrokenPattern(),))  # type: ignore[arg-type]
    assert r.redact_text("sensitive") == REDACTION_ERROR_STUB


def test_escape_control_chars() -> None:
    assert escape_control_chars("a\x00b\nc\x1fd") == "a\\x00b\\nc\\x1fd"
