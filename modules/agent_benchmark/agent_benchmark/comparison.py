"""Multi-model comparison, paired task discordance, and confidence interval reporting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from termdash import Table


def compute_wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Compute 95% Wilson score confidence interval for a proportion."""
    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    denominator = 1.0 + (z**2) / total
    centre_adjusted_probability = p + (z**2) / (2.0 * total)
    adjusted_std_dev = (
        (p * (1.0 - p) + (z**2) / (4.0 * total)) / total
    ) ** 0.5
    lower_bound = (centre_adjusted_probability - z * adjusted_std_dev) / denominator
    upper_bound = (centre_adjusted_probability + z * adjusted_std_dev) / denominator
    return round(max(0.0, lower_bound), 4), round(min(1.0, upper_bound), 4)


def compare_suite_runs(run_dir_a: Path, run_dir_b: Path) -> dict[str, Any]:
    """
    Compare two completed or interrupted suite runs on matching tasks.
    Enforces comparability rules and produces paired task outcomes and coverage statistics.
    """
    cp_path_a = run_dir_a / "checkpoint.json"
    cp_path_b = run_dir_b / "checkpoint.json"

    if not cp_path_a.is_file():
        raise FileNotFoundError(f"Checkpoint not found in {run_dir_a}")
    if not cp_path_b.is_file():
        raise FileNotFoundError(f"Checkpoint not found in {run_dir_b}")

    cp_a = json.loads(cp_path_a.read_text(encoding="utf-8"))
    cp_b = json.loads(cp_path_b.read_text(encoding="utf-8"))

    rep_path_a = run_dir_a / "report.json"
    rep_path_b = run_dir_b / "report.json"
    rep_a = json.loads(rep_path_a.read_text(encoding="utf-8")) if rep_path_a.is_file() else {}
    rep_b = json.loads(rep_path_b.read_text(encoding="utf-8")) if rep_path_b.is_file() else {}

    model_a = cp_a.get("model") or "model_a"
    model_b = cp_b.get("model") or "model_b"
    cohort_a = cp_a.get("cohort")
    cohort_b = cp_b.get("cohort")
    rev_a = cp_a.get("source_revision")
    rev_b = cp_b.get("source_revision")

    # Comparability verification
    comparability_blockers: list[str] = []
    if cohort_a != cohort_b and (cohort_a is not None and cohort_b is not None):
        comparability_blockers.append(f"Cohorts differ: {cohort_a!r} vs {cohort_b!r}")
    if rev_a != rev_b and (rev_a is not None and rev_b is not None):
        comparability_blockers.append(f"Source revisions differ: {rev_a[:8]} vs {rev_b[:8]}")

    tasks_a = {item["task_id"]: item for item in cp_a.get("tasks", [])}
    tasks_b = {item["task_id"]: item for item in cp_b.get("tasks", [])}

    all_task_ids = sorted(set(tasks_a.keys()) | set(tasks_b.keys()))
    common_task_ids = sorted(set(tasks_a.keys()) & set(tasks_b.keys()))

    if not common_task_ids:
        comparability_blockers.append("Runs share no common task IDs")

    is_comparable = len(comparability_blockers) == 0

    # Task categorization
    both_passed: list[str] = []
    both_failed: list[str] = []
    a_only: list[str] = []
    b_only: list[str] = []
    unpaired: list[str] = []

    for tid in common_task_ids:
        ta = tasks_a[tid]
        tb = tasks_b[tid]
        st_a = ta.get("status")
        st_b = tb.get("status")

        if st_a in ("passed", "failed") and st_b in ("passed", "failed"):
            if st_a == "passed" and st_b == "passed":
                both_passed.append(tid)
            elif st_a == "failed" and st_b == "failed":
                both_failed.append(tid)
            elif st_a == "passed" and st_b == "failed":
                a_only.append(tid)
            elif st_a == "failed" and st_b == "passed":
                b_only.append(tid)
        else:
            unpaired.append(tid)

    # Missing from one run
    for tid in all_task_ids:
        if tid not in tasks_a or tid not in tasks_b:
            unpaired.append(tid)

    common_valid_count = len(both_passed) + len(both_failed) + len(a_only) + len(b_only)
    discordance_count = len(a_only) + len(b_only)

    # Scored counts and rates
    scored_a = sum(t.get("status") in ("passed", "failed", "timed_out") for t in tasks_a.values())
    passed_a = sum(t.get("status") == "passed" for t in tasks_a.values())
    rate_a = round(100.0 * passed_a / scored_a, 2) if scored_a > 0 else 0.0
    ci_a_lo, ci_a_hi = compute_wilson_interval(passed_a, scored_a)

    scored_b = sum(t.get("status") in ("passed", "failed", "timed_out") for t in tasks_b.values())
    passed_b = sum(t.get("status") == "passed" for t in tasks_b.values())
    rate_b = round(100.0 * passed_b / scored_b, 2) if scored_b > 0 else 0.0
    ci_b_lo, ci_b_hi = compute_wilson_interval(passed_b, scored_b)

    # Paired delta on common valid tasks
    if common_valid_count > 0:
        paired_a_pass = len(both_passed) + len(a_only)
        paired_b_pass = len(both_passed) + len(b_only)
        paired_delta = round((paired_b_pass - paired_a_pass) / common_valid_count * 100.0, 2)
    else:
        paired_delta = 0.0

    return {
        "is_comparable": is_comparable,
        "blockers": comparability_blockers,
        "cohort": cohort_a or cohort_b or "custom",
        "model_a": {
            "id": model_a,
            "run_dir": str(run_dir_a),
            "planned": len(tasks_a),
            "scored": scored_a,
            "passed": passed_a,
            "pass_rate_pct": rate_a,
            "confidence_interval_95": [round(ci_a_lo * 100.0, 2), round(ci_a_hi * 100.0, 2)],
            "coverage_pct": round(100.0 * scored_a / len(tasks_a), 2) if tasks_a else 0.0,
            "wall_time_ms": rep_a.get("total_wall_time_ms", 0.0),
        },
        "model_b": {
            "id": model_b,
            "run_dir": str(run_dir_b),
            "planned": len(tasks_b),
            "scored": scored_b,
            "passed": passed_b,
            "pass_rate_pct": rate_b,
            "confidence_interval_95": [round(ci_b_lo * 100.0, 2), round(ci_b_hi * 100.0, 2)],
            "coverage_pct": round(100.0 * scored_b / len(tasks_b), 2) if tasks_b else 0.0,
            "wall_time_ms": rep_b.get("total_wall_time_ms", 0.0),
        },
        "paired_analysis": {
            "common_valid_tasks": common_valid_count,
            "discordance_count": discordance_count,
            "both_passed_count": len(both_passed),
            "both_failed_count": len(both_failed),
            "model_a_only_count": len(a_only),
            "model_b_only_count": len(b_only),
            "unpaired_tasks_count": len(unpaired),
            "paired_delta_pct": paired_delta,
            "model_a_only_tasks": a_only,
            "model_b_only_tasks": b_only,
        },
    }


def format_comparison_table(data: dict[str, Any]) -> str:
    """Render comparison report as a formatted terminal table."""
    ma = data["model_a"]
    mb = data["model_b"]
    pa = data["paired_analysis"]

    tbl = Table(headers=["Metric", ma["id"], mb["id"], "Delta (B - A)"], style="dash")
    tbl.add_row("Scored / Planned", f"{ma['scored']} / {ma['planned']}", f"{mb['scored']} / {mb['planned']}", "-")
    tbl.add_row("Coverage", f"{ma['coverage_pct']}%", f"{mb['coverage_pct']}%", f"{round(mb['coverage_pct'] - ma['coverage_pct'], 2):+}%")
    tbl.add_row("Pass Rate (Overall)", f"{ma['pass_rate_pct']}%", f"{mb['pass_rate_pct']}%", f"{round(mb['pass_rate_pct'] - ma['pass_rate_pct'], 2):+}%")
    tbl.add_row(
        "95% CI",
        f"[{ma['confidence_interval_95'][0]}%, {ma['confidence_interval_95'][1]}%]",
        f"[{mb['confidence_interval_95'][0]}%, {mb['confidence_interval_95'][1]}%]",
        "-",
    )
    tbl.add_row("Paired Valid Tasks", f"{pa['common_valid_tasks']}", f"{pa['common_valid_tasks']}", f"{pa['paired_delta_pct']:+}% (paired)")

    output = [
        f"\n=== Benchmark Model Comparison ({data['cohort']}) ===",
        tbl.render(),
        "\nPaired Discordance Matrix:",
        f"  Both Passed:        {pa['both_passed_count']}",
        f"  Both Failed:        {pa['both_failed_count']}",
        f"  {ma['id']} only:   {pa['model_a_only_count']}",
        f"  {mb['id']} only:   {pa['model_b_only_count']}",
        f"  Unpaired / Invalid: {pa['unpaired_tasks_count']}",
    ]
    if not data["is_comparable"]:
        output.append("\nWARNING: Runs are NOT strictly comparable:")
        for b in data["blockers"]:
            output.append(f"  - {b}")
    return "\n".join(output)


def format_comparison_markdown(data: dict[str, Any]) -> str:
    """Render comparison report in GitHub-flavored Markdown."""
    ma = data["model_a"]
    mb = data["model_b"]
    pa = data["paired_analysis"]

    lines = [
        f"# Benchmark Model Comparison: `{data['cohort']}`",
        "",
        f"| Metric | `{ma['id']}` | `{mb['id']}` | Delta (`B - A`) |",
        "|---|---|---|---|",
        f"| **Scored / Planned** | {ma['scored']} / {ma['planned']} | {mb['scored']} / {mb['planned']} | - |",
        f"| **Coverage** | {ma['coverage_pct']}% | {mb['coverage_pct']}% | {round(mb['coverage_pct'] - ma['coverage_pct'], 2):+}% |",
        f"| **Pass Rate** | {ma['pass_rate_pct']}% | {mb['pass_rate_pct']}% | {round(mb['pass_rate_pct'] - ma['pass_rate_pct'], 2):+}% |",
        f"| **95% Wilson CI** | [{ma['confidence_interval_95'][0]}%, {ma['confidence_interval_95'][1]}%] | [{mb['confidence_interval_95'][0]}%, {mb['confidence_interval_95'][1]}%] | - |",
        f"| **Paired Valid Tasks** | {pa['common_valid_tasks']} | {pa['common_valid_tasks']} | **{pa['paired_delta_pct']:+}%** |",
        "",
        "### Paired Discordance Matrix",
        f"- **Both Passed:** {pa['both_passed_count']}",
        f"- **Both Failed:** {pa['both_failed_count']}",
        f"- **`{ma['id']}` only:** {pa['model_a_only_count']}",
        f"- **`{mb['id']}` only:** {pa['model_b_only_count']}",
        f"- **Unpaired / Invalid:** {pa['unpaired_tasks_count']}",
    ]
    if not data["is_comparable"]:
        lines.append("")
        lines.append("> [!WARNING]")
        lines.append("> **Runs are not strictly comparable:**")
        for b in data["blockers"]:
            lines.append(f"> - {b}")

    return "\n".join(lines)
