"""CLI definitions and handlers for benchmark setup and resource lifecycle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from termdash import Table

from ..benchmarks.catalog import get_default_catalog
from ..external_sources import ResourceSpec, SourceManager


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
    setup_p.add_argument(
        "--resource-root",
        help="Override default external resource store directory",
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
    parser.add_argument(
        "--resource-root",
        help="Override default external resource store directory",
    )


def handle_setup(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Handle setup subcommands and default setup -A invocation."""
    subcmd = getattr(args, "setup_command", None)
    is_all = bool(getattr(args, "all", False))
    target = getattr(args, "target", None)
    fmt = getattr(args, "format", "table")
    execute = bool(getattr(args, "execute", False))
    custom_root = getattr(args, "resource_root", None)
    resource_root = Path(custom_root).resolve() if custom_root else None

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

    source_manager = SourceManager(resource_root)

    if subcmd == "plan":
        plan_rows = []
        benchmark_rows = []
        for b in selected_benchmarks:
            resources = [r.to_dict() for r in b.resources]
            benchmark_rows.append({
                "benchmark_id": b.id,
                "name": b.name,
                "version": b.version,
                "implementation_type": b.implementation_type,
                "default_dataset": b.default_dataset,
                "required_resources": resources,
                "resource_count": len(resources),
            })
            for decl in b.resources:
                spec = ResourceSpec.from_declaration(b.id, decl)
                res_plan = source_manager.plan_resource(spec)
                plan_rows.append(res_plan)

        payload = {
            "mode": "plan",
            "scope": "all" if is_all or not target else target,
            "resource_root": str(source_manager.root),
            "benchmarks": benchmark_rows,
            "resources": plan_rows,
            "note": "Read-only setup plan; no resources downloaded or installed",
        }

        if fmt == "json":
            print(json.dumps(payload, indent=2))
        else:
            print("\n=== Benchmark Setup Plan ===")
            print(f"Resource store: {source_manager.root}")
            tbl = Table(headers=["Benchmark", "Resource", "Type", "Status", "Action"], style="dash")
            for r in plan_rows:
                status_str = "Installed" if r["installed"] else "Missing"
                act = r["action"].upper()
                if r["optional"]:
                    act += " (OPTIONAL)"
                tbl.add_row(r["benchmark_id"], r["resource_name"], r["resource_type"], status_str, act)
            print(tbl.render())
            print("\nUse 'agent-benchmark setup install -A' to preview installation.")
        return 0

    elif subcmd == "install":
        # Group specs to install
        specs_to_install = []
        for b in selected_benchmarks:
            for decl in b.resources:
                if not decl.optional:
                    specs_to_install.append(ResourceSpec.from_declaration(b.id, decl))

        if not execute:
            preview_rows = []
            for spec in specs_to_install:
                plan = source_manager.plan_resource(spec)
                preview_rows.append({
                    "benchmark_id": spec.benchmark_id,
                    "resource_name": spec.name,
                    "resource_type": spec.resource_type,
                    "target_location": plan["target_location"],
                    "action": plan["action"],
                })

            payload = {
                "mode": "install_preview",
                "scope": "all" if is_all or not target else target,
                "authorized": False,
                "resource_root": str(source_manager.root),
                "actions": preview_rows,
                "note": "Dry-run installation preview. Re-run with -x/--execute to authorize installation.",
            }
            if fmt == "json":
                print(json.dumps(payload, indent=2))
            else:
                print("\n=== Setup Installation Preview (Dry Run) ===")
                print(f"Resource store: {source_manager.root}")
                tbl = Table(headers=["Benchmark", "Resource", "Type", "Action"], style="dash")
                for item in preview_rows:
                    tbl.add_row(item["benchmark_id"], item["resource_name"], item["resource_type"], item["action"])
                print(tbl.render())
                print("\nAuthorization required: add -x/--execute to authorize external resource installation.")
            return 0

        else:
            # Authorized execution
            installed_receipts = []
            for spec in specs_to_install:
                try:
                    receipt = source_manager.install_resource(spec, execute=True)
                    installed_receipts.append(receipt.to_dict())
                except Exception as err:
                    print(f"agent-bench setup install: failed to install {spec.name}: {err}", file=sys.stderr)
                    return 1

            payload = {
                "mode": "install_executed",
                "scope": "all" if is_all or not target else target,
                "resource_root": str(source_manager.root),
                "installed": installed_receipts,
            }
            if fmt == "json":
                print(json.dumps(payload, indent=2))
            else:
                print("\n=== Setup Installation Succeeded ===")
                tbl = Table(headers=["Benchmark", "Resource", "Type", "Status"], style="dash")
                for rc in installed_receipts:
                    tbl.add_row(rc["benchmark_id"], rc["resource_name"], rc["resource_type"], rc["status"])
                print(tbl.render())
            return 0

    elif subcmd == "status":
        status_rows = []
        benchmark_status = []
        for b in selected_benchmarks:
            ds = catalog.resolve_dataset(b.default_dataset) if b.default_dataset else None
            state = ds.install_state if ds else "registered"
            benchmark_status.append({
                "benchmark_id": b.id,
                "name": b.name,
                "state": state,
                "resources_declared": len(b.resources),
                "readiness_reason": ds.readiness_reason if ds else None,
            })
            for decl in b.resources:
                spec = ResourceSpec.from_declaration(b.id, decl)
                res_plan = source_manager.plan_resource(spec)
                r_state = "installed" if res_plan["installed"] else ("optional" if decl.optional else "registered")
                status_rows.append({
                    "benchmark_id": b.id,
                    "resource_name": decl.name,
                    "resource_type": decl.type,
                    "state": r_state,
                    "optional": decl.optional,
                    "target_location": res_plan["target_location"],
                })

        payload = {
            "mode": "status",
            "scope": "all" if is_all or not target else target,
            "resource_root": str(source_manager.root),
            "benchmarks": benchmark_status,
            "resources": status_rows,
        }
        if fmt == "json":
            print(json.dumps(payload, indent=2))
        else:
            print("\n=== Benchmark Setup Status ===")
            print(f"Resource store: {source_manager.root}")
            tbl = Table(headers=["Benchmark", "Resource", "Type", "State"], style="dash")
            for r in status_rows:
                tbl.add_row(r["benchmark_id"], r["resource_name"], r["resource_type"], r["state"].upper())
            print(tbl.render())
        return 0

    elif subcmd == "verify":
        verify_rows = []
        has_failure = False
        for b in selected_benchmarks:
            for decl in b.resources:
                spec = ResourceSpec.from_declaration(b.id, decl)
                res_verify = source_manager.verify_resource(spec)
                verify_rows.append(res_verify)
                if res_verify.get("status") in ("corrupted", "failed"):
                    has_failure = True

        payload = {
            "mode": "verify",
            "scope": "all" if is_all or not target else target,
            "resource_root": str(source_manager.root),
            "results": verify_rows,
        }
        if fmt == "json":
            print(json.dumps(payload, indent=2))
        else:
            print("\n=== Benchmark Setup Verification ===")
            print(f"Resource store: {source_manager.root}")
            tbl = Table(headers=["Benchmark", "Resource", "Status", "Details"], style="dash")
            for r in verify_rows:
                details = r.get("details") or f"{r.get('files_checked', 0)} file(s) checked"
                tbl.add_row(r["benchmark_id"], r["resource_name"], r["status"].upper(), details)
            print(tbl.render())

        return 1 if has_failure else 0

    elif subcmd == "upgrade":
        upgrade_rows = []
        for b in selected_benchmarks:
            for decl in b.resources:
                spec = ResourceSpec.from_declaration(b.id, decl)
                up_res = source_manager.upgrade_resource(spec, execute=execute)
                upgrade_rows.append(up_res)

        payload = {
            "mode": "upgrade" if execute else "upgrade_preview",
            "scope": "all" if is_all or not target else target,
            "resource_root": str(source_manager.root),
            "results": upgrade_rows,
        }
        if fmt == "json":
            print(json.dumps(payload, indent=2))
        else:
            header = "=== Benchmark Upgrade Succeeded ===" if execute else "=== Benchmark Upgrade Preview ==="
            print(f"\n{header}")
            tbl = Table(headers=["Benchmark", "Resource", "Status", "Revision"], style="dash")
            for r in upgrade_rows:
                rev = r.get("new_revision") or r.get("target_revision") or "-"
                tbl.add_row(r["benchmark_id"], r["resource_name"], r["status"], rev)
            print(tbl.render())
        return 0

    return 0
