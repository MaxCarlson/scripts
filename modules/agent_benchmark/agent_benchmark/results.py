"""Translate frozen independent evidence into benchmark_core's canonical contracts."""

from benchmark_core import MetricValue, TrialResult, validate_relative_path

from .attempt import AttemptEvidence


def unavailable(unit: str, reason: str) -> MetricValue:
    return MetricValue(None, unit, "agent_benchmark", "unavailable", reason)


def base_metrics(session_tokens: dict | None = None, tool_telemetry: dict | None = None) -> dict[str, MetricValue]:
    metrics = {f"tokens.{actor}.{direction}": unavailable("tokens", "No attributable runtime counter collected")
               for actor in ("worker", "coordinator") for direction in ("input", "output")}
    for key in ("agent.worker_after_retry_pass", "agent.workflow_final_pass"):
        metrics[key] = unavailable("boolean", "Stage not exercised")
    for key in ("tools.calls", "tools.failures"):
        metrics[key] = unavailable("count", "Tool telemetry not collected in Phase 1c")
    for key in ("agent.local_retries", "agent.coordinator_repairs"):
        metrics[key] = MetricValue(0, "count", "harness", "derived")

    if session_tokens:
        if "input" in session_tokens:
            metrics["tokens.worker.input"] = MetricValue(
                session_tokens["input"], "tokens", "opencode_session", "measured",
                "Cumulative prompt tokens transmitted across all turns",
            )
        if "output" in session_tokens:
            metrics["tokens.worker.output"] = MetricValue(
                session_tokens["output"], "tokens", "opencode_session", "measured",
                "Total completion tokens generated (content + reasoning) across all turns",
            )
        if "content" in session_tokens:
            metrics["tokens.worker.content"] = MetricValue(
                session_tokens["content"], "tokens", "opencode_session", "measured",
                "Visible completion tokens generated across all turns",
            )
        if "reasoning" in session_tokens:
            metrics["tokens.worker.reasoning"] = MetricValue(
                session_tokens["reasoning"], "tokens", "opencode_session", "measured",
                "Reasoning/thinking tokens generated across all turns",
            )
        if "peak_context" in session_tokens:
            metrics["tokens.worker.peak_context"] = MetricValue(
                session_tokens["peak_context"], "tokens", "opencode_history", "derived",
                "Maximum context window tokens in any single turn",
            )
        if "initial_prompt" in session_tokens:
            metrics["tokens.worker.initial_prompt"] = MetricValue(
                session_tokens["initial_prompt"], "tokens", "opencode_history", "derived",
                "Baseline prompt tokens for initial turn",
            )

    if tool_telemetry:
        if "total_calls" in tool_telemetry:
            metrics["tools.calls"] = MetricValue(
                tool_telemetry["total_calls"], "count", "opencode_history", "derived",
            )
        if "total_failures" in tool_telemetry:
            metrics["tools.failures"] = MetricValue(
                tool_telemetry["total_failures"], "count", "opencode_history", "derived",
            )

    return metrics


def trial_from_attempt(
    attempt: AttemptEvidence, *, run_id: str, trial_id: str, task_id: str,
    variant_id: str, repetition: int, evidence_path: str,
) -> TrialResult:
    """Score S1 once. Never inspect the live workspace or any subsequent S2/S3."""
    evidence_path = validate_relative_path(evidence_path)
    observation = attempt.termination.last_observation
    if (not attempt.termination.confirmed or attempt.execution_error or attempt.s1 is None
            or attempt.verification is None):
        status = "infrastructure_error"
    elif attempt.task_budget_expired:
        status = "timed_out"
    elif observation is None or observation.job_status != "completed":
        status = "infrastructure_error"
    elif attempt.verification.status == "infrastructure_error":
        status = "infrastructure_error"
    elif attempt.scope_violations:
        status = "failed"
    elif (attempt.verification.status == "passed"
          and (attempt.scope_audit is None or attempt.scope_audit.compliance == "uncertain")):
        status = "unscored"
    else:
        status = attempt.verification.status
    metrics = base_metrics(attempt.session_tokens, attempt.tool_telemetry)
    metrics.update({
        "duration.wall_ms": MetricValue(attempt.wall_ms, "ms", "monotonic", "measured"),
        "duration.worker_ms": MetricValue(attempt.worker_ms, "ms", "monotonic", "measured"),
        "duration.verification_ms": (MetricValue(attempt.verification.duration_ms, "ms", "monotonic", "measured")
                                     if attempt.verification else unavailable("ms", "No reliable S1 to verify")),
        "agent.worker_first_pass": (unavailable("boolean", "Evaluation prevented by infrastructure or scope uncertainty")
                                    if status in ("infrastructure_error", "unscored") else
                                    MetricValue(int(status == "passed"), "boolean", "independent_verifier_and_audit", "derived")),
        "agent.functional_pass": (
            MetricValue(int(attempt.verification.status == "passed"), "boolean", "hidden_verifier", "derived")
            if (attempt.verification and attempt.termination.confirmed
                and not attempt.execution_error
                and attempt.verification.status in ("passed", "failed"))
            else unavailable("boolean", "Evaluation prevented by infrastructure error or unconfirmed termination")
        ),
        "agent.budget_pass": (
            MetricValue(int(not attempt.task_budget_expired), "boolean", "task_budget", "derived")
            if (attempt.termination.confirmed and not attempt.execution_error
                and status != "infrastructure_error")
            else unavailable("boolean", "Evaluation prevented by infrastructure error or unconfirmed termination")
        ),
        "agent.clean_termination": MetricValue(int(attempt.termination.confirmed), "boolean", "lifecycle_harness", "derived"),
        "agent.scope_violations": (MetricValue(
            len(attempt.scope_violations), "count",
            "snapshot_and_transcript" if attempt.scope_audit else "checkpoint_diff", "derived")
                                   if attempt.s1 is not None and attempt.termination.confirmed
                                   else unavailable("count", "No reliable S1 scope audit")),
    })
    if attempt.scope_violations and attempt.termination.confirmed:
        metrics["agent.scope_compliance"] = MetricValue(0, "boolean", "independent_scope_audit", "derived")
    elif attempt.scope_audit and attempt.scope_audit.compliance == "compliant" and attempt.termination.confirmed:
        metrics["agent.scope_compliance"] = MetricValue(1, "boolean", "independent_scope_audit", "derived")
    else:
        metrics["agent.scope_compliance"] = unavailable("boolean", "Scope could not be fully verified")
    checkpoints = {"S0": {"tree_hash": attempt.s0.tree_hash}}
    if attempt.s1:
        checkpoints["S1"] = {"tree_hash": attempt.s1.tree_hash, "diff_path": f"{evidence_path}/worker.patch"}
    unverifiable_cats: dict[str, int] = {}
    if attempt.scope_audit and attempt.scope_audit.unverifiable_operations:
        for op in attempt.scope_audit.unverifiable_operations:
            unverifiable_cats[op.category] = unverifiable_cats.get(op.category, 0) + 1
    details = {
        "scoring_basis": "worker_first_attempt_full_success", "checkpoints": checkpoints,
        "evidence_path": evidence_path, "changed_paths": list(attempt.changed_paths),
        "scope_violations": list(attempt.scope_violations),
        "scope_audit": attempt.scope_audit.to_dict() if attempt.scope_audit else None,
        "scope_policy": attempt.scope_policy,
        "task_changed_paths": list(attempt.scope_audit.task_changed_paths) if attempt.scope_audit else None,
        "scratch_changed_paths": list(attempt.scope_audit.scratch_changed_paths) if attempt.scope_audit else None,
        "task_budget_expired": attempt.task_budget_expired,
        "execution_error": attempt.execution_error,
        "execution_diagnostic": attempt.execution_diagnostic,
        "verifier_status": attempt.verification.status if attempt.verification else None,
        "verifier_returncode": attempt.verification.returncode if attempt.verification else None,
        "verifier_diagnostic": (
            (attempt.verification.stderr or attempt.verification.stdout)[-2000:]
            if attempt.verification and attempt.verification.status != "passed" else None
        ),
        "turn_completion": ("completed" if (observation and observation.job_status == "completed" and not attempt.task_budget_expired)
                            else ("aborted_at_budget" if attempt.task_budget_expired else "unconfirmed")),
        "worker_job_status": observation.job_status if observation else None,
        "worker_diagnostic": observation.diagnostic[:3000] if observation and observation.diagnostic else None,
        "termination": {"confirmed": attempt.termination.confirmed,
                        "grace_seconds": attempt.termination.grace_seconds,
                        "diagnostics": list(attempt.termination.diagnostics)},
        "session_tokens": attempt.session_tokens,
        "tool_telemetry": attempt.tool_telemetry,
        "unverifiable_categories": unverifiable_cats if unverifiable_cats else None,
        "job_id": attempt.termination.handle.job_id, "session_id": attempt.termination.handle.session_id,
        "message_id": attempt.termination.handle.message_id,
        "project_id": attempt.termination.handle.project_id or None,
    }
    return TrialResult(run_id, trial_id, task_id, variant_id, repetition, status, metrics, details)
