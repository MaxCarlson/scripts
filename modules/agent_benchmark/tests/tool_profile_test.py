"""Auditable smoke-task execution; shell auditing is never relaxed."""
import json
from pathlib import Path

import pytest

from agent_benchmark.tool_profile import FILE_AGENT, configure_file_agent, validate_file_agent
from agent_benchmark.evidence import load_task

TASK = Path(__file__).resolve().parents[1] / "agent_benchmark/tasks/py-grep-smoke"


def test_smoke_task_declares_file_tools_profile():
    assert load_task(TASK).opencode_tool_profile == "file-tools-v1"


def test_file_agent_is_local_and_preserves_provider_configuration(tmp_path):
    config = {"provider": {"lmstudio": {"models": {"exact": {"limit": {"context": 16384}}}}}}
    path = tmp_path / "opencode.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    configure_file_agent(tmp_path)
    actual = json.loads(path.read_text(encoding="utf-8"))
    assert actual["provider"] == config["provider"]
    role = actual["agent"][FILE_AGENT]
    assert role["permission"]["*"] == "deny"
    assert role["permission"]["edit"] == "allow"
    assert "Do not run tests" in role["prompt"]
    assert "shell" in role["prompt"]


def test_file_agent_preflight_rejects_missing_or_broadened_effective_permissions():
    with pytest.raises(ValueError):
        validate_file_agent({"permission": None})
    rules = [{"permission": "*", "pattern": "*", "action": "deny"},
             {"permission": "edit", "pattern": "*", "action": "allow"},
             {"permission": "read", "pattern": "*", "action": "allow"}]
    validate_file_agent({"permission": rules})
    # OpenCode appends its output-directory access rule after per-agent config.
    validate_file_agent({"permission": rules + [{"permission": "external_directory",
                        "pattern": "C:/opencode/tool-output/*", "action": "allow"}]})
    with pytest.raises(ValueError, match="bash"):
        validate_file_agent({"permission": rules + [{"permission": "bash", "pattern": "*", "action": "allow"}]})
    with pytest.raises(ValueError):
        validate_file_agent({"permission": rules + [{"permission": "mcp_*", "pattern": "*", "action": "allow"}]})


def test_file_agent_refuses_overwriting_an_existing_agent(tmp_path):
    path = tmp_path / "opencode.json"
    original = json.dumps({"agent": {FILE_AGENT: {"prompt": "existing task-owned role"}}})
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        configure_file_agent(tmp_path)
    assert path.read_text(encoding="utf-8") == original


def test_cli_providers_do_not_claim_the_opencode_file_tool_policy(tmp_path):
    from agent_benchmark.attempt import build_prompt
    from agent_benchmark.scratch import SCRATCH_NAME

    (tmp_path / SCRATCH_NAME).mkdir()
    prompt = build_prompt(load_task(TASK), tmp_path, file_tools=False)
    assert "Tool profile: file-tools-v1" not in prompt
    assert "TMPDIR" in prompt
