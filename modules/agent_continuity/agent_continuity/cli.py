"""Command-line interface (`agents`) for the GUI-agent session continuity module."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from . import __version__
from .errors import ContinuityError, ErrorCode
from .service import ContinuityService, MutationPreview
from .shim import run_hook_shim


def _common_parent() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "-H",
        "--home",
        dest="home",
        default=argparse.SUPPRESS,
        help="Override state directory (defaults to AGENT_CONTINUITY_HOME or ~/.agent_continuity).",
    )
    parent.add_argument(
        "-j",
        "--json",
        dest="json_output",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit machine-readable JSON output.",
    )
    return parent


def build_parser() -> argparse.ArgumentParser:
    """Build the `agents` CLI argument parser."""
    common = _common_parent()
    parser = argparse.ArgumentParser(
        prog="agents",
        parents=[common],
        description="Local-first GUI-agent session continuity registry for ChatGPT workflows, Codex, and AGY.",
        epilog=(
            "Safety:\n"
            "  Mutating commands default to dry-run. Pass -a / --apply to persist changes.\n\n"
            "Examples:\n"
            "  agents wf add -w procwatch -t \"ProcWatch Development\" -u \"https://chatgpt.com/c/<id>\" -a\n"
            "  agents link -w procwatch -p codex -s <session-id> -e windows -a\n"
            "  agents find -w procwatch\n"
            "  agents doctor -v\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # ------------------------------------------------------------------
    # `agents wf ...`
    # ------------------------------------------------------------------
    wf_p = sub.add_parser("wf", parents=[common], help="Manage registered ChatGPT GUI workflows.")
    wf_sub = wf_p.add_subparsers(dest="wf_command", metavar="<wf-command>")

    wf_add = wf_sub.add_parser("add", parents=[common], help="Register a new GUI workflow.")
    wf_add.add_argument("-w", "--workflow", required=True, help="Human-readable workflow slug (e.g. procwatch).")
    wf_add.add_argument("-t", "--title", help="Display title for the workflow.")
    wf_add.add_argument("-u", "--url", action="append", default=[], help="ChatGPT GUI conversation URL (repeatable).")
    wf_add.add_argument("-r", "--repo", action="append", default=[], help="Associated repository path (repeatable).")
    wf_add.add_argument("-a", "--apply", action="store_true", help="Persist workflow registration (default: dry-run).")

    wf_list = wf_sub.add_parser("list", parents=[common], help="List registered workflows.")
    wf_list.add_argument(
        "-S",
        "--status",
        choices=["active", "archived", "all"],
        default="active",
        help="Filter workflows by status (default: active).",
    )

    wf_show = wf_sub.add_parser("show", parents=[common], help="Show workflow details and associated sessions.")
    wf_show.add_argument("-w", "--workflow", required=True, help="Workflow ID or slug.")

    wf_archive = wf_sub.add_parser("archive", parents=[common], help="Archive a workflow.")
    wf_archive.add_argument("-w", "--workflow", required=True, help="Workflow ID or slug.")
    wf_archive.add_argument("-a", "--apply", action="store_true", help="Persist archival (default: dry-run).")

    wf_gui_add = wf_sub.add_parser("gui-add", parents=[common], help="Associate another GUI conversation URL.")
    wf_gui_add.add_argument("-w", "--workflow", required=True, help="Workflow ID or slug.")
    wf_gui_add.add_argument("-u", "--url", required=True, help="ChatGPT GUI conversation URL.")
    wf_gui_add.add_argument("-t", "--title", help="Optional conversation title.")
    wf_gui_add.add_argument(
        "-R",
        "--relationship",
        default="continuation",
        help="Relationship type (e.g. primary, continuation, branch).",
    )
    wf_gui_add.add_argument("-a", "--apply", action="store_true", help="Persist link (default: dry-run).")

    # ------------------------------------------------------------------
    # `agents find`
    # ------------------------------------------------------------------
    find_p = sub.add_parser("find", parents=[common], help="Find native sessions associated with a workflow.")
    find_p.add_argument("-w", "--workflow", required=True, help="Workflow ID or slug.")
    find_p.add_argument("-p", "--provider", choices=["codex", "agy"], help="Filter by provider.")
    find_p.add_argument("-e", "--environment", help="Filter by environment ID, 'windows', or 'wsl'.")
    find_p.add_argument(
        "-C",
        "--include-candidates",
        action="store_true",
        help="Include unconfirmed candidate associations in results.",
    )

    # ------------------------------------------------------------------
    # `agents link`
    # ------------------------------------------------------------------
    link_p = sub.add_parser("link", parents=[common], help="Manually associate a native session with a workflow.")
    link_p.add_argument("-w", "--workflow", required=True, help="Workflow ID or slug.")
    link_p.add_argument("-p", "--provider", required=True, choices=["codex", "agy"], help="Coding-agent provider.")
    link_p.add_argument("-s", "--session-id", required=True, help="Native provider session ID.")
    link_p.add_argument(
        "-e",
        "--environment",
        help="Target environment ID or alias ('windows', 'wsl', 'wsl:<distro>', or 'local').",
    )
    link_p.add_argument("-d", "--cwd", help="Session working directory.")
    link_p.add_argument("-r", "--repo", help="Associated repository path.")
    link_p.add_argument("-t", "--title", help="Optional session title.")
    link_p.add_argument(
        "-L",
        "--level",
        choices=["confirmed", "candidate"],
        default="confirmed",
        help="Association evidence level (default: confirmed).",
    )
    link_p.add_argument("-n", "--note", help="Provenance note.")
    link_p.add_argument(
        "-X",
        "--supersede",
        action="store_true",
        help="Supersede conflicting active associations for this session.",
    )
    link_p.add_argument("-a", "--apply", action="store_true", help="Persist association (default: dry-run).")

    # ------------------------------------------------------------------
    # `agents unlink`
    # ------------------------------------------------------------------
    unlink_p = sub.add_parser("unlink", parents=[common], help="Unlink an association between a workflow and session.")
    unlink_p.add_argument("-w", "--workflow", required=True, help="Workflow ID or slug.")
    unlink_p.add_argument("-p", "--provider", required=True, choices=["codex", "agy"], help="Coding-agent provider.")
    unlink_p.add_argument("-s", "--session-id", required=True, help="Native provider session ID.")
    unlink_p.add_argument("-e", "--environment", help="Environment ID or alias.")
    unlink_p.add_argument("-n", "--note", help="Reason for unlinking.")
    unlink_p.add_argument("-a", "--apply", action="store_true", help="Persist unlink (default: dry-run).")

    # ------------------------------------------------------------------
    # `agents reject`
    # ------------------------------------------------------------------
    reject_p = sub.add_parser("reject", parents=[common], help="Reject a candidate or conflicting association.")
    reject_p.add_argument("-w", "--workflow", required=True, help="Workflow ID or slug.")
    reject_p.add_argument("-p", "--provider", required=True, choices=["codex", "agy"], help="Coding-agent provider.")
    reject_p.add_argument("-s", "--session-id", required=True, help="Native provider session ID.")
    reject_p.add_argument("-e", "--environment", help="Environment ID or alias.")
    reject_p.add_argument("-n", "--note", help="Reason for rejection.")
    reject_p.add_argument("-a", "--apply", action="store_true", help="Persist rejection (default: dry-run).")

    # ------------------------------------------------------------------
    # `agents status`
    # ------------------------------------------------------------------
    status_p = sub.add_parser("status", parents=[common], help="Update lifecycle status for a tracked session.")
    status_p.add_argument("-p", "--provider", required=True, choices=["codex", "agy"], help="Coding-agent provider.")
    status_p.add_argument("-s", "--session-id", required=True, help="Native provider session ID.")
    status_p.add_argument(
        "-S",
        "--status",
        required=True,
        choices=["active", "paused", "completed", "abandoned"],
        help="Session lifecycle status.",
    )
    status_p.add_argument("-e", "--environment", help="Environment ID or alias.")
    status_p.add_argument("-a", "--apply", action="store_true", help="Persist status update (default: dry-run).")

    # ------------------------------------------------------------------
    # `agents inbox`
    # ------------------------------------------------------------------
    inbox_p = sub.add_parser("inbox", parents=[common], help="Review unlinked, candidate, and conflicting sessions.")
    inbox_p.add_argument("-w", "--workflow", help="Filter candidates/conflicts by workflow ID or slug.")
    inbox_p.add_argument("-p", "--provider", choices=["codex", "agy"], help="Filter by provider.")
    inbox_p.add_argument("-e", "--environment", help="Filter by environment ID or alias.")

    # ------------------------------------------------------------------
    # `agents rebuild`
    # ------------------------------------------------------------------
    rebuild_p = sub.add_parser("rebuild", parents=[common], help="Rebuild SQLite index from durable event spools.")
    rebuild_p.add_argument("-a", "--apply", action="store_true", help="Execute atomic index rebuild (default: dry-run).")

    # ------------------------------------------------------------------
    # `agents doctor`
    # ------------------------------------------------------------------
    doctor_p = sub.add_parser("doctor", parents=[common], help="Diagnose storage, spools, SQLite index, and providers.")
    doctor_p.add_argument("-v", "--verbose", action="store_true", help="Show detailed capability and path diagnostics.")

    # ------------------------------------------------------------------
    # `agents hook-shim`
    # ------------------------------------------------------------------
    shim_p = sub.add_parser(
        "hook-shim",
        parents=[common],
        help="Fail-open hook stdin entrypoint for Codex and AGY lifecycle hooks.",
    )
    shim_p.add_argument("-p", "--provider", required=True, choices=["codex", "agy"], help="Provider emitting the hook.")
    shim_p.add_argument("-E", "--event", help="Optional native event name hint if omitted by provider payload.")

    return parser


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _render_mutation_text(preview: MutationPreview) -> None:
    print(preview.summary)
    if preview.action == "wf.add":
        details = preview.details
        print(f"Workflow ID: {details['workflow_id']}")
        print(f"Slug:        {details['slug']}")
        print(f"Title:       {details['title']}")
        if details.get("repo_paths"):
            print(f"Repos:       {', '.join(details['repo_paths'])}")
        print(f"Instruction: {details['handoff_instruction']}")
    elif not preview.applied:
        print("Pass -a / --apply to persist this change.")


def _render_workflows_text(workflows: list[Any]) -> None:
    if not workflows:
        print("No workflows registered.")
        return
    print(f"{'ID':<12} {'SLUG':<24} {'STATUS':<10} {'TITLE'}")
    print("-" * 72)
    for wf in workflows:
        print(f"{wf.workflow_id:<12} {wf.slug:<24} {wf.status:<10} {wf.title}")


def _render_find_text(result: dict[str, Any]) -> None:
    wf = result["workflow"]
    print(f"Workflow:    {wf['title']}")
    print(f"Workflow ID: {wf['workflow_id']} (slug: {wf['slug']}, status: {wf['status']})")
    if wf.get("repo_paths"):
        print(f"Repos:       {', '.join(wf['repo_paths'])}")
    if wf.get("gui_conversations"):
        print("ChatGPT GUI:")
        for gui in wf["gui_conversations"]:
            print(f"  - {gui['canonical_url']} [{gui['relationship']}]")
    print()

    sessions = result["sessions"]
    if not sessions:
        print("No associated sessions found.")
    else:
        print("ASSOCIATED SESSIONS")
        print(f"{'PROVIDER':<8} {'ENVIRONMENT':<24} {'SESSION ID':<38} {'EVIDENCE':<10} {'STATUS':<10} {'LAST OBSERVED'}")
        print("-" * 116)
        for item in sessions:
            s = item["session"]
            a = item["association"]
            env = item["environment"]
            env_label = env.get("label") or s["environment_id"]
            last_obs = s.get("last_turn_at") or s.get("last_seen_at") or s.get("first_observed_at") or "-"
            print(
                f"{s['provider']:<8} {env_label[:23]:<24} {s['native_session_id'][:37]:<38} "
                f"{a['evidence_level']:<10} {s['lifecycle_status']:<10} {last_obs}"
            )
        print()
        cont = result["continuity"]
        print("CONTINUITY POINTERS")
        for label, key in (
            ("Latest created       ", "latest_created"),
            ("Latest seen          ", "latest_seen"),
            ("Latest turn          ", "latest_turn"),
            ("Latest completed turn", "latest_completed_turn"),
        ):
            val = cont.get(key)
            if val:
                print(f"  {label}: {val['provider']} {val['native_session_id']} ({val['environment_id']})")
            else:
                print(f"  {label}: unavailable")

        print()
        print("RESUME OPTIONS (manual preview; never executed automatically)")
        for item in sessions:
            s = item["session"]
            resume = item.get("resume")
            if resume:
                print(f"  {s['provider']} ({s['environment_id']}) {s['native_session_id']}: {resume['display_command']}")
                if resume.get("cwd"):
                    print(f"    cwd: {resume['cwd']}")

    if result.get("warnings"):
        print()
        print("WARNINGS")
        for w in result["warnings"]:
            print(f"  - {w}")


def _render_inbox_text(inbox: dict[str, Any]) -> None:
    unlinked = inbox["unlinked_sessions"]
    candidates = inbox["candidate_associations"]
    conflicts = inbox["conflict_associations"]
    if not unlinked and not candidates and not conflicts:
        print("Inbox is empty.")
        return
    if conflicts:
        print(f"CONFLICTS ({len(conflicts)})")
        for c in conflicts:
            print(
                f"  - ({c['provider']}, {c['environment_id']}, {c['native_session_id']}) "
                f"-> {c['workflow_id']} [{c['evidence_level']}] ({c['evidence_summary'] or ''})"
            )
    if candidates:
        print(f"CANDIDATES ({len(candidates)})")
        for c in candidates:
            print(
                f"  - ({c['provider']}, {c['environment_id']}, {c['native_session_id']}) "
                f"-> {c['workflow_id']} [{c['evidence_level']}] ({c['evidence_summary'] or ''})"
            )
    if unlinked:
        print(f"UNLINKED SESSIONS ({len(unlinked)})")
        for s in unlinked:
            print(
                f"  - ({s['provider']}, {s['environment_id']}, {s['native_session_id']}) "
                f"repo={s.get('repository_identity') or '-'}"
            )


def _render_doctor_text(report: dict[str, Any], *, verbose: bool) -> None:
    print(f"Status:        {report['status']}")
    print(f"Home dir:      {report['home_dir']}")
    print(f"Runtime:       {report['runtime_kind']}")
    print(f"Environment:   {report['environment']['environment_id']} ({report['environment']['label']})")
    print(f"SQLite writer: {'allowed' if report['sqlite_writer_allowed'] else 'blocked (read-only cross-OS)'}")
    db = report["database"]
    print(
        f"SQLite DB:     {db['db_path']} (exists={db['db_exists']}, "
        f"schema={db['schema_version']}, integrity={db['integrity']})"
    )
    spools = report["spools"]
    print(f"Event spools:  {spools['valid_event_count']} valid event(s), {spools['issue_count']} issue(s)")
    if verbose:
        for root in spools["roots"]:
            print(f"  spool root:  {root}")
        if db.get("counts"):
            counts_str = ", ".join(f"{k}={v}" for k, v in db["counts"].items())
            print(f"  row counts:  {counts_str}")
    print("Providers:")
    for name, p in report["providers"].items():
        inst = p["installation"]
        print(f"  - {name}: {p['status']} (version={inst['version'] or 'unknown'}, exe={inst['executable_path'] or 'missing'})")
        if verbose and p.get("message"):
            print(f"      {p['message']}")
    if report.get("warnings"):
        print("Warnings:")
        for w in report["warnings"]:
            print(f"  - {w}")


def dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    json_mode = bool(getattr(args, "json_output", False))
    home = getattr(args, "home", None)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "hook-shim":
        return run_hook_shim(
            args.provider,
            home_dir=home,
            event_name_hint=args.event,
        )

    svc = ContinuityService(home_dir=home)

    if args.command == "wf":
        if not args.wf_command:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Missing `wf` subcommand. Try `agents wf --help`.")
        if args.wf_command == "add":
            res = svc.add_workflow(
                slug=args.workflow,
                title=args.title,
                urls=args.url,
                repo_paths=args.repo,
                apply=bool(args.apply),
            )
            if json_mode:
                _print_json({"ok": True, **res.to_dict()})
            else:
                _render_mutation_text(res)
            return 0
        if args.wf_command == "list":
            wfs = svc.list_workflows(status=args.status)
            if json_mode:
                _print_json({"ok": True, "workflows": [w.to_dict() for w in wfs]})
            else:
                _render_workflows_text(wfs)
            return 0
        if args.wf_command == "show":
            res = svc.show_workflow(args.workflow)
            if json_mode:
                _print_json({"ok": True, **res})
            else:
                _render_find_text(res)
            return 0
        if args.wf_command == "archive":
            res = svc.archive_workflow(args.workflow, apply=bool(args.apply))
            if json_mode:
                _print_json({"ok": True, **res.to_dict()})
            else:
                _render_mutation_text(res)
            return 0
        if args.wf_command == "gui-add":
            res = svc.add_gui_conversation(
                args.workflow,
                url=args.url,
                title=args.title,
                relationship=args.relationship,
                apply=bool(args.apply),
            )
            if json_mode:
                _print_json({"ok": True, **res.to_dict()})
            else:
                _render_mutation_text(res)
            return 0

    elif args.command == "find":
        res = svc.find_sessions(
            workflow_identifier=args.workflow,
            provider=args.provider,
            environment_selector=args.environment,
            include_candidates=bool(args.include_candidates),
        )
        if json_mode:
            _print_json({"ok": True, **res})
        else:
            _render_find_text(res)
        return 0

    elif args.command == "link":
        res = svc.link_session(
            workflow_identifier=args.workflow,
            provider=args.provider,
            native_session_id=args.session_id,
            environment_selector=args.environment,
            cwd=args.cwd,
            repo_path=args.repo,
            title=args.title,
            evidence_level=args.level,
            note=args.note,
            supersede=bool(args.supersede),
            apply=bool(args.apply),
        )
        if json_mode:
            _print_json({"ok": True, **res.to_dict()})
        else:
            _render_mutation_text(res)
        return 0

    elif args.command == "unlink":
        res = svc.unlink_session(
            workflow_identifier=args.workflow,
            provider=args.provider,
            native_session_id=args.session_id,
            environment_selector=args.environment,
            note=args.note,
            apply=bool(args.apply),
        )
        if json_mode:
            _print_json({"ok": True, **res.to_dict()})
        else:
            _render_mutation_text(res)
        return 0

    elif args.command == "reject":
        res = svc.reject_candidate(
            workflow_identifier=args.workflow,
            provider=args.provider,
            native_session_id=args.session_id,
            environment_selector=args.environment,
            note=args.note,
            apply=bool(args.apply),
        )
        if json_mode:
            _print_json({"ok": True, **res.to_dict()})
        else:
            _render_mutation_text(res)
        return 0

    elif args.command == "status":
        res = svc.update_session_status(
            provider=args.provider,
            native_session_id=args.session_id,
            lifecycle_status=args.status,
            environment_selector=args.environment,
            apply=bool(args.apply),
        )
        if json_mode:
            _print_json({"ok": True, **res.to_dict()})
        else:
            _render_mutation_text(res)
        return 0

    elif args.command == "inbox":
        res = svc.list_inbox(
            workflow_identifier=args.workflow,
            provider=args.provider,
            environment_selector=args.environment,
        )
        if json_mode:
            _print_json({"ok": True, **res})
        else:
            _render_inbox_text(res)
        return 0

    elif args.command == "rebuild":
        res = svc.rebuild_index(apply=bool(args.apply))
        if json_mode:
            _print_json({"ok": True, **res})
        else:
            print(res["summary"])
            if not res["applied"]:
                print("Pass -a / --apply to execute rebuild.")
        return 0

    elif args.command == "doctor":
        res = svc.diagnose()
        if json_mode:
            _print_json({"ok": True, **res})
        else:
            _render_doctor_text(res, verbose=bool(args.verbose))
        return 0

    raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unhandled command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for `agents`."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    json_mode = bool(getattr(args, "json_output", False))
    try:
        return dispatch(args, parser)
    except ContinuityError as exc:
        if json_mode:
            _print_json({"ok": False, "error": exc.to_dict()})
        else:
            print(f"Error {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        if json_mode:
            _print_json(
                {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.MATERIALIZER_FAILED,
                        "message": str(exc),
                        "detail": {},
                    },
                }
            )
        else:
            print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
