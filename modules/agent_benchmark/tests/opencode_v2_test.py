"""Unit tests for OpenCode v2 candidate adapter and Harbor integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
    plan_benchmark,
)
from agent_benchmark.harbor.runner import execute_harbor_run


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
    """Verify installation script targets @opencode/cli@2.2.5 and checks version."""
    cmd = build_opencode_v2_install_command()
    assert "npm i -g @opencode/cli@2.2.5" in cmd
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
        # Create minimal fake job_dir and result.json to satisfy runner post-execution
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
