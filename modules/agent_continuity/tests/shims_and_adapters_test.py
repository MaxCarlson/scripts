"""Tests for Codex and AGY hook normalization, shims, and fail-open behavior."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

from agent_continuity.cli import main
from agent_continuity.hooks import NormalizedHookType
from agent_continuity.providers.agy import AgyAdapter
from agent_continuity.providers.codex import CodexAdapter
from agent_continuity.shim import process_hook_stdin, run_hook_shim

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_codex_adapter_normalizes_fixtures() -> None:
    fixtures = json.loads((_FIXTURES / "codex_hooks.json").read_text(encoding="utf-8"))
    adapter = CodexAdapter()

    created = adapter.normalize_hook_event(fixtures["session_start_new"], environment_id="env_win_1")
    assert created.normalized_event_type == NormalizedHookType.SESSION_CREATED.value
    assert created.native_session_id == "019a0000-0000-7000-8000-000000000101"

    resumed = adapter.normalize_hook_event(fixtures["session_start_resume"], environment_id="env_win_1")
    assert resumed.normalized_event_type == NormalizedHookType.SESSION_OBSERVED.value
    assert resumed.source == "resume"

    prompt = adapter.normalize_hook_event(fixtures["user_prompt_submit_tagged"], environment_id="env_win_1")
    assert prompt.normalized_event_type == NormalizedHookType.TURN_SUBMITTED.value
    assert prompt.workflow_marker == "wf_7d3a92"
    assert prompt.turn_id is not None

    stopped = adapter.normalize_hook_event(fixtures["stop"], environment_id="env_win_1")
    assert stopped.normalized_event_type == NormalizedHookType.TURN_COMPLETED.value

    ended = adapter.normalize_hook_event(fixtures["session_end"], environment_id="env_win_1")
    assert ended.normalized_event_type == NormalizedHookType.SESSION_ENDED.value


def test_agy_adapter_normalizes_v1_5_and_v1_2_fixtures() -> None:
    fixtures = json.loads((_FIXTURES / "agy_hooks.json").read_text(encoding="utf-8"))
    adapter = AgyAdapter()

    started = adapter.normalize_hook_event(fixtures["session_start_1_5"], environment_id="env_win_1")
    assert started.normalized_event_type == NormalizedHookType.SESSION_CREATED.value
    assert started.surface == "antigravity-cli"

    pre = adapter.normalize_hook_event(fixtures["pre_invocation_tagged"], environment_id="env_win_1")
    assert pre.normalized_event_type == NormalizedHookType.TURN_SUBMITTED.value
    assert pre.workflow_marker == "procwatch"
    assert pre.turn_id == "inv_1"

    pre_1_2 = adapter.normalize_hook_event(fixtures["pre_invocation_v1_2_minimal"], environment_id="env_wsl_1")
    assert pre_1_2.normalized_event_type == NormalizedHookType.TURN_SUBMITTED.value
    assert pre_1_2.workflow_marker is None
    assert pre_1_2.cwd == "/mnt/c/Users/mcarls/src/scripts"

    stop = adapter.normalize_hook_event(fixtures["stop"], environment_id="env_win_1")
    assert stop.normalized_event_type == NormalizedHookType.TURN_COMPLETED.value
    assert stop.metadata["termination_reason"] == "NO_TOOL_CALL"


def test_hook_shim_writes_durable_event_and_never_creates_sqlite(tmp_path: Path) -> None:
    home = tmp_path / "shim_home"
    fixtures = json.loads((_FIXTURES / "codex_hooks.json").read_text(encoding="utf-8"))
    out = io.StringIO()
    rc = run_hook_shim(
        "codex",
        stdin_stream=io.StringIO(json.dumps(fixtures["user_prompt_submit_tagged"])),
        stdout_stream=out,
        home_dir=home,
    )
    assert rc == 0
    assert json.loads(out.getvalue()) == {}
    assert not (home / "index.sqlite").exists()
    spool_files = list((home / "events").rglob("*.json"))
    assert len(spool_files) == 1
    saved = json.loads(spool_files[0].read_text(encoding="utf-8"))
    assert saved["event_type"] == "hook.event"
    assert saved["payload"]["workflow_marker"] == "wf_7d3a92"
    assert "Implement Phase 2." not in json.dumps(saved)


def test_hook_shim_fails_open_on_malformed_input_and_spool_errors(tmp_path: Path) -> None:
    # 1. Malformed JSON stdin
    out1 = io.StringIO()
    rc1 = run_hook_shim("agy", stdin_stream=io.StringIO("{not-json"), stdout_stream=out1, home_dir=tmp_path)
    assert rc1 == 0
    assert json.loads(out1.getvalue()) == {}

    # 2. Missing required session_id / conversationId
    resp2, outcome2 = process_hook_stdin("codex", raw_stdin=json.dumps({"hook_event_name": "Stop"}), home_dir=tmp_path)
    assert resp2 == {}
    assert outcome2.recorded is False

    # 3. Spool write failure (OSError) must still exit 0 with {}
    fixtures = json.loads((_FIXTURES / "agy_hooks.json").read_text(encoding="utf-8"))
    out3 = io.StringIO()
    with patch("agent_continuity.shim.append_event", side_effect=OSError("disk full")):
        rc3 = run_hook_shim(
            "agy",
            stdin_stream=io.StringIO(json.dumps(fixtures["pre_invocation_tagged"])),
            stdout_stream=out3,
            home_dir=tmp_path,
        )
    assert rc3 == 0
    assert json.loads(out3.getvalue()) == {}


def test_cli_hook_shim_command(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "cli_shim_home"
    fixtures = json.loads((_FIXTURES / "agy_hooks.json").read_text(encoding="utf-8"))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(fixtures["stop"])))
    rc = main(["-H", str(home), "hook-shim", "-p", "agy"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {}
    assert len(list((home / "events").rglob("*.json"))) == 1
