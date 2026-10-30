"""Comparative reporting and leaderboard generation for external benchmark results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark_core import load_run_info, load_trials


def collect_run_summaries(target_dir: Path | str) -> list[dict[str, Any]]:
    """Scan target directory for imported benchmark runs and build comparison records."""
    root = Path(target_dir).resolve()
    candidates: list[Path] = []

    if (root / "run.json").is_file():
        candidates.append(root)
    else:
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "run.json").is_file():
                candidates.append(child)

    summaries: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    for rdir in candidates:
        try:
            run_info = load_run_info(rdir / "run.json")
            if run_info.run_id in seen_run_ids:
                # Deduplicate identical run imported into multiple locations
                continue
            seen_run_ids.add(run_info.run_id)
            trials = list(load_trials(rdir / "trials.jsonl"))
        except Exception:
            continue

        # Look for extended harbor_summary.json if present
        hs_file = rdir / "harbor_summary.json"
        if hs_file.is_file():
            try:
                json.loads(hs_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Aggregate across variants in the run
        variant_groups: dict[str, list[Any]] = {}
        for t in trials:
            variant_groups.setdefault(t.variant_id, []).append(t)

        for var_id, vtrials in variant_groups.items():
            var_meta = run_info.variants.get(var_id, {})
            agent_name = var_meta.get("agent") or var_id.split("__")[0]
            model_name = var_meta.get("model") or (var_id.split("__")[1] if "__" in var_id else "default")

            scheduled = len(vtrials)
            scored_trials = [t for t in vtrials if t.status in ("passed", "failed", "timed_out")]
            passed_trials = [t for t in vtrials if t.status == "passed"]
            failed_trials = [t for t in vtrials if t.status == "failed"]
            timed_out_trials = [t for t in vtrials if t.status == "timed_out"]
            infra_errors = [t for t in vtrials if t.status == "infrastructure_error"]

            points_earned = sum(
                t.metrics["points"].value
                for t in passed_trials
                if "points" in t.metrics and t.metrics["points"].value is not None
            )

            scored_count = len(scored_trials)
            pass_rate = (len(passed_trials) / scored_count * 100.0) if scored_count > 0 else 0.0
            coverage = (scored_count / scheduled * 100.0) if scheduled > 0 else 0.0

            wall_times = [
                t.metrics["duration.wall_ms"].value
                for t in vtrials
                if "duration.wall_ms" in t.metrics and t.metrics["duration.wall_ms"].value is not None
            ]
            median_wall = (
                sorted(wall_times)[len(wall_times) // 2]
                if wall_times
                else None
            )

            costs = [
                t.metrics["cost.usd"].value
                for t in vtrials
                if "cost.usd" in t.metrics and t.metrics["cost.usd"].value is not None
            ]
            total_cost = sum(costs) if costs else None

            summaries.append({
                "run_dir": str(rdir),
                "run_id": run_info.run_id,
                "benchmark": f"{run_info.suite_id}@{run_info.suite_version}",
                "suite_id": run_info.suite_id,
                "suite_version": run_info.suite_version,
                "agent": agent_name,
                "model": model_name,
                "variant_id": var_id,
                "task_count": len(run_info.task_ids),
                "task_ids": run_info.task_ids,
                "scheduled": scheduled,
                "scored": scored_count,
                "passed": len(passed_trials),
                "failed": len(failed_trials),
                "timed_out": len(timed_out_trials),
                "errors": len(infra_errors),
                "points_earned": round(points_earned, 2),
                "score_display": (
                    f"{points_earned:.1f}/{scored_count} ({len(run_info.task_ids)} tasks x {run_info.repetitions} reps)"
                    if run_info.repetitions > 1
                    else f"{int(points_earned)}/{scored_count}"
                ),
                "pass_rate_pct": round(pass_rate, 2),
                "coverage_pct": round(coverage, 2),
                "median_wall_ms": round(median_wall, 2) if median_wall is not None else None,
                "total_cost_usd": round(total_cost, 4) if total_cost is not None else None,
            })

    return summaries


def render_leaderboard_table(summaries: list[dict[str, Any]]) -> str:
    """Render a GitHub-flavored Markdown leaderboard table."""
    if not summaries:
        return "No external benchmark runs found."

    # Group by benchmark suite
    by_suite: dict[str, list[dict[str, Any]]] = {}
    for s in summaries:
        by_suite.setdefault(s["benchmark"], []).append(s)

    lines: list[str] = []
    for bench_name, rows in by_suite.items():
        lines.append(f"### Benchmark: {bench_name}\n")
        lines.append("| Agent | Model | Score | Pass Rate | Coverage | Wall Time (Median) | Errors | Cost |")
        lines.append("|---|---|---|---|---|---|---|---|")

        # Sort by pass_rate_pct descending, then errors ascending
        sorted_rows = sorted(rows, key=lambda r: (-r["pass_rate_pct"], r["errors"]))
        for r in sorted_rows:
            time_str = f"{r['median_wall_ms'] / 1000.0:.1f}s" if r["median_wall_ms"] is not None else "unavailable"
            cost_str = f"${r['total_cost_usd']:.4f}" if r["total_cost_usd"] is not None else "unavailable"
            lines.append(
                f"| `{r['agent']}` | `{r['model']}` | {r['score_display']} | "
                f"{r['pass_rate_pct']:.1f}% | {r['coverage_pct']:.1f}% | "
                f"{time_str} | {r['errors']} | {cost_str} |"
            )
        lines.append("")

    return "\n".join(lines)
