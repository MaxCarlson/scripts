"""Tests for Workflow-ID marker parsing and normalized hook event envelopes."""

from __future__ import annotations

from agent_continuity.hooks import NormalizedHookEvent, NormalizedHookType, normalized_hook_to_event_envelope
from agent_continuity.markers import parse_workflow_markers
from agent_continuity.models import EventType


def test_parse_canonical_and_legacy_markers_with_whitespace() -> None:
    res = parse_workflow_markers("  Workflow-ID:   WF_7D3A92  \n\nImplement feature.")
    assert res.marker == "wf_7d3a92"
    assert res.conflict is False

    res_slug = parse_workflow_markers("Workflow-ID: ProcWatch\nProceed.")
    assert res_slug.marker == "procwatch"

    res_legacy = parse_workflow_markers("[wf:procwatch]\nProceed.")
    assert res_legacy.marker == "procwatch"


def test_parse_ignores_fenced_code_blocks_blockquotes_and_inline_examples() -> None:
    prompt = (
        "Here is documentation:\n"
        "> Workflow-ID: wf_111111\n"
        "\n"
        "```text\n"
        "Workflow-ID: wf_222222\n"
        "```\n"
        "\n"
        "~~~markdown\n"
        "[wf:fake-slug]\n"
        "~~~\n"
        "\n"
        "Example inline `Workflow-ID: wf_333333` should not match.\n"
        "\n"
        "Workflow-ID: wf_abcdef\n"
    )
    res = parse_workflow_markers(prompt)
    assert res.marker == "wf_abcdef"
    assert res.markers_found == ["wf_abcdef"]
    assert res.conflict is False


def test_parse_detects_conflicting_markers_and_rejects_malformed() -> None:
    res = parse_workflow_markers("Workflow-ID: wf_aaaaaa\nWorkflow-ID: wf_bbbbbb\n")
    assert res.marker is None
    assert res.conflict is True
    assert res.markers_found == ["wf_aaaaaa", "wf_bbbbbb"]

    res_bad = parse_workflow_markers("Workflow-ID: wf_12\nWorkflow-ID: bad/slug\n")
    assert res_bad.marker is None
    assert res_bad.conflict is False
    assert "wf_12" in res_bad.ignored_malformed


def test_normalized_hook_to_event_envelope_omits_raw_prompt() -> None:
    hook = NormalizedHookEvent(
        provider="codex",
        environment_id="env_win_test",
        native_session_id="ses-1",
        native_event_type="UserPromptSubmit",
        normalized_event_type=NormalizedHookType.TURN_SUBMITTED.value,
        event_id="evt_hook_1",
        event_schema_version=1,
        source_timestamp="2026-11-19T10:00:00Z",
        observed_timestamp="2026-11-19T10:00:01Z",
        source_adapter_version="0.2.0",
        workflow_marker="wf_7d3a92",
        turn_id="turn_1",
        cwd=r"C:\Users\mcarls\src\scripts",
    )
    env = normalized_hook_to_event_envelope(hook)
    assert env.event_type == EventType.HOOK_EVENT.value
    assert env.payload["workflow_marker"] == "wf_7d3a92"
    assert "prompt" not in env.payload
    assert "lastUserInput" not in env.payload
