import json
import os
import subprocess
import sys

import pytest

from agent_benchmark.study_task_integrity import EXPECTED, verify_study_task_trees


def manifest():
    task = "polyglot_python_beer-song"
    return {
        "tasks": [task],
        "prompt_policy": {"id": "sv0-unmodified-v1"},
        "provenance": {
            "effective_base_url": "http://host.docker.internal:1234/v1",
            "registry_resolution": {
                "tasks": [
                    {
                        "task_id": task,
                        "git_url": "https://github.com/laude-institute/harbor-datasets.git",
                        "git_commit_id": "f30b14415dd733c83627204bad0af69a89ceb46f",
                        "git_path": "datasets/aider_polyglot/" + task,
                    }
                ]
            },
        },
    }


def test_task_digest_drift_is_rejected(monkeypatch):
    task = "polyglot_python_beer-song"

    def run(*args, **kwargs):
        data = [{"task_id": task, "task_sha256": "0" * 64, "verifier_sha256": EXPECTED[task][1]}]
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(data), stderr="")

    monkeypatch.setattr("agent_benchmark.study_task_integrity.subprocess.run", run)
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_study_task_trees(manifest(), python=sys.executable)


def test_changed_registry_path_is_rejected_before_probe(monkeypatch):
    data = manifest()
    data["provenance"]["registry_resolution"]["tasks"][0]["git_path"] = "other/polyglot_python_beer-song"
    monkeypatch.setattr(
        "agent_benchmark.study_task_integrity.subprocess.run",
        lambda *args, **kwargs: pytest.fail("unexpected subprocess"),
    )
    with pytest.raises(ValueError, match="task path"):
        verify_study_task_trees(data, python=sys.executable)


def test_verifier_digest_drift_is_rejected(monkeypatch):
    task = "polyglot_python_beer-song"

    def run(*args, **kwargs):
        data = [{"task_id": task, "task_sha256": EXPECTED[task][0], "verifier_sha256": "0" * 64}]
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(data), stderr="")

    monkeypatch.setattr("agent_benchmark.study_task_integrity.subprocess.run", run)
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_study_task_trees(manifest(), python=sys.executable)


def test_dispatch_stops_on_identity_drift(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from agent_benchmark.harbor.planner import plan_benchmark
    from agent_benchmark.harbor.runner import execute_harbor_run
    from agent_benchmark.study_network_policy import NETWORK_POLICY

    monkeypatch.setattr("agent_benchmark.harbor.runner._require_study_network_qualification", lambda *_: None)

    monkeypatch.setattr("agent_benchmark.harbor.planner.check_docker_readiness", lambda: (True, "ok"))
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_harbor_readiness", lambda: (True, "0.25.0"))
    monkeypatch.setattr("agent_benchmark.harbor.runner.check_docker_readiness", lambda: (True, "ok"))
    monkeypatch.setattr("agent_benchmark.harbor.runner.check_harbor_readiness", lambda: (True, "0.25.0"))
    monkeypatch.setattr("agent_benchmark.harbor.runner.shutil.which", lambda _: "harbor")
    monkeypatch.setattr("agent_benchmark.harbor.runner.command_lock", lambda _: nullcontext())
    registry = tmp_path / "registry" / "registry.json"
    registry.parent.mkdir()
    registry.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("agent_benchmark.suite_revision.verify_saved_registry_snapshot", lambda *_: registry.resolve())
    snapshot = tmp_path / "polyglot_python_beer-song"
    snapshot.mkdir()
    network_row = {
        "source_git_url": "https://github.com/laude-institute/harbor-datasets.git",
        "source_revision": "f30b14415dd733c83627204bad0af69a89ceb46f",
        "network_policy": NETWORK_POLICY,
    }
    monkeypatch.setattr(
        "agent_benchmark.study_network_policy.verify_study_network_manifest",
        lambda *_: (snapshot, network_row),
    )

    def reject(_manifest):
        raise ValueError("digest mismatch")

    monkeypatch.setattr("agent_benchmark.study_task_integrity.verify_study_task_trees", reject)
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.subprocess.run",
        lambda *args, **kwargs: pytest.fail("Harbor dispatch was reached"),
    )
    plan = plan_benchmark("aider/aider-polyglot", agent="opencode", task_ids=["polyglot_python_beer-song"])
    with pytest.raises(ValueError, match="digest mismatch"):
        execute_harbor_run(
            plan,
            execute=True,
            output_dir=tmp_path / "out",
            jobs_dir=tmp_path / "jobs",
            state_dir=tmp_path / "state",
            study_adapter=True,
            study_manifest=manifest(),
            study_policy=manifest()["prompt_policy"],
            registry_path=registry,
            study_run_dir=tmp_path,
        )


def test_cached_harbor_identity_when_runtime_is_available():
    if not os.environ.get("HARBOR_025_PYTHON"):
        pytest.skip("set HARBOR_025_PYTHON to qualify the Harbor cache")
    rows = []
    for task in EXPECTED:
        rows.append(
            {
                "task_id": task,
                "git_url": "https://github.com/laude-institute/harbor-datasets.git",
                "git_commit_id": "f30b14415dd733c83627204bad0af69a89ceb46f",
                "git_path": "datasets/aider_polyglot/" + task,
            }
        )
    data = {"tasks": list(EXPECTED), "provenance": {"registry_resolution": {"tasks": rows}}}
    assert len(verify_study_task_trees(data)) == 3
