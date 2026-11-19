"""Unit tests for identifier generation, validation, and URL/path normalization."""

from __future__ import annotations

import pytest

from agent_continuity.errors import ContinuityError, ErrorCode
from agent_continuity.identifiers import (
    generate_workflow_id,
    is_workflow_id,
    normalize_gui_url,
    normalize_path_canonical,
    normalize_repo_identity,
    validate_slug,
)


def test_generate_workflow_id_format_and_uniqueness() -> None:
    existing = {"wf_aaaaaa"}
    wf_id = generate_workflow_id(existing)
    assert is_workflow_id(wf_id)
    assert wf_id not in existing


def test_validate_slug_accepts_valid_and_rejects_invalid() -> None:
    assert validate_slug("  ProcWatch-Dev_1 ") == "procwatch-dev_1"
    for bad in ("", "wf_123456", "-bad", "has space", "bad/slash"):
        with pytest.raises(ContinuityError) as exc_info:
            validate_slug(bad)
        assert exc_info.value.code == ErrorCode.INVALID_INPUT


def test_normalize_gui_url_canonicalizes_chatgpt_and_rejects_bad_scheme() -> None:
    raw, canon = normalize_gui_url("  https://chat.openai.com/c/67890-abcd/?model=gpt5#bottom  ")
    assert raw == "https://chat.openai.com/c/67890-abcd/?model=gpt5#bottom"
    assert canon == "https://chatgpt.com/c/67890-abcd"

    raw_g, canon_g = normalize_gui_url("https://chatgpt.com/g/g-proj/c/abc-123/")
    assert raw_g == "https://chatgpt.com/g/g-proj/c/abc-123/"
    assert canon_g == "https://chatgpt.com/c/abc-123"

    with pytest.raises(ContinuityError) as exc_info:
        normalize_gui_url("ftp://chatgpt.com/c/123")
    assert exc_info.value.code == ErrorCode.INVALID_INPUT


def test_normalize_repo_identity_matches_windows_and_wsl_paths() -> None:
    win_norm = normalize_repo_identity(r"C:\Users\mcarls\Src\Scripts\\")
    wsl_norm = normalize_repo_identity("/mnt/c/users/mcarls/src/scripts/")
    assert win_norm == "/c:/users/mcarls/src/scripts"
    assert win_norm == wsl_norm
    assert normalize_path_canonical("/home/mcarls/src/scripts/") == "/home/mcarls/src/scripts"
    assert normalize_path_canonical(None) is None
