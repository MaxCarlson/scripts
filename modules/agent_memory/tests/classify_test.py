from unittest.mock import patch

import pytest

from agent_memory.classify import PlacementError, determine_project


def test_constraint_always_global() -> None:
    result = determine_project(kind="constraint", project=None, title="my rule", auto_classify=False)
    assert result == "global"


def test_preference_always_global() -> None:
    result = determine_project(kind="preference", project=None, title="my pref", auto_classify=False)
    assert result == "global"


def test_explicit_project_always_returned() -> None:
    result = determine_project(kind="decision", project="my-project", title="some decision", auto_classify=False)
    assert result == "my-project"


def test_explicit_global_always_returned() -> None:
    result = determine_project(kind="decision", project="global", title="some decision", auto_classify=False)
    assert result == "global"


def test_project_required_kind_without_project_raises() -> None:
    with pytest.raises(PlacementError, match="requires a project"):
        determine_project(kind="handoff", project=None, title="handoff", auto_classify=False)


def test_project_required_kind_task_without_project_raises() -> None:
    with pytest.raises(PlacementError, match="requires a project"):
        determine_project(kind="task", project=None, title="my task", auto_classify=False)


def test_project_required_kind_bug_without_project_raises() -> None:
    with pytest.raises(PlacementError, match="requires a project"):
        determine_project(kind="bug", project=None, title="my bug", auto_classify=False)


def test_ambiguous_kind_without_auto_classify_defaults_global() -> None:
    result = determine_project(kind="decision", project=None, title="some decision", auto_classify=False)
    assert result == "global"


def test_auto_classify_calls_llm_for_ambiguous_kind() -> None:
    with patch("agent_memory.classify._llm_complete", return_value="my-project") as mock_llm:
        result = determine_project(
            kind="decision", project=None, title="Use SQLite", auto_classify=True, interactive=False
        )
    assert result == "my-project"
    mock_llm.assert_called_once()


def test_auto_classify_returns_global_when_llm_says_global() -> None:
    with patch("agent_memory.classify._llm_complete", return_value="global"):
        result = determine_project(
            kind="code_note", project=None, title="How routing works", auto_classify=True, interactive=False
        )
    assert result == "global"


def test_auto_classify_strips_quotes_from_llm_response() -> None:
    with patch("agent_memory.classify._llm_complete", return_value="'my-project'"):
        result = determine_project(
            kind="session", project=None, title="Session summary", auto_classify=True, interactive=False
        )
    assert result == "my-project"


def test_auto_classify_returns_global_when_llm_unreachable_no_tty() -> None:
    with patch("agent_memory.classify._llm_complete", return_value=None):
        result = determine_project(
            kind="decision",
            project=None,
            title="Some decision",
            auto_classify=True,
            interactive=False,
        )
    assert result == "global"


def test_auto_classify_returns_global_on_unusable_llm_response() -> None:
    with patch("agent_memory.classify._llm_complete", return_value="   "):
        result = determine_project(
            kind="decision",
            project=None,
            title="Some decision",
            auto_classify=True,
            interactive=False,
        )
    assert result == "global"


def test_auto_classify_returns_global_on_oversized_llm_response() -> None:
    long_response = "x" * 100
    with patch("agent_memory.classify._llm_complete", return_value=long_response):
        result = determine_project(
            kind="decision",
            project=None,
            title="Some decision",
            auto_classify=True,
            interactive=False,
        )
    assert result == "global"


def test_interactive_fallback_global_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["g"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("agent_memory.classify._llm_complete", return_value=None), patch("sys.stdin.isatty", return_value=True):
        result = determine_project(
            kind="decision",
            project=None,
            title="Some decision",
            auto_classify=True,
            interactive=True,
        )
    assert result == "global"


def test_interactive_fallback_project_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["p", "my-project"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("agent_memory.classify._llm_complete", return_value=None), patch("sys.stdin.isatty", return_value=True):
        result = determine_project(
            kind="session",
            project=None,
            title="Session end",
            auto_classify=True,
            interactive=True,
        )
    assert result == "my-project"


def test_interactive_fallback_retries_on_invalid_input(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["x", "bad", "g"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("agent_memory.classify._llm_complete", return_value=None), patch("sys.stdin.isatty", return_value=True):
        result = determine_project(
            kind="code_note",
            project=None,
            title="Some code note",
            auto_classify=True,
            interactive=True,
        )
    assert result == "global"


def test_no_interactive_no_llm_defaults_global() -> None:
    with patch("agent_memory.classify._llm_complete", return_value=None):
        result = determine_project(
            kind="decision",
            project=None,
            title="Something",
            auto_classify=True,
            interactive=False,
        )
    assert result == "global"
