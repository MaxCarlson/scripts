"""Tests for Harbor evaluation artifact importer and result normalizer."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from agent_benchmark.harbor import (
    HarborImportError,
    HarborImporter,
    collect_run_summaries,
    render_leaderboard_table,
)
from benchmark_core import load_run_info, load_trials


def _create_mock_harbor_job(tmp_path: Path) -> Path:
    """Create a realistic Harbor 0.25.0 job output directory."""
    job_dir = tmp_path / "harbor_job_001"
    job_dir.mkdir(parents=True)

    # lock.json
    lock_data = {
        "schema_version": 3,
        "created_at": "2026-10-29T10:00:00Z",
        "harbor": {
            "version": "0.25.0",
            "git_commit_hash": "a1b2c3d4e5f6",
            "is_editable": False,
        },
        "n_concurrent_trials": 1,
        "retry": {"max_retries": 0},
        "trials": [
            {
                "schema_version": 2,
                "task": {
                    "name": "python/bank-account",
                    "version": "1.0.0",
                    "type": "local",
                    "digest": "sha256:" + "a" * 64,
                },
                "agent": {"name": "oracle"},
            },
            {
                "schema_version": 2,
                "task": {
                    "name": "python/grep",
                    "version": "1.0.0",
                    "type": "local",
                    "digest": "sha256:" + "b" * 64,
                },
                "agent": {"name": "oracle"},
            },
            {
                "schema_version": 2,
                "task": {
                    "name": "python/collatz-conjecture",
                    "version": "1.0.0",
                    "type": "local",
                    "digest": "sha256:" + "c" * 64,
                },
                "agent": {"name": "oracle"},
            },
            {
                "schema_version": 2,
                "task": {
                    "name": "python/allergies",
                    "version": "1.0.0",
                    "type": "local",
                    "digest": "sha256:" + "d" * 64,
                },
                "agent": {"name": "oracle"},
            },
        ],
    }
    (job_dir / "lock.json").write_text(json.dumps(lock_data, indent=2), encoding="utf-8")

    # result.json
    job_data = {
        "id": "11111111-2222-3333-4444-555555555555",
        "started_at": "2026-10-29T10:00:00Z",
        "finished_at": "2026-10-29T10:05:00Z",
        "n_total_trials": 4,
        "stats": {
            "n_completed_trials": 4,
            "n_errored_trials": 1,
            "n_running_trials": 0,
            "n_pending_trials": 0,
        },
        "trial_results": [
            # Trial 1: Passing
            {
                "id": "aaaa1111-0000-0000-0000-000000000001",
                "task_name": "python/bank-account",
                "trial_name": "python/bank-account__oracle",
                "source": "aider/aider-polyglot",
                "task_checksum": "sha256:" + "a" * 64,
                "agent_info": {
                    "name": "oracle",
                    "version": "0.25.0",
                    "model_info": {"name": "reference-solution", "provider": "ground-truth"},
                },
                "agent_result": {
                    "n_input_tokens": 1200,
                    "n_output_tokens": 300,
                    "cost_usd": 0.005,
                },
                "verifier_result": {
                    "rewards": {"reward": 1.0},
                },
                "started_at": "2026-10-29T10:00:05Z",
                "finished_at": "2026-10-29T10:00:25Z",
            },
            # Trial 2: Failing
            {
                "id": "aaaa1111-0000-0000-0000-000000000002",
                "task_name": "python/grep",
                "trial_name": "python/grep__oracle",
                "source": "aider/aider-polyglot",
                "task_checksum": "sha256:" + "b" * 64,
                "agent_info": {
                    "name": "oracle",
                    "version": "0.25.0",
                    "model_info": {"name": "reference-solution", "provider": "ground-truth"},
                },
                "verifier_result": {
                    "rewards": {"reward": 0.0},
                },
                "started_at": "2026-10-29T10:00:30Z",
                "finished_at": "2026-10-29T10:00:50Z",
            },
            # Trial 3: Timed out (AgentTimeoutError)
            {
                "id": "aaaa1111-0000-0000-0000-000000000003",
                "task_name": "python/collatz-conjecture",
                "trial_name": "python/collatz-conjecture__oracle",
                "source": "aider/aider-polyglot",
                "task_checksum": "sha256:" + "c" * 64,
                "agent_info": {
                    "name": "oracle",
                    "version": "0.25.0",
                    "model_info": {"name": "reference-solution", "provider": "ground-truth"},
                },
                "exception_info": {
                    "exception_type": "AgentTimeoutError",
                    "exception_message": "Agent exceeded allotted time budget of 120s",
                    "occurred_at": "2026-10-29T10:02:50Z",
                },
                "started_at": "2026-10-29T10:01:00Z",
                "finished_at": "2026-10-29T10:03:00Z",
            },
            # Trial 4: Infrastructure error (SandboxBuildFailedError)
            {
                "id": "aaaa1111-0000-0000-0000-000000000004",
                "task_name": "python/allergies",
                "trial_name": "python/allergies__oracle",
                "source": "aider/aider-polyglot",
                "task_checksum": "sha256:" + "d" * 64,
                "agent_info": {
                    "name": "oracle",
                    "version": "0.25.0",
                    "model_info": {"name": "reference-solution", "provider": "ground-truth"},
                },
                "exception_info": {
                    "exception_type": "SandboxBuildFailedError",
                    "exception_message": "Docker container build failed: package mirror timeout",
                    "occurred_at": "2026-10-29T10:03:10Z",
                },
                "started_at": "2026-10-29T10:03:05Z",
                "finished_at": "2026-10-29T10:03:15Z",
            },
        ],
    }
    (job_dir / "result.json").write_text(json.dumps(job_data, indent=2), encoding="utf-8")
    return job_dir


def test_import_valid_job(tmp_path: Path):
    job_dir = _create_mock_harbor_job(tmp_path)
    out_dir = tmp_path / "imported_run"

    importer = HarborImporter(job_dir)
    saved_dir, summary = importer.import_to(out_dir)

    assert saved_dir == out_dir
    assert summary["scheduled"] == 4
    assert summary["completed"] == 4
    assert summary["scored"] == 3  # passed (1) + failed (1) + timed_out (1)
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["timed_out"] == 1
    assert summary["infrastructure_error"] == 1
    assert summary["points_earned"] == 1.0
    assert summary["pass_rate_pct"] == pytest.approx(33.33, rel=1e-2)  # 1/3
    assert summary["coverage_pct"] == 75.0  # 3/4 scored

    # Verify canonical benchmark_core storage
    run_info = load_run_info(out_dir / "run.json")
    assert run_info.run_id == "11111111-2222-3333-4444-555555555555"
    assert run_info.suite_id == "aider/aider-polyglot"
    assert run_info.suite_version == "1.0.0"
    assert run_info.environment["harbor_package_version"] == "0.25.0"
    assert "python/bank-account" in run_info.metadata["task_content_fingerprints"]
    assert run_info.metadata["task_content_fingerprints"]["python/bank-account"].startswith("sha256:")
    assert run_info.scoring_basis == "external_verifier_pass_v1"
    assert len(run_info.task_ids) == 4

    trials = list(load_trials(out_dir / "trials.jsonl"))
    assert len(trials) == 4

    # Check Trial 1 (pass)
    t1 = next(t for t in trials if t.task_id == "python/bank-account")
    assert t1.status == "passed"
    assert t1.metrics["points"].value == 1.0
    assert t1.metrics["verifier.reward"].value == 1.0
    assert t1.metrics["tokens.worker.input"].value == 1200
    assert t1.metrics["cost.usd"].value == 0.005
    assert t1.details["scope_compliance"] == "unavailable"

    # Check Trial 2 (fail)
    t2 = next(t for t in trials if t.task_id == "python/grep")
    assert t2.status == "failed"
    assert t2.metrics["points"].value == 0.0
    assert t2.metrics["verifier.reward"].value == 0.0

    # Check Trial 3 (timed out)
    t3 = next(t for t in trials if t.task_id == "python/collatz-conjecture")
    assert t3.status == "timed_out"
    assert t3.metrics["points"].value == 0.0
    assert t3.details["failure_cause"] == "agent_exhausted_budget"

    # Check Trial 4 (infrastructure error)
    t4 = next(t for t in trials if t.task_id == "python/allergies")
    assert t4.status == "infrastructure_error"
    assert t4.metrics["points"].value is None
    assert t4.metrics["points"].quality == "unavailable"
    assert t4.details["failure_cause"] == "sandbox_failed"


def test_idempotent_reimport(tmp_path: Path):
    """Importing the same completed Harbor job twice produces identical normalized results without duplicate records."""
    job_dir = _create_mock_harbor_job(tmp_path)
    out_dir = tmp_path / "imported_run"

    importer = HarborImporter(job_dir)
    _, summary1 = importer.import_to(out_dir)
    _, summary2 = importer.import_to(out_dir)

    assert summary1 == summary2

    trials = list(load_trials(out_dir / "trials.jsonl"))
    assert len(trials) == 4  # No duplicates created


def test_missing_or_corrupt_job_dir(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist"
    with pytest.raises(HarborImportError, match="not found"):
        HarborImporter(nonexistent)

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    importer = HarborImporter(empty_dir)
    with pytest.raises(HarborImportError, match="Missing root result.json"):
        importer.load_job()

    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    (corrupt_dir / "result.json").write_text("{not valid json", encoding="utf-8")
    importer2 = HarborImporter(corrupt_dir)
    with pytest.raises(HarborImportError, match="Failed to parse"):
        importer2.load_job()


def test_leaderboard_rendering(tmp_path: Path):
    job_dir = _create_mock_harbor_job(tmp_path)
    out_dir = tmp_path / "imported_run"
    HarborImporter(job_dir).import_to(out_dir)

    summaries = collect_run_summaries(out_dir)
    assert len(summaries) == 1
    assert summaries[0]["passed"] == 1
    assert summaries[0]["scored"] == 3
    assert summaries[0]["errors"] == 1

    table_md = render_leaderboard_table(summaries)
    assert "Benchmark: aider/aider-polyglot" in table_md
    assert "`oracle`" in table_md
    assert "33.3%" in table_md


def test_dataset_identity_with_explicit_version(tmp_path: Path):
    job_dir = tmp_path / "harbor_job_tb"
    job_dir.mkdir(parents=True)

    job_data = {
        "id": "22222222-3333-4444-5555-666666666666",
        "started_at": "2026-10-29T11:00:00Z",
        "finished_at": "2026-10-29T11:01:00Z",
        "n_total_trials": 1,
        "stats": {"n_completed_trials": 1},
        "trial_results": [
            {
                "id": "bbbb1111-0000-0000-0000-000000000001",
                "task_name": "terminal-bench/find-large-files",
                "trial_name": "terminal-bench/find-large-files__oracle",
                "source": "terminal-bench@4.0.0",
                "agent_info": {"name": "oracle"},
                "verifier_result": {"rewards": {"reward": 1.0}},
            }
        ],
    }
    (job_dir / "result.json").write_text(json.dumps(job_data, indent=2), encoding="utf-8")

    out_dir = tmp_path / "imported_tb"
    HarborImporter(job_dir).import_to(out_dir)

    run_info = load_run_info(out_dir / "run.json")
    assert run_info.suite_id == "terminal-bench"
    assert run_info.suite_version == "4.0.0"
    assert run_info.environment["harbor_package_version"] == "0.25.0"


def test_deduplication_in_reporting(tmp_path: Path):
    job_dir = _create_mock_harbor_job(tmp_path)
    out_dir_1 = tmp_path / "runs" / "import_copy_1"
    out_dir_2 = tmp_path / "runs" / "import_copy_2"

    # Import identical job into two directories under the same parent
    HarborImporter(job_dir).import_to(out_dir_1)
    HarborImporter(job_dir).import_to(out_dir_2)

    # Scanning parent directory should deduplicate and return only 1 summary entry
    summaries = collect_run_summaries(tmp_path / "runs")
    assert len(summaries) == 1


def test_import_authentic_harbor_artifact(tmp_path: Path):
    fixture_path = Path(__file__).parent / "fixtures" / "harbor_native_0_25_0.json"
    assert fixture_path.is_file(), f"Native Harbor fixture not found at {fixture_path}"

    job_dir = tmp_path / "authentic_harbor_job"
    job_dir.mkdir(parents=True)
    (job_dir / "result.json").write_text(fixture_path.read_text(encoding="utf-8"), encoding="utf-8")

    out_dir = tmp_path / "imported_authentic"
    importer = HarborImporter(job_dir)
    saved_dir, summary = importer.import_to(out_dir)

    assert saved_dir == out_dir
    assert summary["scheduled"] == 3
    assert summary["completed"] == 3
    assert summary["scored"] == 2  # 1 passed, 1 failed, 1 infra error
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["infrastructure_error"] == 1
    assert summary["points_earned"] == 1.0

    run_info = load_run_info(out_dir / "run.json")
    assert run_info.suite_id == "aider/aider-polyglot"
    assert run_info.suite_version == "1.0.0"
    assert run_info.metadata["harbor_package_version"] == "0.25.0"


