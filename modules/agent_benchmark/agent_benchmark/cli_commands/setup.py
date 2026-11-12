"""CLI definitions and handlers for benchmark setup and resource lifecycle."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from termdash import Table

from ..benchmarks.catalog import get_default_catalog


def add_setup_parser(actions: Any) -> None:
    """Add 'setup' command group with scoped -A/--all support."""
    setup_p = actions.add_parser(
        "setup",
        help="Plan, install, verify, and inspect external benchmark suites and dependencies",
    )
    # Support setup -A / --all directly on the root setup command
    setup_p.add_argument(
        "-A",
        "--all",
        action="store_true",
        help="Plan setup for all registered default benchmark resources",
    )
    setup_p.add_argument(
        "-d",
        "--dataset",
        "--benchmark",
        dest="target",
        help="Target benchmark or dataset identifier",
    )
    setup_p.add_argument(
        "-f",
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )

    sub = setup_p.add_subparsers(dest="setup_command")

    # setup plan
    plan_p = sub.add_parser("plan", help="Inspect setup requirements and download plans without execution")
    _add_setup_common(plan_p)

    # setup install
    install_p = sub.add_parser("install", help="Install required resources for benchmark suites")
    _add_setup_common(install_p)
    install_p.add_argument(
        "-x",
        "--execute",
        action="store_true",
        help="Explicitly authorize resource downloads and virtual environment installation",
    )

    # setup status
    status_p = sub.add_parser("status", help="Inspect installation readiness and presence for benchmarks")
    _add_setup_common(status_p)

    # setup verify
    verify_p = sub.add_parser("verify", help="Verify hash integrity of installed sources, datasets, and environments")
    _add_setup_common(verify_p)

    # setup upgrade
    upgrade_p = sub.add_parser("upgrade", help="Preview or execute side-by-side version upgrades for benchmark sources")
    _add_setup_common(upgrade_p)
    upgrade_p.add_argument(
        "-x",
        "--execute",
        action="store_true",
        help="Authorize installation of updated revision",
    )


def _add_setup_common(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "-A",
        "--all",
        action="store_true",
        help="Apply action to all registered default benchmark resources",
    )
    group.add_argument(
        "-d",
        "--dataset",
        "--benchmark",
        dest="target",
        help="Specific benchmark or dataset identifier",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )


def handle_setup(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Handle setup subcommands and default setup -A invocation."""
    subcmd = getattr(args, "setup_command", None)
    is_all = bool(getattr(args, "all", False))
    target = getattr(args, "target", None)
    fmt = getattr(args, "format", "table")
    execute = bool(getattr(args, "execute", False))

    if target and is_all:
        print("agent-bench setup: cannot specify both --all (-A) and a specific target (-d)", file=sys.stderr)
        return 2

    if not subcmd:
        if is_all or target:
            # Default to plan when called as 'setup -A' or 'setup -d ...'
            subcmd = "plan"
        else:
            parser.parse_args(["setup", "--help"])
            return 0

    catalog = get_default_catalog()
    all_benchmarks = catalog.list_benchmarks()

    if target:
        # Match benchmark or dataset
        matching = [b for b in all_benchmarks if b.id == target or b.default_dataset == target]
        if not matching:
            try:
                ds = catalog.resolve_dataset(target)
                matching = [b for b in all_benchmarks if b.id == ds.benchmark_id]
            except KeyError:
                print(f"agent-bench setup: unknown target {target!r}", file=sys.stderr)
                return 2
        selected_benchmarks = matching
    else:
        selected_benchmarks = all_benchmarks

    if subcmd == "plan":
        plan_rows = []
        for b in selected_benchmarks:
            resources = [r.to_dict() for r in b.resources]
            plan_rows.append({
                "benchmark_id": b.id,
                "name": b.name,
                "version": b.version,
                "implementation_type": b.implementation_type,
                "default_dataset": b.default_dataset,
                "required_resources": resources,
                "resource_count": len(resources),
            })

        payload = {
            "mode": "plan",
            "scope": "all" if is_all or not target else target,
            "benchmarks": plan_rows,
            "note": "Read-only setup plan; no resources downloaded or installed",
        }

        if fmt == "json":
            print(json.dumps(payload, indent=2))
        else:
            print("\n=== Benchmark Setup Plan ===")
            tbl = Table(headers=["Benchmark", "Type", "Resources Required", "Default Dataset"], style="dash")
            for r in plan_rows:
                res_types = ", ".join(res["type"] for res in r["required_resources"]) or "None (native)"
                tbl.add_row(r["benchmark_id"], r["implementation_type"], res_types, r["default_dataset"] or "-")
            print(tbl.render())
            print("\nUse 'agent-benchmark setup install -A' to preview installation.")
        return 0

    elif subcmd == "install":
        install_rows = []
        for b in selected_benchmarks:
            for r in b.resources:
                install_rows.append({
                    "benchmark_id": b.id,
                    "resource_name": r.name,
                    "resource_type": r.type,
                    "target_location": f"<external-root>/sources/{b.id}/{r.revision or 'default'}",
                    "revision": r.revision,
                    "action": "install" if not r.optional else "skip_optional",
                })

        if not execute:
            payload = {
                "mode": "install_preview",
                "scope": "all" if is_all or not target else target,
                "authorized": False,
                "actions": install_rows,
                "note": "Dry-run installation preview. Re-run with -x/--execute to authorize installation (Phase 03).",
            }
            if fmt == "json":
                print(json.dumps(payload, indent=2))
            else:
                print("\n=== Setup Installation Preview (Dry Run) ===")
                tbl = Table(headers=["Benchmark", "Resource", "Type", "Action"], style="dash")
                for item in install_rows:
                    tbl.add_row(item["benchmark_id"], item["resource_name"], item["resource_type"], item["action"])
                print(tbl.render())
                print("\nAuthorization required: add -x/--execute to authorize external resource installation.")
            return 0
        else:
            # Phase 02 stub for authorized execution - will be implemented in Phase 03
            print(
                "agent-bench setup install: external resource installer will be available in Phase 03. "
                "Use 'agent-bench setup install -A' without -x for dry-run preview.",
                file=sys.stderr,
            )
            return 1

    elif subcmd in ("status", "verify"):
        status_rows = []
        for b in selected_benchmarks:
            ds = catalog.resolve_dataset(b.default_dataset) if b.default_dataset else None
            state = ds.install_state if ds else "registered"
            status_rows.append({
                "benchmark_id": b.id,
                "name": b.name,
                "state": state,
                "resources_declared": len(b.resources),
                "readiness_reason": ds.readiness_reason if ds else None,
            })

        payload = {
            "mode": subcmd,
            "scope": "all" if is_all or not target else target,
            "benchmarks": status_rows,
        }
        if fmt == "json":
            print(json.dumps(payload, indent=2))
        else:
            print(f"\n=== Benchmark Setup {subcmd.capitalize()} ===")
            tbl = Table(headers=["Benchmark", "Status", "Resources", "Details"], style="dash")
            for r in status_rows:
                details = r["readiness_reason"] or "Ready"
                tbl.add_row(r["benchmark_id"], r["state"], str(r["resources_declared"]), details)
            print(tbl.render())
        return 0

    elif subcmd == "upgrade":
        print("agent-bench setup upgrade: upgrade functionality available in Phase 03.", file=sys.stderr)
        return 1

    return 0
