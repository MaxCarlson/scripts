from __future__ import annotations

import os
from agent_benchmark.cli import main, parser
from agent_benchmark.suite_output import capture_process_output
import subprocess
import sys
import pytest


def test_suite_parser_exposes_short_and_long_flags():
    args = parser().parse_args(
        [
            "suite",
            "run",
            "-c",
            "aider-python-10",
            "-a",
            "opencode",
            "-m",
            "openai/model",
            "-L",
            "-U",
            "http://monitor/v1",
            "-R",
            "content",
            "-A",
            "openai_chat_completions",
            "-j",
            "1",
            "-F",
            "-B",
            "-x",
        ]
    )
    assert args.llm_monitor and args.llm_friendly and args.background and args.execute
    assert args.recording == "content"
    assert args.api_format == "openai_chat_completions"


def test_suite_run_requires_explicit_execution_authorization(capsys):
    assert main(["suite", "run", "-c", "aider-python-10", "-F"]) == 2
    assert '"code":"EXECUTION_AUTHORIZATION_REQUIRED"' in capsys.readouterr().out


def test_monitor_preflight_errors_keep_their_stable_code():
    from agent_benchmark.suite_cli import _error_code
    from agent_benchmark.suite_monitor import MonitorPreflightError

    assert _error_code(MonitorPreflightError("unavailable")) == "MONITOR_PREFLIGHT_FAILED"


def test_all_suite_read_commands_accept_friendly_flag():
    for argv in (
        ["suite", "plan", "-c", "aider-python-10", "-F"],
        ["suite", "status", "-r", "missing", "-F"],
        ["suite", "resume", "-r", "missing", "-F"],
        ["suite", "report", "-r", "missing", "-F"],
    ):
        args = parser().parse_args(argv)
        assert args.llm_friendly is True


def test_suite_status_without_id_lists_empty_run_store(tmp_path, monkeypatch, capsys):
    import agent_benchmark.suite_cli as suite_cli
    from agent_benchmark.cli import main

    monkeypatch.setattr(suite_cli, "DEFAULT_RUNS", tmp_path / "absent-runs")
    assert main(["suite", "status"]) == 0
    assert capsys.readouterr().out.strip() == "No saved suite runs."


def test_suite_list_defaults_to_table(capsys):
    from agent_benchmark.cli import main

    assert main(["suite", "list"]) == 0
    output = capsys.readouterr().out
    assert "Registered Datasets" in output
    assert not output.lstrip().startswith("{")


def test_llm_friendly_plan_preserves_harbor_execution_spec(monkeypatch, capsys):
    import agent_benchmark.suite_cli as suite_cli

    calls = []

    def fake_build_manifest(**kwargs):
        calls.append(kwargs)
        return {"readiness": {"is_runnable": True}}

    monkeypatch.setattr(suite_cli, "build_manifest", fake_build_manifest)
    base = ["suite", "plan", "-c", "aider-python-10", "-a", "opencode", "-m", "openai/model"]
    assert main(base) == 0
    capsys.readouterr()
    assert main([*base, "-F"]) == 0
    capsys.readouterr()
    assert calls[0] == calls[1]


def test_suite_run_resolves_frozen_revision_before_creating_or_dispatching_run(monkeypatch, tmp_path):
    import agent_benchmark.suite_cli as suite_cli

    planned = {
        "cohort": "aider-python-10",
        "dataset": "aider/aider-polyglot",
        "source_revision": "f30b14415dd733c83627204bad0af69a89ceb46f",
        "tasks": ["polyglot_python_beer-song"],
        "agent": "oracle",
        "model": None,
        "provenance": {
            "effective_api_format": None,
            "registry_revision_required": True,
            "harbor_dataset": "aider-polyglot",
        },
        "readiness": {"is_runnable": True, "blockers": []},
    }
    calls = []
    monkeypatch.setattr(suite_cli, "build_manifest", lambda **_kwargs: planned)
    monkeypatch.setattr(
        suite_cli,
        "resolve_frozen_registry_snapshot",
        lambda **kwargs: (calls.append(kwargs) or (b"registry snapshot", {"verified": True})),
    )
    monkeypatch.setattr(suite_cli, "include_registry_resolution", lambda manifest, resolution: manifest)
    monkeypatch.setattr(suite_cli, "create_run", lambda *args, **kwargs: calls.append((args, kwargs)) or tmp_path)
    monkeypatch.setattr(
        suite_cli,
        "RunStore",
        lambda _path: type(
            "Store",
            (),
            {
                "manifest": {
                    "run_id": "fixture",
                    "tasks": ["polyglot_python_beer-song"],
                    "provenance": {"effective_api_format": None},
                }
            },
        )(),
    )
    monkeypatch.setattr(
        suite_cli,
        "execute_pending",
        lambda *_args, **_kwargs: {
            "run_id": "fixture",
            "state": "finished",
            "planned": 1,
            "scored": 1,
            "passed": 1,
            "failed": 0,
            "timed_out": 0,
            "infrastructure_invalid": 0,
            "pending": 0,
            "pass_rate_pct": 100.0,
            "coverage_pct": 100.0,
        },
    )

    assert main(["suite", "run", "-c", "aider-python-10", "-x", "-o", str(tmp_path)]) == 0
    assert calls[0]["expected_revision"] == planned["source_revision"]
    assert calls[0]["task_ids"] == planned["tasks"]
    assert calls[1][1]["registry_snapshot"] == b"registry snapshot"


def test_suite_run_aborts_before_run_creation_if_frozen_revision_is_unavailable(monkeypatch, tmp_path, capsys):
    import agent_benchmark.suite_cli as suite_cli
    from agent_benchmark.suite_revision import DatasetRevisionError

    monkeypatch.setattr(
        suite_cli,
        "build_manifest",
        lambda **_kwargs: {
            "cohort": "aider-python-10",
            "dataset": "aider/aider-polyglot",
            "source_revision": "f30b14415dd733c83627204bad0af69a89ceb46f",
            "tasks": ["polyglot_python_beer-song"],
            "provenance": {
                "registry_revision_required": True,
                "harbor_dataset": "aider-polyglot",
            },
            "readiness": {"is_runnable": True, "blockers": []},
        },
    )
    monkeypatch.setattr(
        suite_cli,
        "resolve_frozen_registry_snapshot",
        lambda **_kwargs: (_ for _ in ()).throw(
            DatasetRevisionError("Harbor registry unavailable; no inference was dispatched")
        ),
    )
    created = []
    monkeypatch.setattr(suite_cli, "create_run", lambda *args, **kwargs: created.append(args))

    assert main(["suite", "run", "-c", "aider-python-10", "-x", "-F", "-o", str(tmp_path)]) == 2
    assert created == []
    assert "DATASET_REVISION_PREFLIGHT_FAILED" in capsys.readouterr().out


def test_external_run_accepts_compact_output_flag():
    args = parser().parse_args(["external", "run", "-F", "-x"])
    assert args.llm_friendly


def test_process_output_capture_keeps_large_subprocess_log_off_caller_stdout(tmp_path, capsys):
    path = tmp_path / "logs" / "task.log"
    with capture_process_output(path):
        subprocess.run([sys.executable, "-c", "print('fixture-output' * 1000)"], check=True)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert path.stat().st_size > 10_000


def test_background_launch_detaches_and_passes_explicit_worker_authorization(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import agent_benchmark.suite as suite

    run = suite.create_run(
        tmp_path,
        cohort="aider-python-10",
        agent="qwen-coder",
        model="qwen38_23GB",
        base_url=None,
        api_format=None,
        llm_monitor=False,
        recording="off",
    )
    args_seen = {}

    def fake_popen(args, **kwargs):
        args_seen.update(args=args, kwargs=kwargs)
        suite.RunStore(run).set_state("running", worker_pid=os.getpid())
        return SimpleNamespace(pid=os.getpid())

    monkeypatch.setattr(suite.subprocess, "Popen", fake_popen)
    assert suite.launch_background(run) == os.getpid()
    assert "--execute" in args_seen["args"]
    if suite.os.name == "nt":
        assert args_seen["kwargs"]["creationflags"] & suite.subprocess.DETACHED_PROCESS
    else:
        assert args_seen["kwargs"]["start_new_session"] is True
    with pytest.raises(RuntimeError, match="already owns"):
        suite.launch_background(run)


def test_background_retry_policy_is_forwarded_to_detached_worker(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import agent_benchmark.suite as suite

    run = suite.create_run(
        tmp_path,
        cohort="aider-python-10",
        agent="qwen-coder",
        model="qwen38_23GB",
        base_url=None,
        api_format=None,
        llm_monitor=False,
        recording="off",
    )
    args_seen = {}

    def fake_popen(args, **kwargs):
        args_seen["args"] = args
        suite.RunStore(run).set_state("running", worker_pid=os.getpid())
        return SimpleNamespace(pid=os.getpid())

    monkeypatch.setattr(suite.subprocess, "Popen", fake_popen)
    suite.launch_background(run, retry_invalid=True)
    assert "--retry-invalid" in args_seen["args"]


def test_background_resume_clears_previous_worker_pid(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import agent_benchmark.suite as suite

    run = suite.create_run(
        tmp_path,
        cohort="aider-python-10",
        agent="qwen-coder",
        model="model",
        base_url=None,
        api_format=None,
        llm_monitor=False,
        recording="off",
    )
    suite.RunStore(run).set_state("interrupted", worker_pid=999999)

    def fake_popen(_args, **_kwargs):
        assert suite.RunStore(run).read()["worker_pid"] is None
        suite.RunStore(run).set_state("running", worker_pid=os.getpid())
        return SimpleNamespace(pid=os.getpid())

    monkeypatch.setattr(suite.subprocess, "Popen", fake_popen)
    assert suite.launch_background(run) == os.getpid()


def test_detached_worker_lifecycle_reconciles_a_completed_fixture_without_inference(tmp_path):
    import time
    import agent_benchmark.suite as suite

    run = suite.create_run(
        tmp_path,
        cohort="aider-python-10",
        agent="qwen-coder",
        model="fixture-model",
        base_url=None,
        api_format=None,
        llm_monitor=False,
        recording="off",
    )
    store = suite.RunStore(run)
    for task_id in store.manifest["tasks"]:
        store.update_task(task_id, status="passed", trial_id=f"fixture-{task_id}", ended_at="fixture")

    pid = suite.launch_background(run)
    assert pid > 0
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and suite.status_run(run)["state"] not in {"finished", "interrupted"}:
        time.sleep(0.05)

    status = suite.status_run(run)
    assert status["state"] == "finished"
    assert (run / "report.json").is_file()
    assert (run / "logs" / "worker.stdout.log").is_file()
    assert (run / "worker.lock").exists() is False


def test_finished_event_omits_repeated_per_task_details(tmp_path):
    from agent_benchmark.suite_cli import _finished_payload

    summary = {
        "run_id": "run-1",
        "state": "finished",
        "planned": 10,
        "scored": 10,
        "passed": 7,
        "failed": 3,
        "timed_out": 0,
        "infrastructure_invalid": 0,
        "pending": 0,
        "pass_rate_pct": 70.0,
        "coverage_pct": 100.0,
        "tasks": [{"task_id": "large-evidence-reference", "log": "logs/task.log"}],
    }
    payload = _finished_payload(summary, tmp_path)
    assert payload["passed"] == 7
    assert "tasks" not in payload
    assert payload["report"].endswith("report.json")


def test_suite_plan_with_monitor_resolves_host_monitor_origin(monkeypatch, capsys):
    import agent_benchmark.suite_cli as suite_cli

    def fake_build_manifest(**kwargs):
        return {
            "agent": kwargs.get("agent"),
            "model": kwargs.get("model"),
            "provenance": {"effective_api_format": "openai_chat_completions"},
            "readiness": {"is_runnable": True},
        }

    recovered = []

    def fake_recover_managed_monitor(**kwargs):
        recovered.append(kwargs)
        return {"status": "ready"}

    def fake_validate_monitor(**kwargs):
        return {"status": "ready"}

    monkeypatch.setattr(suite_cli, "build_manifest", fake_build_manifest)
    monkeypatch.setattr("agent_benchmark.suite_recovery.recover_managed_monitor", fake_recover_managed_monitor)
    monkeypatch.setattr(suite_cli, "validate_monitor", fake_validate_monitor)

    cmd = [
        "suite",
        "plan",
        "-c",
        "aider-python-10",
        "-a",
        "opencode",
        "-m",
        "openai/model",
        "-L",
        "-U",
        "http://host.docker.internal:8788/v1",
        "-H",
        "http://127.0.0.1:8788",
        "-F",
    ]
    code = main(cmd)
    out = capsys.readouterr().out
    assert code == 0
    assert "plan_ready" in out
    assert len(recovered) == 1
    assert recovered[0]["host_origin"] == "http://127.0.0.1:8788"


def test_study_prepare_only_creates_run_without_execution_or_monitor(monkeypatch, tmp_path, capsys):
    import agent_benchmark.suite_cli as suite_cli

    plan = {
        "study_adapter": "opencode-v1-isolated-v1",
        "tasks": ["task"],
        "prompt_policy": {"id": "sv0-unmodified-v1"},
        "provenance": {"registry_revision_required": False},
        "readiness": {"is_runnable": True, "blockers": []},
    }
    monkeypatch.setattr(suite_cli, "build_manifest", lambda **_: plan)
    monkeypatch.setattr(suite_cli, "create_run", lambda *a, **kw: tmp_path)
    monkeypatch.setattr(suite_cli, "RunStore", lambda _: type("Store", (), {"manifest": {"run_id": "fixture"}})())
    monkeypatch.setattr(suite_cli, "execute_pending", lambda *a, **kw: pytest.fail("unexpected dispatch"))
    result = main(["suite", "run", "-c", "aider-python-10", "-S", "-I", "1", "-Z", "1", "-N"])
    assert result == 0
    assert "fixture" in capsys.readouterr().out
