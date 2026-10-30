"""Unit tests for Harbor execution runner, authorization gates, and subprocess command generation."""

from __future__ import annotations

from pathlib import Path
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
        agent="oracle",
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
    assert "oracle" in cmd
    assert "--model" in cmd
    assert "test-model" in cmd
    assert "--include-task-name" in cmd
    assert "polyglot_python_proverb" in cmd
    assert "polyglot_python_grep" in cmd
    assert "--n-attempts" in cmd
    assert "2" in cmd
    assert "--max-retries" in cmd
    assert "0" in cmd
    assert "--quiet" in cmd


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
