"""Synthetic lifecycle tests for the persistent Harbor suite runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_benchmark.suite import (
    COHORTS,
    RunStore,
    build_manifest,
    create_run,
    load_cohort,
    summarize_run,
)


EXPECTED_PYTHON_10 = (
    "polyglot_python_beer-song",
    "polyglot_python_bottle-song",
    "polyglot_python_bowling",
    "polyglot_python_dot-dsl",
    "polyglot_python_pig-latin",
    "polyglot_python_react",
    "polyglot_python_robot-name",
    "polyglot_python_transpose",
    "polyglot_python_variable-length-quantity",
    "polyglot_python_zipper",
)


def test_frozen_cohort_identity_and_order():
    cohort = COHORTS["aider-python-10"]
    assert cohort["revision"] == "f30b14415dd733c83627204bad0af69a89ceb46f"
    assert tuple(cohort["tasks"]) == EXPECTED_PYTHON_10


def test_user_manifest_preserves_order_and_rejects_duplicate_tasks(tmp_path: Path):
    path = tmp_path / "custom.json"
    path.write_text(json.dumps({"id": "custom", "dataset": "aider/aider-polyglot",
                                "source_revision": "rev-1", "tasks": ["task-b", "task-a"]}),
                    encoding="utf-8")
    assert load_cohort(manifest=path)["tasks"] == ["task-b", "task-a"]
    path.write_text(json.dumps({"dataset": "aider/aider-polyglot", "source_revision": "rev-1",
                                "tasks": ["task-a", "task-a"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="must be unique"):
        load_cohort(manifest=path)


def test_manifest_is_deterministic_and_preserves_protocol_provenance():
    first = build_manifest(
        cohort="aider-python-10", agent="opencode", model="openai/qwen38_23GB",
        base_url="http://host.docker.internal:8788/v1", api_format="openai_chat_completions",
        llm_monitor=True, recording="metadata", jobs=1,
    )
    second = build_manifest(
        cohort="aider-python-10", agent="opencode", model="openai/qwen38_23GB",
        base_url="http://host.docker.internal:8788/v1", api_format="openai_chat_completions",
        llm_monitor=True, recording="metadata", jobs=1,
    )
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["provenance"]["requested_api_format"] == "openai_chat_completions"
    assert first["tasks"] == list(EXPECTED_PYTHON_10)


def test_monitored_opencode_refuses_conflicting_endpoint_or_provider_model():
    with pytest.raises(ValueError, match="conflicts with required --monitor-url"):
        build_manifest(cohort="aider-python-10", agent="opencode", model="openai/model",
                       base_url="http://other/v1", api_format=None, llm_monitor=True, recording="off")
    with pytest.raises(ValueError, match="requires an OpenCode openai/<model>"):
        build_manifest(cohort="aider-python-10", agent="opencode", model="anthropic/model",
                       base_url=None, api_format=None, llm_monitor=True, recording="off")


def test_recording_mode_requires_monitor_routing():
    with pytest.raises(ValueError, match="requires -L/--llm-monitor"):
        build_manifest(cohort="aider-python-10", agent="qwen-coder", model="model",
                       base_url=None, api_format=None, llm_monitor=False, recording="content")


def test_run_checkpoint_counts_infrastructure_separately(tmp_path: Path):
    run = create_run(
        tmp_path, cohort="aider-python-10", agent="qwen-coder", model="qwen38_23GB",
        base_url=None, api_format=None, llm_monitor=False, recording="off", jobs=1,
    )
    store = RunStore(run)
    store.update_task("polyglot_python_beer-song", status="passed", trial_id="trial-1")
    store.update_task("polyglot_python_bottle-song", status="infrastructure_invalid", error_code="HARBOR_PROTOCOL")
    report = summarize_run(store.read())
    assert report["passed"] == 1
    assert report["scored"] == 1
    assert report["infrastructure_invalid"] == 1
    assert report["pass_rate_pct"] == 100.0
    assert json.loads((run / "checkpoint.json").read_text(encoding="utf-8"))["tasks"][0]["status"] == "passed"


def test_run_store_refuses_task_outside_manifest(tmp_path: Path):
    run = create_run(
        tmp_path, cohort="aider-python-10", agent="qwen-coder", model="qwen38_23GB",
        base_url=None, api_format=None, llm_monitor=False, recording="off", jobs=1,
    )
    with pytest.raises(ValueError, match="not in the run manifest"):
        RunStore(run).update_task("unknown-task", status="passed")


def test_friendly_presentation_does_not_change_harbor_manifest(monkeypatch):
    from types import SimpleNamespace

    import agent_benchmark.suite as suite

    class Plan:
        dataset: object = SimpleNamespace(id="aider/aider-polyglot", name="Aider", version="1.0",
                                          default_scoring_protocol="single-attempt-v1")
        selected_tasks: tuple = EXPECTED_PYTHON_10
        agent: str = "opencode"
        model: str = "openai/model"
        base_url: str = "http://gateway/v1"
        model_api_format: str = "openai_chat_completions"
        scoring_protocol: str = "single-attempt-v1"
        readiness: object = SimpleNamespace(is_runnable=True, blockers=(), harbor_installed=True,
                                            docker_available=True, harbor_version="Harbor 0.25.0")

    monkeypatch.setattr(suite, "plan_benchmark", lambda *args, **kwargs: Plan())
    regular = build_manifest(cohort="aider-python-10", agent="opencode", model="openai/model",
                             base_url=None, api_format=None, llm_monitor=True, recording="metadata")
    friendly = build_manifest(cohort="aider-python-10", agent="opencode", model="openai/model",
                              base_url=None, api_format=None, llm_monitor=True, recording="metadata")
    assert regular == friendly
    assert regular["source_revision"] == "f30b14415dd733c83627204bad0af69a89ceb46f"
    assert len(regular["tasks"]) == 10


def test_sequential_execution_preserves_accepted_trials_and_retries_invalid_once(tmp_path: Path):
    from agent_benchmark.suite import execute_pending

    run = create_run(tmp_path, cohort="aider-python-10", agent="qwen-coder", model="qwen38_23GB",
                     base_url=None, api_format=None, llm_monitor=False, recording="off")
    calls = []

    def executor(store, task):
        calls.append(task)
        return {"status": "passed" if task.endswith("beer-song") else "infrastructure_invalid",
                "trial_id": f"trial-{len(calls)}", "native_artifacts": [f"artifact-{len(calls)}"]}

    execute_pending(run, execute=True, executor=executor)
    execute_pending(run, execute=True, executor=executor, retry_invalid=True)
    assert calls.count("polyglot_python_beer-song") == 1
    assert calls.count("polyglot_python_bottle-song") == 2
    row = next(item for item in RunStore(run).read()["tasks"] if item["task_id"].endswith("bottle-song"))
    assert row["attempt_history"]


def test_active_worker_lock_prevents_duplicate_dispatch(tmp_path: Path):
    from agent_benchmark.suite import _claim, execute_pending

    run = create_run(tmp_path, cohort="aider-python-10", agent="qwen-coder", model="qwen38_23GB",
                     base_url=None, api_format=None, llm_monitor=False, recording="off")
    lock = _claim(run)
    with pytest.raises(RuntimeError, match="another worker owns this run"):
        execute_pending(run, execute=True, executor=lambda *_: pytest.fail("must not dispatch"))
    lock.unlink()


def test_uncertain_running_task_is_not_automatically_replayed(tmp_path: Path):
    from agent_benchmark.suite import execute_pending

    run = create_run(tmp_path, cohort="aider-python-10", agent="qwen-coder", model="qwen38_23GB",
                     base_url=None, api_format=None, llm_monitor=False, recording="off")
    RunStore(run).update_task("polyglot_python_beer-song", status="running", started_at="now")
    with pytest.raises(RuntimeError, match="uncertain running task"):
        execute_pending(run, execute=True, executor=lambda *_: pytest.fail("must not duplicate trial"))


def test_resume_dispatches_only_pending_tasks_after_interruption(tmp_path: Path):
    from agent_benchmark.suite import execute_pending

    run = create_run(tmp_path, cohort="aider-python-10", agent="qwen-coder", model="qwen38_23GB",
                     base_url=None, api_format=None, llm_monitor=False, recording="off")
    seen = []

    def interrupted(store, task):
        if task.endswith("bottle-song"):
            raise RuntimeError("fixture interruption between tasks")
        seen.append(task)
        return {"status": "passed", "trial_id": "accepted-first", "native_artifacts": []}

    with pytest.raises(RuntimeError, match="fixture interruption"):
        execute_pending(run, execute=True, executor=interrupted)
    assert RunStore(run).read()["tasks"][0]["status"] == "passed"
    remaining = []
    execute_pending(run, execute=True, executor=lambda store, task: (
        remaining.append(task) or {"status": "failed", "trial_id": f"trial-{len(remaining)}", "native_artifacts": []}
    ))
    assert "polyglot_python_beer-song" not in remaining
    assert remaining[0] == "polyglot_python_bottle-song"
