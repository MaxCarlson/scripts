"""CLI authorization, preview and independent process behavior."""

import json
import subprocess
import sys

from agent_benchmark.cli import main


def test_run_requires_execute_before_writing_any_files(tmp_path, capsys):
    assert main(["run", "-m", "test", "-o", str(tmp_path / "reports"), "-s", str(tmp_path / "state")]) != 0
    assert not (tmp_path / "reports").exists()
    assert not (tmp_path / "state").exists()
    assert "execute" in capsys.readouterr().err.lower()


def test_experiment_run_can_pause_after_session_creation_for_monitor_attachment():
    from agent_benchmark.cli import parser

    args = parser().parse_args([
        "experiment", "run", "-x", "-m", "qwen38-27b-q4km", "-t", "qwen-file-creation",
        "--pause-before-dispatch",
    ])

    assert args.pause_before_dispatch is True
    assert args.max_ram_percent is None


def test_experiment_run_accepts_explicit_ram_percentage_limit():
    from agent_benchmark.cli import parser

    args = parser().parse_args([
        "experiment", "run", "-x", "-m", "qwen38-27b-q4km", "-t", "qwen-file-creation",
        "--max-ram-percent", "87.5",
    ])

    assert args.max_ram_percent == 87.5


def test_experiment_run_short_aliases_match_long_inference_options():
    from agent_benchmark.cli import parser

    plan_args = parser().parse_args([
        "experiment", "plan", "-m", "qwen38-27b-q4km", "-I", "profile.json", "-A", "invariants.md",
    ])
    assert str(plan_args.inference_profile) == "profile.json"
    assert str(plan_args.instruction_append_file) == "invariants.md"

    args = parser().parse_args([
        "experiment", "run", "-x", "-m", "qwen38-27b-q4km", "-t", "qwen-file-creation",
        "-I", "profile.json", "-A", "invariants.md", "-P",
    ])

    assert str(args.inference_profile) == "profile.json"
    assert str(args.instruction_append_file) == "invariants.md"
    assert args.pause_before_dispatch is True


def test_plan_and_status_are_read_only(tmp_path, capsys):
    state = tmp_path / "state"
    assert main(["plan", "-s", str(state)]) == 0
    assert "py-grep-smoke" in capsys.readouterr().out
    assert main(["status", "-s", str(state)]) == 0
    assert not state.exists()


def test_module_cli_from_another_directory_and_bundled_fixture(tmp_path):
    result = subprocess.run([sys.executable, "-m", "agent_benchmark", "plan", "-s", str(tmp_path / "state")],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "py-grep-smoke" in result.stdout
    assert not (tmp_path / "state").exists()


def test_cleanup_is_preview_without_execute(tmp_path, capsys):
    assert main(["cleanup", "-s", str(tmp_path / "state")]) == 0
    assert not (tmp_path / "state").exists()


def test_modules_first_keeps_cli_and_version_importable():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    script = "import sys; sys.path.insert(0, 'modules'); from agent_benchmark.cli import main; from agent_benchmark import __version__; assert isinstance(__version__, str) and __version__; main(['plan'])"
    result = subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_models_list_json(monkeypatch, capsys):
    from agent_benchmark.models_lifecycle import DownloadedModelInfo, LoadedModelInfo
    import agent_benchmark.cli as cli_mod

    mock_downloaded = [
        DownloadedModelInfo(
            model_key="qwen/qwen3-coder-30b",
            display_name="Qwen 3 Coder 30B",
            architecture="qwen2",
            size_bytes=23000000000,
            quantization="Q5_K_M",
            max_context_length=32768,
            format="gguf",
            path="/models/qwen.gguf",
        )
    ]
    mock_loaded = [
        LoadedModelInfo(
            identifier="inst-1",
            model_key="qwen/qwen3-coder-30b",
            display_name="Qwen 3 Coder 30B",
            status="loaded",
            context_length=32768,
            size_bytes=23000000000,
            max_context_length=32768,
        )
    ]

    monkeypatch.setattr(cli_mod, "list_downloaded_models", lambda **kw: mock_downloaded)
    monkeypatch.setattr(cli_mod, "get_loaded_models", lambda **kw: mock_loaded)

    assert main(["models", "list", "--format", "json"]) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data["downloaded_models"]) == 1
    assert data["downloaded_models"][0]["model_key"] == "qwen/qwen3-coder-30b"
    assert len(data["loaded_models"]) == 1


def test_models_list_table(monkeypatch, capsys):
    from agent_benchmark.models_lifecycle import DownloadedModelInfo
    import agent_benchmark.cli as cli_mod

    mock_downloaded = [
        DownloadedModelInfo(
            model_key="qwen/qwen3-coder-30b",
            display_name="Qwen 3 Coder 30B",
            architecture="qwen2",
            size_bytes=23000000000,
            quantization="Q5_K_M",
            max_context_length=32768,
            format="gguf",
            path="/models/qwen.gguf",
        )
    ]
    monkeypatch.setattr(cli_mod, "list_downloaded_models", lambda **kw: mock_downloaded)
    monkeypatch.setattr(cli_mod, "get_loaded_models", lambda **kw: [])

    assert main(["models", "list", "--format", "table"]) == 0
    captured = capsys.readouterr()
    assert "qwen/qwen3-coder-30b" in captured.out
    assert "qwen2" in captured.out
    assert "Q5_K_M" in captured.out
    assert "DOWNLOADED" in captured.out


def test_experiment_run_requires_execute(capsys):
    assert main(["experiment", "run", "-m", "model-a"]) != 0
    captured = capsys.readouterr()
    assert "experiment run requires explicit -x/--execute authorization" in captured.err


def test_experiment_plan_output(capsys, monkeypatch):
    from agent_benchmark import cli
    from agent_benchmark.models_lifecycle import DownloadedModelInfo

    async def local_models():
        return [DownloadedModelInfo("meta/muse-glimmer", "Muse Glimmer", "muse", 100, "Q4_K_M", 32768,
                                    "gguf", "meta/muse-glimmer")]

    async def effective_ids(*args, **kwargs):
        return set(), True

    monkeypatch.setattr(cli, "list_downloaded_models", local_models)
    monkeypatch.setattr(cli, "get_effective_lmstudio_model_ids", effective_ids)
    ret = main(["experiment", "plan", "-m", "meta/muse-glimmer", "-m", "qwen38_23GB", "-r", "2"])
    assert ret == 0
    captured = capsys.readouterr()
    plan_data = json.loads(captured.out)
    assert plan_data["model_keys"] == ["meta/muse-glimmer", "qwen38_23GB"]
    assert plan_data["repetitions"] == 2
    # At least 1 task (py-grep-smoke) * 2 models * 2 repetitions = 4 planned trials
    assert plan_data["total_trials"] >= 4
    assert plan_data["config"]["budget_profile"] == "canonical-120s"
    assert plan_data["config"]["metadata"]["requested_context_length"] == 16384
    assert len(plan_data["planned_trials"]) == plan_data["total_trials"]
    assert [row["status"] for row in plan_data["model_readiness"]] == ["registration_required", "unavailable"]


def test_experiment_plan_accepts_budget_and_context_short_flags(capsys, monkeypatch):
    from agent_benchmark import cli
    from agent_benchmark.models_lifecycle import DownloadedModelInfo

    async def local_models():
        return [DownloadedModelInfo("local-model", "Local", "arch", 100, "Q4", 32768, "gguf", "model")]

    async def effective_ids(*args, **kwargs):
        return {"local-model"}, True

    monkeypatch.setattr(cli, "list_downloaded_models", local_models)
    monkeypatch.setattr(cli, "get_effective_lmstudio_model_ids", effective_ids)
    assert main(["experiment", "plan", "-m", "local-model", "-b", "canonical-60s", "-c", "8192"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["config"]["budget_profile"] == "canonical-60s"
    assert data["config"]["metadata"]["requested_context_length"] == 8192
    assert data["model_readiness"][0]["requested_context_length"] == 8192


def test_experiment_status_and_report(tmp_path, capsys):
    from benchmark_core import Experiment, ExperimentConfig, ExperimentRunRef, save_experiment, format_utc_timestamp

    exp_dir = tmp_path / "exp_01"
    config = ExperimentConfig(
        experiment_id="EXP_TEST_CLI",
        created_at=format_utc_timestamp(),
        suite_id="agent-benchmark",
        suite_version="1.3.0",
        task_ids=["py-grep-smoke"],
        variant_ids=["model-a"],
        repetitions=1,
        scoring_basis="worker_first_attempt_full_success",
        budget_profile="canonical-60s",
    )
    ref = ExperimentRunRef(
        run_id="run-01",
        run_dir="runs/run-01",
        variant_id="model-a",
        suite_id="agent-benchmark",
        suite_version="1.3.0",
        scoring_basis="worker_first_attempt_full_success",
        budget_profile="canonical-60s",
        comparison_eligible=True,
    )
    exp = Experiment(config=config, run_refs=[ref])
    save_experiment(exp_dir, exp)

    # Status table
    assert main(["experiment", "status", "-e", str(exp_dir), "--format", "table"]) == 0
    out_table = capsys.readouterr().out
    assert "EXP_TEST_CLI" in out_table
    assert "agent-benchmark" in out_table

    # Status json
    assert main(["experiment", "status", "-e", str(exp_dir), "--format", "json"]) == 0
    out_json = capsys.readouterr().out
    assert "EXP_TEST_CLI" in out_json

    # Report command
    assert main(["experiment", "report", "-e", str(exp_dir)]) == 0


def test_experiment_run_e2e(tmp_path, monkeypatch, capsys):
    from agent_benchmark.scheduler import ExperimentScheduler
    from agent_benchmark import models_lifecycle
    from agent_benchmark.telemetry import ResourceSnapshot
    from benchmark_core import MetricQuality, MetricValue, TrialResult, TrialStatus

    reports_dir = tmp_path / "reports"
    state_dir = tmp_path / "state"

    loaded_state = ["qwen-model-1"]
    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(
        ram_pct=40, ram_available_bytes=32 * 1024**3,
        gpu_memory_used_bytes=4 * 1024**3, gpu_memory_total_bytes=32 * 1024**3,
    ))

    async def mock_lms_runner(cmd: list[str]) -> tuple[int, str, str]:
        if cmd[:2] == ["lms", "ps"]:
            res = [
                {
                    "identifier": k,
                    "modelKey": k,
                    "status": "idle",
                    "contextLength": 16384,
                    "sizeBytes": 10000000,
                    "maxContextLength": 32768,
                }
                for k in loaded_state
            ]
            return 0, json.dumps(res), ""
        elif cmd[:2] == ["lms", "unload"]:
            loaded_state.clear()
            return 0, "unloaded", ""
        elif cmd[:2] == ["lms", "load"]:
            target = cmd[2]
            if "--estimate-only" in cmd:
                return 0, "Estimated GPU Memory: 18 GiB\nEstimated Total Memory: 22 GiB", ""
            loaded_state.append(target)
            return 0, f"loaded {target}", ""
        return 0, "", ""

    async def mock_executor(
        planned_trial, task, run_dir, evidence_dir, base_url, task_sec, grace_sec, verifier_sec
    ):
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "opencode_events.jsonl").write_text('{"event": "start"}\n{"event": "end"}\n')
        (evidence_dir / "test_report.json").write_text('{"summary": {"outcome": "passed"}}\n')
        return TrialResult(
            run_id=planned_trial.run_id,
            trial_id=f"trial-{planned_trial.trial_index + 1:03d}",
            task_id=planned_trial.task_id,
            variant_id=planned_trial.model_key,
            repetition=planned_trial.repetition,
            status=TrialStatus.PASSED,
            metrics={
                "duration.wall_ms": MetricValue(500.0, "ms", "timer", MetricQuality.MEASURED),
                "tokens.input": MetricValue(120, "tokens", "bridge", MetricQuality.MEASURED),
                "tokens.output": MetricValue(45, "tokens", "bridge", MetricQuality.MEASURED),
            },
            details={"evidence_path": f"evidence/trial-{planned_trial.trial_index + 1:03d}"},
        )

    orig_init = ExperimentScheduler.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["trial_executor"] = mock_executor
        kwargs["lms_runner"] = mock_lms_runner
        orig_init(self, *args, **kwargs)

    monkeypatch.setattr(ExperimentScheduler, "__init__", patched_init)

    ret = main([
        "experiment",
        "run",
        "-x",
        "-m", "qwen-model-1",
        "-m", "qwen-model-2",
        "-r", "1",
        "-o", str(reports_dir),
        "-s", str(state_dir),
        "-Q",
    ])
    assert ret == 0

    # Locate experiment dir under reports_dir
    exp_dirs = [d for d in reports_dir.iterdir() if d.is_dir() and d.name.startswith("EXP_")]
    assert len(exp_dirs) == 1
    exp_dir = exp_dirs[0]

    # Check generated files
    assert (exp_dir / "experiment.json").exists()
    assert (exp_dir / "run-references.json").exists()
    assert (exp_dir / "comparison.json").exists()
    assert (exp_dir / "comparison.csv").exists()
    assert (exp_dir / "report.md").exists()
    assert (exp_dir / "index.html").exists()

    html_content = (exp_dir / "index.html").read_text(encoding="utf-8")
    assert "qwen-model-1" in html_content
    assert "qwen-model-2" in html_content
    assert "<script src=" not in html_content
    assert '<link rel="stylesheet"' not in html_content
    assert "googleapis.com" not in html_content
    assert "cdnjs.cloudflare.com" not in html_content

    # Status check
    assert main(["experiment", "status", "-e", str(exp_dir)]) == 0

    # Report regeneration
    assert main(["experiment", "report", "-e", str(exp_dir)]) == 0
