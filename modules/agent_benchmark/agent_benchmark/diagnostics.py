"""Human-readable explanations of independently recorded trial outcomes."""

import re

from benchmark_core import TrialResult


def _plain(value: object, limit: int = 350) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value))
    text = " ".join("".join(c if c.isprintable() else " " for c in text).split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _metric_label(result: TrialResult, key: str) -> str:
    metric = result.metrics.get(key)
    return {1: "PASS", 0: "FAIL"}.get(metric.value if metric else None, "UNKNOWN")


def describe_trial(result: TrialResult) -> list[str]:
    """Explain check dimensions and causes without changing canonical scoring."""
    details = result.details
    audit = details.get("scope_audit") or {}
    violations = details.get("scope_violations") or audit.get("all_violations") or []
    scope = {"compliant": "PASS", "violated": "FAIL", "uncertain": "UNKNOWN"}.get(
        audit.get("compliance"), _metric_label(result, "agent.scope_compliance")
    )
    if violations:
        scope = "FAIL"
    verifier = details.get("verifier_status")
    code = _metric_label(result, "agent.functional_pass")
    if ("agent.functional_pass" not in result.metrics and not details.get("execution_error")
            and (details.get("termination") or {}).get("confirmed") is True):
        code = {"passed": "PASS", "failed": "FAIL"}.get(verifier, "UNKNOWN")
    terminated = (details.get("termination") or {}).get("confirmed")
    termination = "CONFIRMED" if terminated is True else "UNCONFIRMED" if terminated is False else "UNKNOWN"
    lines = [f"Checks: code {code} | scope {scope} | budget {_metric_label(result, 'agent.budget_pass')} "
             f"| termination {termination}"]
    if violations:
        paths = ", ".join(_plain(path, 160) for path in violations[:3])
        if len(violations) > 3:
            paths += f" (+{len(violations) - 3} more)"
        lines.append(f"Scope violation: {paths}")
        if any("__pycache__" in str(path) or str(path).endswith(".pyc") for path in violations):
            lines.append("Python cache created outside scratch. Use python -B for optional checks.")
    uncertain = audit.get("unverifiable_operations") or []
    if uncertain:
        first = uncertain[0]
        lines.append(f"Scope uncertainty: {len(uncertain)} operation(s); "
                     f"{_plain(first.get('tool', 'unknown'))}: {_plain(first.get('reason', 'details in scope audit'))}")
    if str(result.status) == "timed_out" or details.get("task_budget_expired"):
        lines.append("Time limit: worker observation budget expired; a passing code check does not clear the timeout.")
    if verifier and verifier != "passed":
        reason = details.get("verifier_diagnostic") or "See verification/stdout.txt and verification/stderr.txt."
        reason = next((line for line in reversed(str(reason).splitlines()) if line.strip()), reason)
        lines.append(f"Verifier {verifier}: {_plain(reason)}")
    for key, label in (("execution_error", "Execution error"), ("worker_diagnostic", "Worker error")):
        if details.get(key):
            diagnostic = details.get("execution_diagnostic") if key == "execution_error" else None
            lines.append(f"{label}: {_plain(diagnostic or details[key])}")
    if str(result.status) == "infrastructure_error" and len(lines) == 1:
        lines.append(f"Infrastructure: worker status {_plain(details.get('worker_job_status') or 'unknown')}; "
                     "inspect lifecycle.json and benchmark.log for termination/transport details.")
    if str(result.status) == "unscored" and not audit:
        lines.append("Scope could not be established: no complete scope audit was recorded.")
    if str(result.status) == "failed" and len(lines) == 1:
        lines.append("No specific cause recorded; inspect the trial evidence and benchmark.log.")
    if details.get("evidence_path"):
        lines.append(f"Evidence: runs/{_plain(result.run_id)}/{_plain(details['evidence_path'])}")
    return lines
