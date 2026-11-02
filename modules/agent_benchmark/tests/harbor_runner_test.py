"""Unit tests for Harbor execution runner, authorization gates, and subprocess command generation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

from agent_benchmark.harbor import (
    ExecutionAuthorizationError,
    PreflightCheckError,
    build_harbor_command,
    execute_harbor_run,
    plan_benchmark,
)


def test_build_harbor_command():
    plan = plan_benchmark(
        "aider/aider-polyglot",
        agent="qwen-coder",
        model="test-model",
        task_ids=["polyglot_python_proverb", "polyglot_python_grep"],
        repetitions=2,
    )

    cmd = build_harbor_command(
        plan,
        jobs_dir=Path(".harbor-jobs"),
        job_name="test_job_123",
        n_concurrent=1,
        max_retries=0,
        quiet=True,
    )

    assert "run" in cmd
    assert "--job-name" in cmd
    assert "test_job_123" in cmd
    assert "--dataset" in cmd
    assert "aider-polyglot" in cmd
    assert "--agent" in cmd
    assert "qwen-coder" in cmd
    assert "--model" in cmd
    assert "test-model" in cmd
    assert "--base-url" in cmd
    assert "http://host.docker.internal:1234/v1" in cmd
    assert "--include-task-name" in cmd
    assert "polyglot_python_proverb" in cmd
    assert "polyglot_python_grep" in cmd
    assert "--n-attempts" in cmd
    assert "2" in cmd
    assert "--max-retries" in cmd
    assert "0" in cmd
    assert "--quiet" in cmd


def test_build_harbor_command_agent_specific_options():
    # 1. Oracle: neither model nor base-url
    plan_oracle = plan_benchmark("aider/aider-polyglot", agent="oracle", task_ids=["polyglot_python_proverb"])
    cmd_oracle = build_harbor_command(plan_oracle, jobs_dir=Path(".harbor-jobs"))
    assert "--agent" in cmd_oracle and "oracle" in cmd_oracle
    assert "--model" not in cmd_oracle
    assert "--base-url" not in cmd_oracle

    # 2. Nop: neither model nor base-url
    plan_nop = plan_benchmark("aider/aider-polyglot", agent="nop", task_ids=["polyglot_python_proverb"])
    cmd_nop = build_harbor_command(plan_nop, jobs_dir=Path(".harbor-jobs"))
    assert "--agent" in cmd_nop and "nop" in cmd_nop
    assert "--model" not in cmd_nop
    assert "--base-url" not in cmd_nop

    # 3. Codex with default model: no base-url, model omitted (Harbor default)
    plan_codex = plan_benchmark("aider/aider-polyglot", agent="codex", task_ids=["polyglot_python_proverb"])
    cmd_codex = build_harbor_command(plan_codex, jobs_dir=Path(".harbor-jobs"))
    assert "--agent" in cmd_codex and "codex" in cmd_codex
    assert "--model" not in cmd_codex
    assert "--base-url" not in cmd_codex

    # 4. Codex with explicit model: passes model, no base-url
    plan_codex_m = plan_benchmark("aider/aider-polyglot", agent="codex", model="gpt-4o", task_ids=["polyglot_python_proverb"])
    cmd_codex_m = build_harbor_command(plan_codex_m, jobs_dir=Path(".harbor-jobs"))
    assert "--model" in cmd_codex_m and "gpt-4o" in cmd_codex_m
    assert "--base-url" not in cmd_codex_m

    # 5. Antigravity CLI: no base-url
    plan_agy = plan_benchmark("aider/aider-polyglot", agent="antigravity-cli", task_ids=["polyglot_python_proverb"])
    cmd_agy = build_harbor_command(plan_agy, jobs_dir=Path(".harbor-jobs"))
    assert "--agent" in cmd_agy and "antigravity-cli" in cmd_agy
    assert "--base-url" not in cmd_agy


def test_execution_requires_authorization(tmp_path: Path):
    plan = plan_benchmark("aider/aider-polyglot", count=1)

    # Refuses without -x
    with pytest.raises(ExecutionAuthorizationError, match="-x/--execute"):
        execute_harbor_run(
            plan,
            execute=False,
            output_dir=tmp_path / "out",
            jobs_dir=tmp_path / "jobs",
        )


def test_build_harbor_command_uses_dataset_registry_identity():
    plan = plan_benchmark("terminal-bench-2", agent="oracle", task_ids=["build-cython-ext"])
    cmd = build_harbor_command(plan, jobs_dir=Path(".harbor-jobs"))
    assert cmd[cmd.index("--dataset") + 1] == "terminal-bench/terminal-bench-2"
    assert "build-cython-ext" in cmd


def test_build_harbor_command_uses_the_preverified_registry_snapshot(tmp_path: Path):
    plan = plan_benchmark("aider/aider-polyglot", agent="oracle", task_ids=["polyglot_python_beer-song"])
    registry = tmp_path / "registry.json"
    registry.write_text("{}", encoding="utf-8")

    cmd = build_harbor_command(plan, jobs_dir=tmp_path / "jobs", registry_path=registry)

    assert cmd[cmd.index("--registry-path") + 1] == str(registry.resolve())


def test_build_harbor_command_keeps_terminal_bench_4_separate():
    plan = plan_benchmark(
        "terminal-bench/terminal-bench@4.0.0",
        agent="oracle",
        task_ids=["layout-config-recreation2"],
    )
    cmd = build_harbor_command(plan, jobs_dir=Path(".harbor-jobs"))
    assert cmd[cmd.index("--dataset") + 1] == "terminal-bench/terminal-bench@4.0.0"
    assert "layout-config-recreation2" in cmd


def test_execution_fails_closed_when_docker_offline(tmp_path: Path, monkeypatch):
    plan = plan_benchmark("aider/aider-polyglot", count=1)

    # Simulate Docker being offline
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.check_docker_readiness",
        lambda: (False, "Docker daemon is not running"),
    )

    with pytest.raises(PreflightCheckError, match="without container isolation"):
        execute_harbor_run(
            plan,
            execute=True,
            output_dir=tmp_path / "out",
            jobs_dir=tmp_path / "jobs",
        )


def _write_mock_harbor_job_result(
    job_dir: Path,
    *,
    n_trials: int = 2,
    completed: int = 2,
    pending: int = 0,
    running: int = 0,
) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    trial_results = []
    for i in range(completed):
        trial_results.append({
            "id": f"00000000-0000-0000-0000-00000000000{i+1}",
            "task_name": f"task_{i+1}",
            "trial_name": f"task_{i+1}__trial",
            "agent_info": {"name": "oracle", "version": "0.25.0"},
            "verifier_result": {"rewards": {"reward": 1.0}},
            "started_at": "2026-10-30T00:00:00Z",
            "finished_at": "2026-10-30T00:01:00Z",
        })
    result_data = {
        "id": "11111111-1111-1111-1111-111111111111",
        "started_at": "2026-10-30T00:00:00Z",
        "finished_at": "2026-10-30T00:02:00Z",
        "n_total_trials": n_trials,
        "stats": {
            "n_completed_trials": completed,
            "n_pending_trials": pending,
            "n_running_trials": running,
            "n_errored_trials": 0,
        },
        "trial_results": trial_results,
    }
    (job_dir / "result.json").write_text(json.dumps(result_data, indent=2), encoding="utf-8")


def test_execute_harbor_run_nonzero_exit_without_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "agent_benchmark.harbor.planner.check_docker_readiness",
        lambda: (True, "Docker daemon is active"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.planner.check_harbor_readiness",
        lambda: (True, "harbor==0.25.0"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.check_docker_readiness",
        lambda: (True, "Docker daemon is active"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.check_harbor_readiness",
        lambda: (True, "harbor==0.25.0"),
    )

    jobs_dir = tmp_path / "jobs"
    plan = plan_benchmark("aider/aider-polyglot", agent="oracle", count=1)

    def mock_subprocess_run(cmd, **kwargs):
        if "--job-name" in cmd:
            job_name = cmd[cmd.index("--job-name") + 1]
            jdir = jobs_dir / job_name
            jdir.mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args=cmd, returncode=1)

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    with pytest.raises(RuntimeError, match="failed with exit code 1 and produced no result.json"):
        execute_harbor_run(
            plan,
            execute=True,
            output_dir=tmp_path / "out",
            jobs_dir=jobs_dir,
            state_dir=tmp_path / "state",
        )


def test_execute_harbor_run_nonzero_exit_corrupt_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "agent_benchmark.harbor.planner.check_docker_readiness",
        lambda: (True, "Docker daemon is active"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.planner.check_harbor_readiness",
        lambda: (True, "harbor==0.25.0"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.check_docker_readiness",
        lambda: (True, "Docker daemon is active"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.check_harbor_readiness",
        lambda: (True, "harbor==0.25.0"),
    )

    jobs_dir = tmp_path / "jobs"
    plan = plan_benchmark("aider/aider-polyglot", agent="oracle", count=1)

    def mock_subprocess_run(cmd, **kwargs):
        if "--job-name" in cmd:
            job_name = cmd[cmd.index("--job-name") + 1]
            jdir = jobs_dir / job_name
            jdir.mkdir(parents=True, exist_ok=True)
            (jdir / "result.json").write_text("CORRUPTED NOT JSON", encoding="utf-8")
        return subprocess.CompletedProcess(args=cmd, returncode=1)

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    with pytest.raises(RuntimeError, match="unparseable result.json"):
        execute_harbor_run(
            plan,
            execute=True,
            output_dir=tmp_path / "out",
            jobs_dir=jobs_dir,
            state_dir=tmp_path / "state",
        )


def test_execute_harbor_run_nonzero_exit_incomplete_job(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "agent_benchmark.harbor.planner.check_docker_readiness",
        lambda: (True, "Docker daemon is active"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.planner.check_harbor_readiness",
        lambda: (True, "harbor==0.25.0"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.check_docker_readiness",
        lambda: (True, "Docker daemon is active"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.check_harbor_readiness",
        lambda: (True, "harbor==0.25.0"),
    )

    jobs_dir = tmp_path / "jobs"
    plan = plan_benchmark("aider/aider-polyglot", agent="oracle", count=2)

    def mock_subprocess_run(cmd, **kwargs):
        if "--job-name" in cmd:
            job_name = cmd[cmd.index("--job-name") + 1]
            jdir = jobs_dir / job_name
            # Projected is 2 trials, but only 1 completed and 1 pending
            _write_mock_harbor_job_result(jdir, n_trials=2, completed=1, pending=1)
        return subprocess.CompletedProcess(args=cmd, returncode=1)

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    with pytest.raises(RuntimeError, match="leaving job incomplete"):
        execute_harbor_run(
            plan,
            execute=True,
            output_dir=tmp_path / "out",
            jobs_dir=jobs_dir,
            state_dir=tmp_path / "state",
        )


def test_execute_harbor_run_nonzero_exit_all_completed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "agent_benchmark.harbor.planner.check_docker_readiness",
        lambda: (True, "Docker daemon is active"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.planner.check_harbor_readiness",
        lambda: (True, "harbor==0.25.0"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.check_docker_readiness",
        lambda: (True, "Docker daemon is active"),
    )
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.check_harbor_readiness",
        lambda: (True, "harbor==0.25.0"),
    )

    jobs_dir = tmp_path / "jobs"
    plan = plan_benchmark("aider/aider-polyglot", agent="oracle", count=2)

    def mock_subprocess_run(cmd, **kwargs):
        if "--job-name" in cmd:
            job_name = cmd[cmd.index("--job-name") + 1]
            jdir = jobs_dir / job_name
            # All 2 projected trials are completed
            _write_mock_harbor_job_result(jdir, n_trials=2, completed=2, pending=0)
        return subprocess.CompletedProcess(args=cmd, returncode=2)

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    out_dir, summary = execute_harbor_run(
        plan,
        execute=True,
        output_dir=tmp_path / "out",
        jobs_dir=jobs_dir,
        state_dir=tmp_path / "state",
    )

    assert out_dir.is_dir()
    assert summary["completed"] == 2
    assert summary["harbor_process_returncode"] == 2


def test_build_harbor_command_api_format():
    # 1. Explicit model_api_format forwarded to harbor
    plan_format = plan_benchmark(
        "aider/aider-polyglot",
        agent="opencode",
        count=1,
        model_api_format="openai_chat_completions",
    )
    cmd_format = build_harbor_command(plan_format, jobs_dir=Path(".harbor-jobs"))
    assert "--api-format" in cmd_format
    fmt_idx = cmd_format.index("--api-format")
    assert cmd_format[fmt_idx + 1] == "openai_chat_completions"
    assert "--base-url" in cmd_format
    assert "http://host.docker.internal:1234/v1" in cmd_format

    # 2. Default plan without model_api_format omits --api-format
    plan_no_fmt = plan_benchmark("aider/aider-polyglot", agent="opencode", count=1)
    cmd_no_fmt = build_harbor_command(plan_no_fmt, jobs_dir=Path(".harbor-jobs"))
    assert "--api-format" not in cmd_no_fmt
    assert "--base-url" in cmd_no_fmt

    # 3. Custom base_url preserved alongside explicit api-format
    plan_gateway = plan_benchmark(
        "aider/aider-polyglot",
        agent="opencode",
        count=1,
        base_url="http://host.docker.internal:8788/v1",
        model_api_format="openai_chat_completions",
    )
    cmd_gateway = build_harbor_command(plan_gateway, jobs_dir=Path(".harbor-jobs"))
    assert "--api-format" in cmd_gateway
    assert cmd_gateway[cmd_gateway.index("--api-format") + 1] == "openai_chat_completions"
    assert "--base-url" in cmd_gateway
    assert cmd_gateway[cmd_gateway.index("--base-url") + 1] == "http://host.docker.internal:8788/v1"
