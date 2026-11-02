"""Shared test fixtures for Harbor benchmark tests."""

from __future__ import annotations

import json
from pathlib import Path


def create_mock_harbor_job(tmp_path: Path) -> Path:
    """Create a realistic Harbor 0.25.0 job output directory."""
    job_dir = tmp_path / "harbor_job_001"
    job_dir.mkdir(parents=True, exist_ok=True)

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
