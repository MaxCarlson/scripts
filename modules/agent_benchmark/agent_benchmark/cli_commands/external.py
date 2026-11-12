"""CLI definitions and handlers for legacy Harbor external benchmark commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from termdash import Table

from ..harbor import (
    DATASETS,
    SUPPORTED_HARBOR_AGENTS,
    HarborImporter,
    check_docker_readiness,
    check_harbor_readiness,
    collect_run_summaries,
    execute_harbor_run,
    plan_benchmark,
    render_leaderboard_table,
)


def add_external_parser(actions: Any) -> None:
    """Add external Harbor benchmark command group."""
    ext_p = actions.add_parser(
        "external",
        help="Compatibility interface for legacy Harbor workflows",
        description="Compatibility interface for legacy Harbor benchmark workflows.",
        epilog="Examples:\n  agent-benchmark external list\n  agent-benchmark external plan -d aider/aider-polyglot\n  agent-benchmark external list --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ext_actions = ext_p.add_subparsers(dest="external_command")

    # external list
    ext_list = ext_actions.add_parser(
        "list", help="List supported external benchmark suites and readiness"
    )
    ext_list.add_argument(
        "--format", choices=("table", "json"), default="table", help="Output format (default: table)"
    )

    # external plan
    ext_plan = ext_actions.add_parser(
        "plan", help="Resolve tasks, configuration, and projected work without execution"
    )
    ext_plan.add_argument(
        "-d", "--dataset", default="aider-polyglot", help="Dataset identifier and version"
    )
    ext_plan.add_argument(
        "-a", "--agent", default="qwen-coder", help="Agent implementation (e.g. qwen-coder, codex, antigravity-cli, opencode, oracle)"
    )
    ext_plan.add_argument(
        "-m", "--model", default=None, help="Exact model identifier (default: qwen38_23GB for qwen-coder)"
    )
    ext_plan.add_argument(
        "-u", "--base-url", default=None, help="Inference API base URL for agent (default: http://host.docker.internal:1234/v1 for qwen-coder)"
    )
    ext_plan.add_argument(
        "-t", "--task", action="append", help="Specific task ID (repeatable)"
    )
    ext_plan.add_argument(
        "-k", "--repetitions", type=int, default=1, help="Number of trials per task (default: 1)"
    )
    ext_plan.add_argument(
        "-s", "--seed", type=int, default=42, help="Deterministic task selection seed"
    )
    ext_plan.add_argument(
        "-n", "--count", type=int, default=None, help="Limit number of tasks"
    )
    ext_plan.add_argument(
        "--language", help="Filter tasks by language (e.g. python, cpp, go, java, javascript, rust)"
    )
    ext_plan.add_argument(
        "--format", choices=("table", "json"), default="table"
    )

    # external run
    ext_run = ext_actions.add_parser(
        "run", help="Execute a planned external benchmark under explicit authorization"
    )
    ext_run.add_argument(
        "-x", "--execute", action="store_true", help="Explicitly authorize execution (required)"
    )
    ext_run.add_argument(
        "-d", "--dataset", default="aider-polyglot", help="Dataset identifier and version"
    )
    ext_run.add_argument(
        "-a", "--agent", default="qwen-coder", help="Agent implementation"
    )
    ext_run.add_argument(
        "-m", "--model", default=None, help="Exact model identifier"
    )
    ext_run.add_argument(
        "-u", "--base-url", default=None, help="Inference API base URL for agent"
    )
    ext_run.add_argument(
        "-t", "--task", action="append", help="Specific task ID (repeatable)"
    )
    ext_run.add_argument(
        "-k", "--repetitions", type=int, default=1, help="Number of trials per task (default: 1)"
    )
    ext_run.add_argument(
        "-s", "--seed", type=int, default=42, help="Deterministic task selection seed"
    )
    ext_run.add_argument(
        "-n", "--count", type=int, default=None, help="Limit number of tasks"
    )
    ext_run.add_argument(
        "--language", help="Filter tasks by language"
    )
    ext_run.add_argument(
        "-j", "--jobs", type=int, default=1, help="Concurrent trials (default: 1)"
    )
    ext_run.add_argument(
        "-o", "--output-dir", type=Path, default=Path("reports/harbor"), help="Directory where benchmark results are saved"
    )
    ext_run.add_argument(
        "--jobs-dir", type=Path, default=Path(".harbor-jobs"), help="Directory for raw Harbor job artifacts"
    )
    ext_run.add_argument(
        "--state-dir", type=Path, default=Path.home() / ".local/share/agent-benchmark", help="Directory for state/receipts"
    )
    ext_run.add_argument(
        "--quiet", action="store_true", help="Suppress Harbor console output"
    )
    ext_run.add_argument(
        "-F", "--llm-friendly", action="store_true", help="Suppress live Harbor output and emit a compact summary"
    )
    ext_run.add_argument(
        "--format", choices=("table", "json"), default="table"
    )

    # external import
    ext_import = ext_actions.add_parser(
        "import", help="Import completed Harbor job directory into benchmark_core structure"
    )
    ext_import.add_argument(
        "-j", "--job-dir", type=Path, required=True, help="Path to completed Harbor job directory"
    )
    ext_import.add_argument(
        "-o", "--output-dir", type=Path, default=Path("reports/harbor"), help="Directory to save imported benchmark_core results"
    )
    ext_import.add_argument(
        "--format", choices=("table", "json"), default="table"
    )

    # external report
    ext_report = ext_actions.add_parser(
        "report", help="Rebuild leaderboard and reports from imported results"
    )
    ext_report.add_argument(
        "-o", "--output-dir", type=Path, required=True, help="Directory containing imported benchmark_core results"
    )
    ext_report.add_argument(
        "--format", choices=("table", "json", "markdown"), default="table"
    )


def handle_external(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Handle legacy external subcommands."""
    cmd = getattr(args, "external_command", None)
    if not cmd:
        parser.parse_args(["external", "--help"])
        return 0

    if cmd == "list":
        harbor_ok, harbor_ver = check_harbor_readiness()
        docker_ok, docker_msg = check_docker_readiness()

        suites_info = []
        seen_ids = set()
        for _d_id, desc in DATASETS.items():
            if desc.id in seen_ids:
                continue
            seen_ids.add(desc.id)
            suites_info.append({
                "id": desc.id,
                "name": desc.name,
                "version": desc.version,
                "harbor_dataset": desc.harbor_dataset,
                "source_repo": desc.source_repo,
                "source_revision": desc.source_revision,
                "languages": list(desc.supported_languages),
                "total_tasks": len(desc.all_tasks),
                "default_tasks": list(desc.default_tasks),
                "scoring_protocol": desc.default_scoring_protocol,
            })

        agents_info = []
        for a_id, meta in SUPPORTED_HARBOR_AGENTS.items():
            agents_info.append({
                "agent": a_id,
                "description": meta["description"],
                "requires_model": meta["requires_model"],
                "requires_credentials": meta.get("requires_credentials", False),
            })

        payload = {
            "readiness": {
                "harbor_available": harbor_ok,
                "harbor_version": harbor_ver,
                "docker_available": docker_ok,
                "docker_status": docker_msg,
            },
            "datasets": suites_info,
            "supported_agents": agents_info,
        }

        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(json.dumps(payload, indent=2))
        else:
            print("\nExternal Benchmark Readiness:")
            tbl_ready = Table(headers=["Component", "Status", "Details"], style="dash")
            tbl_ready.add_row("Harbor Runner", "Ready" if harbor_ok else "Not Available", harbor_ver)
            tbl_ready.add_row("Docker Engine", "Ready" if docker_ok else "Not Available", docker_msg)
            print(tbl_ready.render())

            print("\nSupported External Datasets:")
            tbl_ds = Table(headers=["ID", "Name", "Tasks", "Languages"], style="dash")
            for ds in suites_info:
                langs = ", ".join(ds["languages"]) if ds["languages"] else "all"
                tbl_ds.add_row(ds["id"], ds["name"], str(ds["total_tasks"]), langs)
            print(tbl_ds.render())

            print("\nSupported Harbor Agents:")
            tbl_ag = Table(headers=["Agent", "Description", "Requires Model"], style="dash")
            for ag in agents_info:
                tbl_ag.add_row(ag["agent"], ag["description"], "Yes" if ag["requires_model"] else "No")
            print(tbl_ag.render())

        return 0

    elif cmd == "plan":
        plan = plan_benchmark(
            dataset_name=args.dataset,
            agent=args.agent,
            model=args.model,
            base_url=args.base_url,
            task_ids=args.task,
            language=args.language,
            count=args.count,
            seed=args.seed,
            repetitions=args.repetitions,
        )
        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(json.dumps(plan.to_dict(), indent=2))
        else:
            print(f"\nExternal Benchmark Plan: {plan.dataset.name}")
            print(f"Dataset ID:       {plan.dataset.id}")
            print(f"Harbor Dataset:   {plan.dataset.harbor_dataset}")
            print(f"Agent:            {plan.agent}")
            print(f"Model:            {plan.model or 'None'}")
            print(f"Base URL:         {plan.base_url or 'None'}")
            print(f"Repetitions:      {plan.repetitions}")
            print(f"Total Trials:     {plan.total_trials}")
            print(f"Deterministic:    Yes (Seed: {plan.seed})")

            readiness = plan.readiness
            print("\nReadiness:")
            print(f"  Runnable:       {'Yes' if readiness.is_runnable else 'NO'}")
            if readiness.blockers:
                print("  Blockers:")
                for b in readiness.blockers:
                    print(f"    - {b}")
            if readiness.warnings:
                print("  Warnings:")
                for w in readiness.warnings:
                    print(f"    - {w}")

            print(f"\nTasks ({len(plan.tasks)}):")
            for t in plan.tasks[:10]:
                print(f"  - {t}")
            if len(plan.tasks) > 10:
                print(f"  ... and {len(plan.tasks) - 10} more")
        return 0

    elif cmd == "run":
        try:
            plan = plan_benchmark(
                dataset_name=args.dataset,
                agent=args.agent,
                model=args.model,
                base_url=args.base_url,
                task_ids=args.task,
                language=args.language,
                count=args.count,
                seed=args.seed,
                repetitions=args.repetitions,
            )

            if getattr(args, "llm_friendly", False):
                from datetime import datetime, timezone
                from ..suite_output import capture_process_output

                args.jobs_dir.mkdir(parents=True, exist_ok=True)
                log_path = args.jobs_dir / f"external-run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}.log"
                with capture_process_output(log_path):
                    saved_dir, summary = execute_harbor_run(
                        plan=plan,
                        execute=args.execute,
                        output_dir=args.output_dir,
                        jobs_dir=args.jobs_dir,
                        state_dir=args.state_dir,
                        n_concurrent=args.jobs,
                        quiet=True,
                    )
            else:
                saved_dir, summary = execute_harbor_run(
                    plan=plan,
                    execute=args.execute,
                    output_dir=args.output_dir,
                    jobs_dir=args.jobs_dir,
                    state_dir=args.state_dir,
                    n_concurrent=args.jobs,
                    quiet=args.quiet,
                )
        except Exception as err:
            print(f"agent-bench: {err}", file=sys.stderr)
            return 2

        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(json.dumps(summary, indent=2))
        else:
            print(f"Results saved to: {saved_dir}")
        return 0 if summary.get("infrastructure_error", 0) == 0 else 1

    elif cmd == "import":
        try:
            importer = HarborImporter(args.job_dir)
            job_result, _, _ = importer.load_job()
            out_dir = args.output_dir or (Path("reports/harbor") / str(job_result.id))
            saved_dir, summary = importer.import_to(out_dir)
        except Exception as err:
            print(f"agent-bench: import error: {err}", file=sys.stderr)
            return 2

        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(json.dumps(summary, indent=2))
        else:
            rate_str = f"{summary['pass_rate_pct']:.2f}%" if summary["scored"] > 0 else "N/A"
            print(f"\nHarbor Import: {summary['suite_id']} (Job {summary['job_id'][:8]})")
            tbl = Table(headers=["Metric", "Value"], style="dash")
            tbl.add_row("Scheduled trials", str(summary["scheduled"]))
            tbl.add_row("Completed trials", str(summary["completed"]))
            tbl.add_row("Valid scored trials", str(summary["scored"]))
            tbl.add_row("Passed trials", str(summary["passed"]))
            tbl.add_row("Failed trials", str(summary["failed"]))
            tbl.add_row("Timed out trials", str(summary["timed_out"]))
            tbl.add_row("Infrastructure errors", str(summary["infrastructure_error"]))
            tbl.add_row("Points earned", f"{summary['points_earned']:.2f}")
            tbl.add_row("Pass rate", rate_str)
            tbl.add_row("Coverage", f"{summary['coverage_pct']:.2f}%")
            print(tbl.render())
        return 0 if summary.get("infrastructure_error", 0) == 0 else 1

    elif cmd == "report":
        summaries = collect_run_summaries(args.output_dir)

        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(json.dumps(summaries, indent=2))
        elif fmt == "markdown":
            print(render_leaderboard_table(summaries))
        else:
            if not summaries:
                print(f"No valid benchmark_core runs found in {args.output_dir}")
                return 0
            tbl = Table(
                headers=["Agent", "Model", "Benchmark", "Score", "Pass Rate", "Coverage", "Wall Time", "Errors", "Cost"],
                style="dash",
            )
            for s in sorted(summaries, key=lambda x: (-x["pass_rate_pct"], x["errors"])):
                time_str = f"{s['median_wall_ms'] / 1000.0:.1f}s" if s["median_wall_ms"] is not None else "N/A"
                cost_str = f"${s['total_cost_usd']:.4f}" if s["total_cost_usd"] is not None else "N/A"
                tbl.add_row(
                    s["agent"],
                    s["model"],
                    s["benchmark"],
                    f"{s['points_earned']:.2f}",
                    f"{s['pass_rate_pct']:.1f}%",
                    f"{s['coverage_pct']:.1f}%",
                    time_str,
                    str(s["errors"]),
                    cost_str,
                )
            print("\nExternal Benchmark Leaderboard:")
            print(tbl.render())
        return 0

    return 0
