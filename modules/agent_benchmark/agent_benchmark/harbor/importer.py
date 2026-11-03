"""Strict, version-aware importer for Harbor evaluation job results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark_core import (
    MetricValue,
    RunInfo,
    TrialResult,
    format_utc_timestamp,
    generate_reports,
    save_run,
    summarize,
)

from .models import (
    HarborJobLock,
    HarborJobResult,
    HarborTrialResult,
    evaluate_trial_status,
)


class HarborImportError(ValueError):
    """Raised when Harbor artifacts are missing, corrupt, or invalid."""


class HarborImporter:
    """Imports Harbor evaluation jobs into canonical benchmark_core storage."""

    def __init__(self, job_dir: Path | str):
        self.job_dir = Path(job_dir).resolve()
        if not self.job_dir.is_dir():
            raise HarborImportError(f"Harbor job directory not found: {self.job_dir}")

    def load_job(self) -> tuple[HarborJobResult, HarborJobLock | None, list[HarborTrialResult]]:
        """Load and validate Harbor JobResult, JobLock, and all trial results."""
        result_file = self.job_dir / "result.json"
        if not result_file.is_file():
            raise HarborImportError(f"Missing root result.json in {self.job_dir}")

        try:
            job_data = json.loads(result_file.read_text(encoding="utf-8", errors="replace"))
            job_result = HarborJobResult.model_validate(job_data)
        except Exception as exc:
            raise HarborImportError(f"Failed to parse job result.json in {self.job_dir}: {exc}") from exc

        # Optional lock.json
        job_lock: HarborJobLock | None = None
        lock_file = self.job_dir / "lock.json"
        if lock_file.is_file():
            try:
                lock_data = json.loads(lock_file.read_text(encoding="utf-8", errors="replace"))
                job_lock = HarborJobLock.model_validate(lock_data)
            except Exception:
                job_lock = None

        # Discover trial results: combine trials from job_result and individual trial directories
        trials_by_id: dict[str, HarborTrialResult] = {}
        for tr in job_result.trial_results:
            trials_by_id[str(tr.id)] = tr

        # Search for trial subdirectories that have their own result.json
        for child in self.job_dir.iterdir():
            if child.is_dir() and (child / "result.json").is_file():
                try:
                    trial_data = json.loads((child / "result.json").read_text(encoding="utf-8", errors="replace"))
                    trial = HarborTrialResult.model_validate(trial_data)
                    trials_by_id[str(trial.id)] = trial
                except Exception:
                    continue

        trials = list(trials_by_id.values())
        if not trials and job_result.n_total_trials > 0:
            raise HarborImportError(f"Job specifies {job_result.n_total_trials} trials but none could be loaded")

        return job_result, job_lock, trials

    def normalize(
        self,
        job_result: HarborJobResult,
        job_lock: HarborJobLock | None,
        harbor_trials: list[HarborTrialResult],
        *,
        process_returncode: int = 0,
    ) -> tuple[RunInfo, list[TrialResult], dict[str, Any]]:
        """Normalize Harbor data into canonical RunInfo and TrialResult records."""
        task_digests = job_lock.task_digests() if job_lock else {}
        harbor_version = (
            job_lock.harbor.version
            if job_lock and job_lock.harbor and job_lock.harbor.version
            else "0.25.0"
        )

        # Sort trials deterministically by task_name and trial_name
        sorted_harbor_trials = sorted(
            harbor_trials,
            key=lambda t: (t.task_name, t.trial_name, str(t.id)),
        )

        # Track repetitions per (task_name, variant_id)
        rep_counters: dict[tuple[str, str], int] = {}
        canonical_trials: list[TrialResult] = []
        task_ids_set: set[str] = set()
        task_fingerprints: dict[str, str] = {}
        variants_dict: dict[str, dict[str, Any]] = {}

        # Scoring counters
        stats = {
            "scheduled": job_result.n_total_trials or len(sorted_harbor_trials),
            "completed": 0,
            "scored": 0,
            "passed": 0,
            "failed": 0,
            "timed_out": 0,
            "infrastructure_error": 0,
            "unscored": 0,
            "points_earned": 0.0,
            "wall_time_ms": [],
        }

        # Resolve the dataset identity from immutable task-lock provenance first.
        # Harbor's `source` field is not sufficient: both Terminal-Bench 2.0 and
        # later releases can report the generic value `terminal-bench`.
        raw_source: str | None = None
        for ht in sorted_harbor_trials:
            if ht.source:
                raw_source = ht.source
                break

        if not raw_source and job_lock:
            trial_list = (
                job_lock.trials
                if isinstance(job_lock.trials, list)
                else list(job_lock.trials.values())
            )
            for t_lock in trial_list:
                if t_lock.task and t_lock.task.source:
                    raw_source = t_lock.task.source
                    break

        task_locks = []
        if job_lock:
            task_locks = (
                job_lock.trials
                if isinstance(job_lock.trials, list)
                else list(job_lock.trials.values())
            )
        lock_tasks = [trial.task for trial in task_locks if trial.task]
        locked_repos = {task.git_url.rstrip("/") for task in lock_tasks if task.git_url}
        locked_revisions = {task.git_commit_id for task in lock_tasks if task.git_commit_id}
        from .datasets import DATASETS

        identity = None
        if len(locked_repos) == 1 and len(locked_revisions) == 1:
            identity = next(
                (
                    descriptor
                    for descriptor in DATASETS.values()
                    if descriptor.source_repo
                    and descriptor.source_repo.rstrip("/") in locked_repos
                    and (
                        not descriptor.source_revision
                        or any(
                            revision.startswith(descriptor.source_revision)
                            or descriptor.source_revision.startswith(revision)
                            for revision in locked_revisions
                        )
                    )
                ),
                None,
            )

        raw_source = raw_source or "harbor-benchmark"
        if not identity:
            identity = next(
                (
                    descriptor
                    for descriptor in DATASETS.values()
                    if raw_source == descriptor.id or raw_source == descriptor.harbor_dataset
                ),
                None,
            )
        if identity:
            suite_id = identity.id.rsplit("@", 1)[0]
            suite_version = identity.version
        elif "@" in raw_source:
            suite_id, suite_version = raw_source.split("@", 1)
        else:
            suite_id = raw_source
            suite_version = None

        # Check job_lock task versions or known catalog if suite_version not yet resolved
        if not suite_version and job_lock:
            trial_list = (
                job_lock.trials
                if isinstance(job_lock.trials, list)
                else list(job_lock.trials.values())
            )
            for t_lock in trial_list:
                if t_lock.task and t_lock.task.version:
                    suite_version = t_lock.task.version
                    break

        if not suite_version:
            suite_version = "unversioned"

        dataset_id = identity.id if identity else (f"{suite_id}@{suite_version}" if suite_version != "unversioned" else suite_id)
        dataset_source_repo = next(iter(locked_repos), None) if len(locked_repos) == 1 else None
        dataset_source_revision = next(iter(locked_revisions), None) if len(locked_revisions) == 1 else None

        for ht in sorted_harbor_trials:
            task_ids_set.add(ht.task_name)
            t_digest = ht.task_checksum or task_digests.get(ht.task_name)
            if t_digest:
                task_fingerprints[ht.task_name] = t_digest

            agent_name = ht.agent_info.name
            agent_ver = ht.agent_info.version or "unknown"
            model_name = ht.agent_info.model_info.name if ht.agent_info.model_info else "default"
            provider_name = (
                ht.agent_info.model_info.provider
                if (ht.agent_info.model_info and ht.agent_info.model_info.provider)
                else "unknown"
            )

            variant_id = f"{agent_name}__{model_name}"
            if variant_id not in variants_dict:
                variants_dict[variant_id] = {
                    "agent": agent_name,
                    "agent_version": agent_ver,
                    "model": model_name,
                    "provider": provider_name,
                }

            rep_key = (ht.task_name, variant_id)
            repetition = rep_counters.get(rep_key, 0)
            rep_counters[rep_key] = repetition + 1

            # Discover trial subdirectory if present
            trial_sub_dir = (
                (self.job_dir / ht.trial_name)
                if (self.job_dir / ht.trial_name).is_dir()
                else None
            )

            # Evaluate status
            eval_res = evaluate_trial_status(ht, trial_dir=trial_sub_dir)

            # Record stats
            stats["completed"] += 1
            if eval_res.canonical_status == "passed":
                stats["passed"] += 1
                stats["scored"] += 1
                stats["points_earned"] += eval_res.points_awarded or 0.0
            elif eval_res.canonical_status == "failed":
                stats["failed"] += 1
                stats["scored"] += 1
            elif eval_res.canonical_status == "timed_out":
                stats["timed_out"] += 1
                stats["scored"] += 1
            elif eval_res.canonical_status == "infrastructure_error":
                stats["infrastructure_error"] += 1
            else:
                stats["unscored"] += 1

            # Metrics
            metrics: dict[str, MetricValue] = {}
            if eval_res.points_awarded is not None:
                metrics["points"] = MetricValue(
                    value=eval_res.points_awarded,
                    unit="points",
                    source="harbor_verifier",
                    quality="derived",
                )
            else:
                metrics["points"] = MetricValue(
                    value=None,
                    unit="points",
                    source="harbor_verifier",
                    quality="unavailable",
                    reason=eval_res.diagnostics,
                )

            if eval_res.primary_reward is not None:
                metrics["verifier.reward"] = MetricValue(
                    value=eval_res.primary_reward,
                    unit="score",
                    source="harbor_verifier",
                    quality="measured",
                )
            else:
                metrics["verifier.reward"] = MetricValue(
                    value=None,
                    unit="score",
                    source="harbor_verifier",
                    quality="unavailable",
                    reason="Verifier reward not collected or failed",
                )

            # Durations
            wall_ms: float | None = None
            if ht.started_at and ht.finished_at:
                wall_ms = (ht.finished_at - ht.started_at).total_seconds() * 1000.0
                if wall_ms >= 0:
                    metrics["duration.wall_ms"] = MetricValue(
                        value=round(wall_ms, 2),
                        unit="ms",
                        source="harbor",
                        quality="measured",
                    )
                    stats["wall_time_ms"].append(wall_ms)

            if "duration.wall_ms" not in metrics:
                metrics["duration.wall_ms"] = MetricValue(
                    value=None,
                    unit="ms",
                    source="harbor",
                    quality="unavailable",
                    reason="Timing timestamps unavailable",
                )

            # Tokens & Cost
            n_in, n_cache, n_out, cost = ht.compute_token_cost_totals()
            if n_in is not None:
                metrics["tokens.worker.input"] = MetricValue(
                    value=n_in,
                    unit="tokens",
                    source="harbor",
                    quality="measured",
                )
            if n_out is not None:
                metrics["tokens.worker.output"] = MetricValue(
                    value=n_out,
                    unit="tokens",
                    source="harbor",
                    quality="measured",
                )
            if cost is not None:
                metrics["cost.usd"] = MetricValue(
                    value=round(cost, 6),
                    unit="usd",
                    source="harbor",
                    quality="measured",
                )

            # Details
            details: dict[str, Any] = {
                "scoring_basis": eval_res.scoring_basis,
                "scope_compliance": "unavailable",
                "harbor_trial_name": ht.trial_name,
                "diagnostics": eval_res.diagnostics,
                "failure_cause": eval_res.failure_cause,
                "task_checksum": ht.task_checksum or task_digests.get(ht.task_name),
            }
            if ht.trial_uri:
                details["trial_uri"] = ht.trial_uri

            raw_rew = None
            if ht.verifier_result and ht.verifier_result.rewards:
                for k in ("reward", "score", "acc", "accuracy"):
                    if k in ht.verifier_result.rewards:
                        raw_rew = ht.verifier_result.rewards[k]
                        break
                if raw_rew is None and len(ht.verifier_result.rewards) == 1:
                    raw_rew = next(iter(ht.verifier_result.rewards.values()))
            if raw_rew is not None:
                details["original_verifier_reward"] = raw_rew

            trial_rec = TrialResult(
                run_id=str(job_result.id),
                trial_id=str(ht.id),
                task_id=ht.task_name,
                variant_id=variant_id,
                repetition=repetition,
                status=eval_res.canonical_status,
                metrics=metrics,
                details=details,
            )
            canonical_trials.append(trial_rec)

        # Repetitions is max reps for any task
        max_reps = max(rep_counters.values()) if rep_counters else 1

        run_info = RunInfo(
            run_id=str(job_result.id),
            created_at=format_utc_timestamp(job_result.started_at),
            suite_id=suite_id,
            suite_version=suite_version,
            task_ids=sorted(task_ids_set),
            variants=variants_dict or {"default": {}},
            repetitions=max_reps,
            scoring_basis="external_verifier_pass_v1",
            environment={
                "harbor_package_version": harbor_version,
                "source_job_dir": str(self.job_dir),
                "dataset_source_repo": dataset_source_repo,
                "dataset_source_revision": dataset_source_revision,
                "harbor_process_returncode": process_returncode,
            },
            metadata={
                "harbor_job_id": str(job_result.id),
                "harbor_package_version": harbor_version,
                "dataset_id": dataset_id,
                "dataset_version": suite_version,
                "harbor_dataset": identity.harbor_dataset if identity else None,
                "dataset_source_repo": dataset_source_repo,
                "dataset_source_revision": dataset_source_revision,
                "task_content_fingerprints": task_fingerprints,
                "n_total_trials": job_result.n_total_trials,
                "importer": "agent_benchmark.harbor.importer",
                "harbor_process_returncode": process_returncode,
            },
        )

        # Extended summary statistics
        scored = stats["scored"]
        pass_rate = (stats["passed"] / scored * 100.0) if scored > 0 else 0.0
        coverage = (scored / stats["scheduled"] * 100.0) if stats["scheduled"] > 0 else 0.0

        median_wall = (
            sorted(stats["wall_time_ms"])[len(stats["wall_time_ms"]) // 2]
            if stats["wall_time_ms"]
            else None
        )

        summary_data = {
            "job_id": str(job_result.id),
            "dataset_id": dataset_id,
            "suite_id": suite_id,
            "suite_version": suite_version,
            "harbor_dataset": identity.harbor_dataset if identity else None,
            "dataset_source_repo": dataset_source_repo,
            "dataset_source_revision": dataset_source_revision,
            "scoring_basis": "external_verifier_pass_v1",
            "scheduled": stats["scheduled"],
            "completed": stats["completed"],
            "scored": stats["scored"],
            "passed": stats["passed"],
            "failed": stats["failed"],
            "timed_out": stats["timed_out"],
            "infrastructure_error": stats["infrastructure_error"],
            "unscored": stats["unscored"],
            "points_earned": round(stats["points_earned"], 4),
            "pass_rate_pct": round(pass_rate, 2),
            "coverage_pct": round(coverage, 2),
            "median_wall_time_ms": round(median_wall, 2) if median_wall is not None else None,
            "harbor_process_returncode": process_returncode,
            "valid_model_trials": stats["scored"],
            "valid_model_passes": stats["passed"],
            "infrastructure_invalid_trials": stats["infrastructure_error"],
            "valid_scored_coverage_pct": round(coverage, 2),
            "valid_pass_rate_pct": round(pass_rate, 2),
        }

        return run_info, canonical_trials, summary_data

    def import_to(
        self,
        output_dir: Path | str,
        *,
        process_returncode: int = 0,
        study_policy: dict[str, Any] | None = None,
        study_design: dict[str, Any] | None = None,
        study_network: dict[str, Any] | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        """Import Harbor job results to target destination directory idempotently."""
        out_dir = Path(output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        job_result, job_lock, harbor_trials = self.load_job()
        run_info, canonical_trials, summary_data = self.normalize(
            job_result, job_lock, harbor_trials, process_returncode=process_returncode
        )
        if study_policy is not None:
            run_info.metadata["planned_prompt_policy"] = dict(study_policy)
            run_info.metadata["study_design"] = dict(study_design or {})
            if study_network is None:
                raise HarborImportError("study trial is missing its declared network policy provenance")
            run_info.metadata["study_network_policy"] = {
                "policy_id": study_network.get("policy_id"),
                "network_policy": study_network.get("network_policy"),
                "task_id": study_network.get("task_id"),
                "source_git_url": study_network.get("source_git_url"),
                "source_revision": study_network.get("source_revision"),
                "original_task_sha256": study_network.get("original_task_sha256"),
                "original_verifier_sha256": study_network.get("original_verifier_sha256"),
                "derived_verifier_sha256": study_network.get("derived_verifier_sha256"),
                "original_tree_sha256": study_network.get("original_tree_sha256"),
                "original_task_toml_sha256": study_network.get("original_task_toml_sha256"),
                "derived_task_toml_sha256": study_network.get("derived_task_toml_sha256"),
                "derived_tree_sha256": study_network.get("derived_tree_sha256"),
                "snapshot_path": study_network.get("snapshot_path"),
            }
            assignments = {"sv0-unmodified-v1": "SV0", "sv1-specification-verification-v1": "SV1"}
            assignment = assignments.get(study_policy.get("id"))
            if assignment and study_design and study_design.get("id"):
                run_info.metadata["prompt_intervention"] = {
                    "schema": "declared-prompt-intervention-v1",
                    "design_id": study_design["id"], "assignment": assignment,
                }
            for trial in canonical_trials:
                trial.details["planned_prompt_policy"] = dict(study_policy)
                trial.details["study_design"] = dict(study_design or {})
                trial.details["study_network_policy"] = dict(run_info.metadata["study_network_policy"])

        # Save run.json (overwrite allowed for idempotent reimport)
        save_run(out_dir, run_info, overwrite=True)

        # Write trials.jsonl atomically
        trials_file = out_dir / "trials.jsonl"
        temp_trials = out_dir / "trials.jsonl.tmp"
        with temp_trials.open("w", encoding="utf-8") as f:
            for t in canonical_trials:
                f.write(t.to_json() + "\n")
        temp_trials.replace(trials_file)

        # Generate standard benchmark_core summary and reports
        core_summary = summarize(run_info, canonical_trials)
        generate_reports(core_summary, output_dir=out_dir, write=True)

        # Write extended harbor summary
        harbor_summary_file = out_dir / "harbor_summary.json"
        harbor_summary_file.write_text(
            json.dumps(summary_data, indent=2) + "\n",
            encoding="utf-8",
        )

        return out_dir, summary_data
