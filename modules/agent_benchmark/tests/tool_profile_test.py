"""Auditable smoke-task execution; shell auditing is never relaxed."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent_benchmark.tool_profile import (
    FILE_AGENT,
    FILE_PROMPT,
    RETRIEVAL_AGENT,
    RETRIEVAL_PROFILE,
    configure_file_agent,
    validate_file_agent,
)
from agent_benchmark.evidence import load_task
from agent_benchmark.attempt import build_prompt

TASK = Path(__file__).resolve().parents[1] / "agent_benchmark/tasks/py-grep-smoke"


def test_smoke_task_declares_file_tools_profile():
    assert load_task(TASK).opencode_tool_profile == "file-tools-v1"


def test_task_manifest_accepts_distinct_retrieval_profile(tmp_path):
    import shutil

    copy = tmp_path / "task"
    shutil.copytree(TASK, copy, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = copy / "task.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["opencode_tool_profile"] = RETRIEVAL_PROFILE
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert load_task(copy).opencode_tool_profile == RETRIEVAL_PROFILE


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
    role_identity = {"name": FILE_AGENT, "mode": "primary", "prompt": FILE_PROMPT}
    rules = [{"permission": "*", "pattern": "*", "action": "deny"},
             {"permission": "edit", "pattern": "*", "action": "allow"},
             {"permission": "read", "pattern": "*", "action": "allow"}]
    validate_file_agent({**role_identity, "permission": rules})
    # OpenCode appends its output-directory access rule after per-agent config.
    validate_file_agent({**role_identity, "permission": rules + [{"permission": "external_directory",
                        "pattern": "C:/opencode/tool-output/*", "action": "allow"}]},
                        trusted_output_directory=Path("C:/opencode/tool-output"))
    with pytest.raises(ValueError, match="bash"):
        validate_file_agent({**role_identity, "permission": rules + [{"permission": "bash", "pattern": "*", "action": "allow"}]})
    with pytest.raises(ValueError):
        validate_file_agent({**role_identity, "permission": rules + [{"permission": "mcp_*", "pattern": "*", "action": "allow"}]})


def test_retrieval_agent_keeps_default_deny_and_allows_only_named_read_tools(tmp_path):
    configure_file_agent(tmp_path, retrieval=True)
    actual = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    role = actual["agent"][RETRIEVAL_AGENT]
    assert role["permission"]["*"] == "deny"
    assert role["permission"]["code_locate"] == "allow"
    assert role["permission"]["code_context"] == "allow"
    assert "bash" not in role["permission"]
    rules = [
        {"permission": "*", "pattern": "*", "action": "deny"},
        *({"permission": name, "pattern": "*", "action": "allow"}
          for name in ("read", "edit", "code_locate", "code_context")),
    ]
    validate_file_agent({**role, "name": RETRIEVAL_AGENT, "permission": rules}, retrieval=True)
    with pytest.raises(ValueError, match="bash"):
        validate_file_agent({**role, "name": RETRIEVAL_AGENT, "permission": rules + [
            {"permission": "bash", "pattern": "*", "action": "allow"},
        ]}, retrieval=True)
    assert RETRIEVAL_PROFILE == "retrieval-files-v1"


def test_retrieval_profile_prompt_names_its_exact_tools():
    task = replace(load_task(TASK), opencode_tool_profile=RETRIEVAL_PROFILE)
    prompt = build_prompt(task, Path("C:/trial"))
    assert "code_locate" in prompt and "code_context" in prompt
    assert "Tool profile: retrieval-files-v1" in prompt
    assert "Do not run tests, invoke a shell" in prompt


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


@pytest.mark.parametrize("permission,pattern,action", [
    ("external_directory", "*", "allow"), ("external_directory", "C:/*", "allow"),
    ("external_directory", "C:/opencode/tool-output/../*", "allow"),
    ("external_directory", "C:/opencode/tool-output/*", "ask"),
    ("external_directory", "C:/other/*", "allow"), ("e*", "*", "allow"),
    ("bash", "*", "ask"), ("*", "*", "allow"),
])
def test_profile_rejects_external_or_wildcard_widening(permission, pattern, action):
    role = {"name": FILE_AGENT, "mode": "primary", "prompt": FILE_PROMPT, "permission": [
        {"permission": "*", "pattern": "*", "action": "deny"},
        {"permission": "read", "pattern": "*", "action": "allow"},
        {"permission": "edit", "pattern": "*", "action": "allow"},
        {"permission": permission, "pattern": pattern, "action": action}]}
    with pytest.raises(ValueError):
        validate_file_agent(role, trusted_output_directory=Path("C:/opencode/tool-output"))


@pytest.mark.parametrize("change", [{"mode": "subagent"}, {"prompt": "altered"}, {"name": "other"}])
def test_profile_rejects_altered_role_identity(change):
    role = {"name": FILE_AGENT, "mode": "primary", "prompt": FILE_PROMPT, "permission": [
        {"permission": "*", "pattern": "*", "action": "deny"},
        {"permission": "read", "pattern": "*", "action": "allow"},
        {"permission": "edit", "pattern": "*", "action": "allow"}], **change}
    with pytest.raises(ValueError):
        validate_file_agent(role)


def test_profile_uses_last_matching_wildcard_rule_and_rejects_malformed_entries():
    base = {"name": FILE_AGENT, "mode": "primary", "prompt": FILE_PROMPT}
    rules = [{"permission": "*", "pattern": "*", "action": "deny"},
             {"permission": "read", "pattern": "*", "action": "allow"},
             {"permission": "edit", "pattern": "*", "action": "allow"}]
    with pytest.raises(ValueError):
        validate_file_agent({**base, "permission": rules + [{"permission": "e*", "pattern": "*", "action": "deny"}]})
    with pytest.raises(ValueError):
        validate_file_agent({**base, "permission": [{"permission": None}] + rules})
    validate_file_agent({**base, "permission": [{"permission": "bash", "pattern": "*", "action": "allow"}] + rules})


def test_runtime_output_location_uses_server_data_home_not_config_siblings(tmp_path, monkeypatch):
    from agent_benchmark import tool_profile

    home, actual = tmp_path / "home", tmp_path / "custom-data"
    (home / ".local/share/opencode/tool-output").mkdir(parents=True)
    (actual / "opencode").mkdir(parents=True)
    monkeypatch.setattr(tool_profile, "_server_environment", lambda url: {
        "pid": 42, "process_started": 1, "executable": "opencode.exe", "xdg_data_home": str(actual),
        "source": "correlated_loopback_listener_environment"})
    paths = {"home": str(home), "config": str(home / ".config/opencode"), "state": str(home / ".local/state/opencode")}
    evidence = tool_profile.runtime_output_evidence(paths, "1.19.3", "http://localhost:4096")
    assert evidence["directory"] == str(actual / "opencode/tool-output")
    assert tool_profile.runtime_output_evidence(paths, "unknown-version", "http://localhost:4096") is None
    monkeypatch.setattr(tool_profile, "_server_environment", lambda url: None)
    assert tool_profile.runtime_output_evidence(paths, "1.19.3", "http://localhost:4096") is None


def test_profile_rejects_late_targeted_file_denial():
    role = {"name": FILE_AGENT, "mode": "primary", "prompt": FILE_PROMPT, "permission": [
        {"permission": "*", "pattern": "*", "action": "deny"},
        {"permission": "read", "pattern": "*", "action": "allow"},
        {"permission": "edit", "pattern": "*", "action": "allow"},
        {"permission": "edit", "pattern": "grep.py", "action": "deny"}]}
    with pytest.raises(ValueError, match="edit"):
        validate_file_agent(role)


def test_ordered_external_rules_cannot_widen_verified_exception():
    identity = {"name": FILE_AGENT, "mode": "primary", "prompt": FILE_PROMPT}
    rules = [{"permission": "*", "pattern": "*", "action": "deny"},
             {"permission": "read", "pattern": "*", "action": "allow"},
             {"permission": "edit", "pattern": "*", "action": "allow"},
             {"permission": "external_directory", "pattern": "*", "action": "ask"},
             {"permission": "external_directory", "pattern": "*", "action": "deny"},
             {"permission": "external_directory", "pattern": "C:/output/*", "action": "allow"}]
    validate_file_agent({**identity, "permission": rules}, trusted_output_directory=Path("C:/output"))
    with pytest.raises(ValueError):
        validate_file_agent({**identity, "permission": rules + [{"permission": "external_directory", "pattern": "*", "action": "allow"}]},
                            trusted_output_directory=Path("C:/output"))


def test_sandbox_manifest_is_not_silently_downgraded(tmp_path):
    import shutil
    copy = tmp_path / "task"
    shutil.copytree(TASK, copy, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = copy / "task.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["opencode_tool_profile"] = "sandboxed-shell-v1"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="sandboxed-shell-v1"):
        load_task(copy)


def test_structural_retrieval_profile_is_distinct_and_default_deny(tmp_path):
    from agent_benchmark.tool_profile import (
        STRUCTURAL_AGENT, STRUCTURAL_PROFILE, STRUCTURAL_PROMPT, validate_execution_profile,
    )

    configure_file_agent(tmp_path, structural=True)
    role = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))["agent"][STRUCTURAL_AGENT]
    assert role["permission"]["*"] == "deny"
    for tool in ("code_locate", "code_context", "code_symbols", "code_map"):
        assert role["permission"][tool] == "allow"
    assert "bash" not in role["permission"]
    rules = [{"permission": "*", "pattern": "*", "action": "deny"}]
    rules.extend({"permission": name, "pattern": "*", "action": "allow"}
                 for name in ("read", "edit", "code_locate", "code_context", "code_symbols", "code_map"))
    validate_file_agent({**role, "name": STRUCTURAL_AGENT, "permission": rules}, structural=True)
    with pytest.raises(ValueError, match="bash"):
        validate_file_agent({**role, "name": STRUCTURAL_AGENT, "permission": rules + [
            {"permission": "bash", "pattern": "*", "action": "allow"},
        ]}, structural=True)
    assert STRUCTURAL_PROFILE == "retrieval-structural-v1"
    assert "code_map" in STRUCTURAL_PROMPT and "code_symbols" in STRUCTURAL_PROMPT
    validate_execution_profile(STRUCTURAL_PROFILE)


def test_structural_profile_manifest_and_prompt_are_identifiable(tmp_path):
    import shutil
    from agent_benchmark.tool_profile import STRUCTURAL_PROFILE

    copy = tmp_path / "task"
    shutil.copytree(TASK, copy, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = copy / "task.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["opencode_tool_profile"] = STRUCTURAL_PROFILE
    manifest.write_text(json.dumps(data), encoding="utf-8")
    task = load_task(copy)
    prompt = build_prompt(replace(task, opencode_tool_profile=STRUCTURAL_PROFILE), Path("C:/trial"))
    assert task.opencode_tool_profile == STRUCTURAL_PROFILE
    assert "code_symbols" in prompt and "code_map" in prompt
    assert "Tool profile: retrieval-structural-v1" in prompt
