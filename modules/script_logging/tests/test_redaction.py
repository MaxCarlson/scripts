from __future__ import annotations

import json
from script_logging.redaction import (
    compute_pattern_id,
    normalize_argv_json,
    redact_argv,
)


def test_redact_sensitive_flags_equals_and_spaced():
    argv = (
        "mytool",
        "--token=ghp_secret123",
        "--password",
        "supersecret",
        "--api-key",
        "key987",
        "-p",
        "8080",  # Legitimate port option must NOT be redacted
        "--path",
        "/usr/bin",
        "https://user:pass@example.com/api?token=abc&page=2",
    )
    redacted, is_redacted = redact_argv(argv)
    assert is_redacted is True
    assert "--token=[REDACTED]" in redacted
    assert "supersecret" not in redacted
    assert "key987" not in redacted
    assert "-p" in redacted and "8080" in redacted
    assert "--path" in redacted and "/usr/bin" in redacted
    # URL userinfo and sensitive query param redacted
    assert "https://user:[REDACTED]@example.com/api?token=[REDACTED]&page=2" in redacted


def test_redact_other_sensitive_flags():
    argv = (
        "tool",
        "--passwd=secret1",
        "--secret",
        "secret2",
        "--apikey",
        "key1",
        "--auth=bearer_tok",
        "--access-token",
        "tok1",
        "--bearer",
        "tok2",
        "--key=sec_key",
        "--header",
        "Authorization: Bearer 123",
        "--cookie",
        "sess=abc",
    )
    redacted, is_redacted = redact_argv(argv)
    assert is_redacted is True
    assert "--passwd=[REDACTED]" in redacted
    assert "--auth=[REDACTED]" in redacted
    assert "--key=[REDACTED]" in redacted
    for val in ["secret1", "secret2", "key1", "bearer_tok", "tok1", "tok2", "sec_key"]:
        assert val not in redacted


def test_redact_clean_argv_unchanged():
    argv = ("git", "status", "--short", "-v")
    redacted, is_redacted = redact_argv(argv)
    assert is_redacted is False
    assert redacted == argv


def test_redact_truncation():
    huge_argv = tuple(["arg"] * 300)
    redacted, is_redacted = redact_argv(huge_argv, max_args=100)
    assert is_redacted is True
    assert len(redacted) == 101
    assert redacted[-1] == "[TRUNCATED:count=200]"


def test_redact_cmd_len_truncation():
    # Length truncation when characters exceed max_cmd_len
    long_arg = "a" * 100
    argv = ("echo", long_arg)
    redacted, is_redacted = redact_argv(argv, max_cmd_len=50)
    assert is_redacted is True
    assert any("[TRUNCATED:" in arg for arg in redacted)


def test_pattern_id_deterministic():
    p1 = compute_pattern_id("module:mangadl", ("mangadl", "dl", "--quality", "high"))
    p2 = compute_pattern_id("module:mangadl", ("mangadl", "dl", "--quality", "high"))
    p3 = compute_pattern_id("module:compresser", ("compresser", "dl", "--quality", "high"))
    assert p1 == p2
    assert p1 != p3
    assert len(p1) > 0


def test_normalize_argv_json():
    argv = ("mangadl", "dl", "--quality", "high")
    normalized = normalize_argv_json(argv)
    assert json.loads(normalized) == ["mangadl", "dl", "--quality", "high"]
