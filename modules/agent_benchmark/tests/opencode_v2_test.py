"""Unit tests for OpenCode v2 candidate adapter and Harbor integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_benchmark.harbor import (
    OPENCODE_V2_PACKAGE,
    PINNED_OPENCODE_V2_VERSION,
    HarborImporter,
    OpenCodeV2,
    SUPPORTED_HARBOR_AGENTS,
    build_harbor_command,
    build_opencode_v2_install_command,
    build_opencode_v2_run_command,
    check_agent_configuration_blockers,
    is_harbor_available,
    plan_benchmark,
)
from agent_benchmark.harbor.runner import execute_harbor_run
from agent_benchmark.suite import build_manifest
from agent_benchmark.suite_monitor import MonitorPreflightError, validate_monitor


def test_opencode_v2_constants():
    """Verify pinned version and package identity."""
    assert PINNED_OPENCODE_V2_VERSION == "2.2.5"
    assert OPENCODE_V2_PACKAGE == "@opencode/cli@2.2.5"
    assert OpenCodeV2.name() == "opencode-v2"
    instance = OpenCodeV2() if hasattr(OpenCodeV2, "__init__") else None
    if instance is not None and hasattr(instance, "version"):
        assert instance.version() == "2.2.5"


def test_build_opencode_v2_run_command_default():
    """Verify default run command contains required v2 flags and omits deprecated flags."""
    cmd = build_opencode_v2_run_command(
        model_name="openai/qwen38_23GB",
        instruction="Fix the bug in beer_song.py",
        output_filename="/logs/agent/opencode.txt",
    )
    assert "--model='openai/qwen38_23GB'" in cmd or "--model=openai/qwen38_23GB" in cmd
    assert "run" in cmd
    assert "--format json" in cmd
    assert "--thinking" in cmd
    assert "--auto" in cmd
    assert "--standalone" in cmd
    assert "--dangerously-skip-permissions" not in cmd
    assert "2>&1 </dev/null | stdbuf -oL tee" in cmd
    assert "Fix the bug in beer_song.py" in cmd


def test_build_opencode_v2_run_command_options():
    """Verify run command respects resume and flag overrides."""
    cmd = build_opencode_v2_run_command(
        model_name="test-model",
        instruction="Test instruction",
        resume=True,
        cli_flags="--verbose",
        thinking=False,
        auto=False,
        standalone=False,
    )
    assert "--continue" in cmd
    assert "--verbose" in cmd
    assert "--thinking" not in cmd
    assert "--auto" not in cmd
    assert "--standalone" not in cmd


def test_build_opencode_v2_install_command():
    """Verify installation script targets @opencode/cli@2.2.5 with retry and checks version."""
    cmd = build_opencode_v2_install_command()
    assert "@opencode/cli@2.2.5" in cmd
    assert "npm i -g --fetch-retries=5" in cmd
    assert "opencode --version" in cmd
    assert "set -euo pipefail" in cmd


def test_opencode_v2_in_supported_agents():
    """Verify opencode-v2 is registered in SUPPORTED_HARBOR_AGENTS."""
    assert "opencode-v2" in SUPPORTED_HARBOR_AGENTS
    meta = SUPPORTED_HARBOR_AGENTS["opencode-v2"]
    assert meta["requires_model"] is True
    assert meta["requires_docker"] is True
    assert meta["pinned_version"] == "2.2.5"
    assert meta["package"] == "@opencode/cli"


def test_opencode_v2_configuration_blockers():
    """Verify base-url requirement enforcement for opencode-v2."""
    blockers = check_agent_configuration_blockers("opencode-v2", base_url=None)
    assert any("requires --base-url" in b for b in blockers)

    valid_blockers = check_agent_configuration_blockers(
        "opencode-v2",
        base_url="http://host.docker.internal:8788/v1",
    )
    assert valid_blockers == []


def test_plan_benchmark_opencode_v2():
    """Verify plan_benchmark constructs valid plan for opencode-v2."""
    plan = plan_benchmark(
        dataset_name="aider-polyglot",
        language="python",
        agent="opencode-v2",
        base_url="http://host.docker.internal:8788/v1",
        count=1,
    )
    assert plan.agent == "opencode-v2"
    assert len(plan.selected_tasks) == 1
    assert plan.readiness.is_runnable


def test_build_harbor_command_maps_opencode_v2_to_dynamic_class():
    """Verify build_harbor_command maps opencode-v2 to dynamic agent import path."""
    plan = plan_benchmark(
        dataset_name="aider-polyglot",
        language="python",
        agent="opencode-v2",
        base_url="http://host.docker.internal:8788/v1",
        count=1,
    )
    cmd = build_harbor_command(plan, jobs_dir=Path(".harbor-jobs"))
    agent_idx = cmd.index("--agent")
    assert cmd[agent_idx + 1] == "agent_benchmark.harbor.opencode_v2:OpenCodeV2"


def test_execute_harbor_run_opencode_v2_environment(tmp_path):
    """Verify execute_harbor_run configures PYTHONPATH and default OPENAI_API_KEY."""
    plan = plan_benchmark(
        dataset_name="aider-polyglot",
        language="python",
        agent="opencode-v2",
        base_url="http://host.docker.internal:8788/v1",
        count=1,
    )

    captured_env: dict[str, str] = {}

    def fake_subprocess_run(cmd, env, **kwargs):
        captured_env.update(env)
        job_dir = tmp_path / "jobs" / cmd[cmd.index("--job-name") + 1]
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "result.json").write_text('{"evaluations": []}', encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        return mock_proc

    with (
        patch("agent_benchmark.harbor.runner.check_docker_readiness", return_value=(True, "OK")),
        patch("agent_benchmark.harbor.runner.check_harbor_readiness", return_value=(True, "OK")),
        patch("agent_benchmark.harbor.runner.subprocess.run", side_effect=fake_subprocess_run),
        patch("agent_benchmark.harbor.runner.command_lock"),
        patch.object(
            HarborImporter,
            "import_to",
            return_value=(tmp_path / "saved", {"completed": 1}),
        ),
    ):
        execute_harbor_run(
            plan,
            execute=True,
            output_dir=tmp_path / "output",
            jobs_dir=tmp_path / "jobs",
            state_dir=tmp_path / "state",
        )

    assert captured_env.get("OPENAI_API_KEY") == "lm-studio"
    assert "agent_benchmark" in captured_env.get("PYTHONPATH", "")


# ---------------------------------------------------------------------------
# Real Harbor 0.25.0 Runtime Import & Construction Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not is_harbor_available(),
    reason="Harbor 0.25.0 not installed in current environment; run with --with harbor to verify real adapter",
)
def test_opencode_v2_real_harbor_subclass():
    """Verify OpenCodeV2 is an authentic subclass of Harbor's OpenCode adapter."""
    from harbor.agents.installed.opencode import OpenCode

    assert issubclass(OpenCodeV2, OpenCode)


@pytest.mark.skipif(
    not is_harbor_available(),
    reason="Harbor 0.25.0 not installed in current environment; run with --with harbor to verify real adapter",
)
def test_opencode_v2_harbor_agent_factory_resolution(tmp_path):
    """Verify Harbor's AgentFactory dynamically resolves and instantiates OpenCodeV2."""
    from harbor.agents.factory import AgentFactory
    from harbor.models.trial.config import AgentConfig

    cfg = AgentConfig(
        name="agent_benchmark.harbor.opencode_v2:OpenCodeV2",
        model_name="llm-monitor/qwen38_23GB",
        base_url="http://host.docker.internal:8789/v1",
    )
    cls = AgentFactory.get_agent_class_from_config(cfg)
    assert cls is OpenCodeV2

    agent = AgentFactory.create_agent_from_config(cfg, logs_dir=tmp_path)
    assert isinstance(agent, OpenCodeV2)
    assert agent.name() == "opencode-v2"
    assert agent.version() == "2.2.5"


@pytest.mark.skipif(
    not is_harbor_available(),
    reason="Harbor 0.25.0 not installed in current environment; run with --with harbor to verify real adapter",
)
def test_opencode_v2_harbor_provider_config_generation(tmp_path):
    """Verify OpenCodeV2 generates provider config targeting LLM Monitor via OpenAI-compatible SDK."""
    from harbor.agents.factory import AgentFactory
    from harbor.models.model_api_format import ModelApiFormat
    from harbor.models.trial.config import AgentConfig

    cfg = AgentConfig(
        name="agent_benchmark.harbor.opencode_v2:OpenCodeV2",
        model_name="llm-monitor/qwen38_23GB",
        base_url="http://host.docker.internal:8789/v1",
        model_api_format=ModelApiFormat.OPENAI_CHAT_COMPLETIONS,
    )
    agent = AgentFactory.create_agent_from_config(cfg, logs_dir=tmp_path)
    config_cmd = agent._build_register_config_command()
    assert config_cmd is not None
    assert "@ai-sdk/openai-compatible" in config_cmd
    assert "http://host.docker.internal:8789/v1" in config_cmd
    assert "qwen38_23GB" in config_cmd
    assert "responses" not in config_cmd.lower()


# ---------------------------------------------------------------------------
# Monitored Suite Integration Tests for OpenCode v2
# ---------------------------------------------------------------------------


def test_build_manifest_monitored_opencode_v2_sets_provider_and_protocol():
    """Verify build_manifest sets llm-monitor provider, 2.2.5 version, and openai_chat_completions for opencode-v2."""
    manifest = build_manifest(
        cohort="aider-python-10",
        agent="opencode-v2",
        model="openai/qwen38_23GB",
        base_url=None,
        api_format="openai_chat_completions",
        llm_monitor=True,
        recording="content",
        monitor_url="http://host.docker.internal:8789/v1",
        monitor_host_url="http://127.0.0.1:8789",
    )
    assert manifest["agent"] == "opencode-v2"
    assert manifest["model"] == "openai/qwen38_23GB"
    provenance = manifest["provenance"]
    assert provenance["effective_agent_model"] == "llm-monitor/qwen38_23GB"
    assert provenance["effective_agent_version"] == "2.2.5"
    assert provenance["effective_api_format"] == "openai_chat_completions"
    assert provenance["original_protocol"] == "openai_responses"
    assert provenance["monitor_url"] == "http://host.docker.internal:8789/v1"
    assert provenance["monitor_host_url"] == "http://127.0.0.1:8789"


def test_build_manifest_monitored_opencode_v2_rejects_responses_format():
    """Verify build_manifest fails closed if incompatible API format is supplied for opencode-v2."""
    with pytest.raises(ValueError, match="requires openai_chat_completions"):
        build_manifest(
            cohort="aider-python-10",
            agent="opencode-v2",
            model="openai/qwen38_23GB",
            base_url=None,
            api_format="openai_responses",
            llm_monitor=True,
            recording="content",
        )


def test_build_manifest_monitored_opencode_v2_rejects_non_openai_model():
    """Verify build_manifest fails closed if model is not an openai/ prefix."""
    with pytest.raises(ValueError, match="requires an OpenCode openai/<model> provider model"):
        build_manifest(
            cohort="aider-python-10",
            agent="opencode-v2",
            model="anthropic/claude-3-opus",
            base_url=None,
            api_format="openai_chat_completions",
            llm_monitor=True,
            recording="content",
        )


def test_build_manifest_monitored_opencode_v2_rejects_conflicting_base_url():
    """Verify build_manifest fails closed if explicit base-url conflicts with monitor-url."""
    with pytest.raises(ValueError, match="explicit --base-url conflicts with required --monitor-url"):
        build_manifest(
            cohort="aider-python-10",
            agent="opencode-v2",
            model="openai/qwen38_23GB",
            base_url="http://host.docker.internal:1234/v1",
            api_format="openai_chat_completions",
            llm_monitor=True,
            recording="content",
            monitor_url="http://host.docker.internal:8789/v1",
        )


def test_suite_monitor_preflight_opencode_v2_enforces_chat_completions():
    """Verify validate_monitor enforces openai_chat_completions for opencode-v2."""
    with pytest.raises(MonitorPreflightError, match="requires openai_chat_completions API format"):
        validate_monitor(
            agent="opencode-v2",
            model="openai/qwen38_23GB",
            api_format="openai_responses",
            recording="content",
        )
