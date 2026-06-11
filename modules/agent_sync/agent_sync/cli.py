"""agent-sync CLI entry point."""

import argparse
from pathlib import Path
import sys

from agent_sync import __version__
from agent_sync.commands.audit import cmd_audit_list, cmd_audit_show
from agent_sync.commands.delegate import cmd_delegate
from agent_sync.commands.doctor import cmd_doctor
from agent_sync.commands.init import cmd_init
from agent_sync.commands.workers import cmd_workers
from agent_sync.errors import AgentSyncError
from agent_sync.paths import find_repo_root


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="agent-sync",
        description="Repo-local multi-agent handoff, delegation, review, and verification.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"agent-sync {__version__}")
    parser.add_argument("-r", "--repo-root", type=Path, default=None, help="Repository root; default auto-detects from cwd.")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Print planned work without invoking workers or writing unsafe changes.")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p_init = sub.add_parser("init", help="Bootstrap DB, worker config, docs, and instruction sections.")
    p_init.add_argument("-f", "--force", action="store_true", help="Replace existing .agent_sync/workers.json.")

    p_doctor = sub.add_parser("doctor", help="Verify DB, worker config, and installed worker commands.")
    p_doctor.add_argument("-v", "--verbose", action="store_true", help="Show detailed worker metadata.")

    p_workers = sub.add_parser("workers", help="List configured workers.")
    p_workers.add_argument("-a", "--all", action="store_true", help="Show disabled workers too.")
    p_workers.add_argument("-j", "--json", action="store_true", help="Output JSON.")

    _add_delegate_parser(sub.add_parser("delegate", help="Delegate a bounded task to another LLM worker."), default_type="custom")
    _add_delegate_parser(sub.add_parser("review", help="Ask another LLM worker to review or critique work."), default_type="review")
    _add_delegate_parser(sub.add_parser("verify", help="Ask another LLM worker to independently verify work."), default_type="verify")

    p_prompt = sub.add_parser("prompt", help="Render a delegation prompt without invoking a worker.")
    _add_delegate_args(p_prompt, default_type="custom")

    # Existing planned commands are preserved as stubs unless implemented by later phases.
    p_start = sub.add_parser("start", help="Start or attach a task to an agent (sequential phase stub).")
    p_start.add_argument("-t", "--task", required=True, help="Task ID.")
    p_start.add_argument("-a", "--agent", required=True, help="Agent name.")
    p_start.add_argument("-s", "--slug", default="work", help="Branch slug.")

    p_handoff = sub.add_parser("handoff", help="Freeze run and prepare next agent (sequential phase stub).")
    p_handoff.add_argument("-t", "--task", required=True, help="Task ID.")
    p_handoff.add_argument("-a", "--agent", required=True, help="Target agent.")

    p_resume = sub.add_parser("resume", help="Reconstruct state and relaunch agent (sequential phase stub).")
    p_resume.add_argument("-t", "--task", required=True, help="Task ID.")

    p_dispatch = sub.add_parser("dispatch", help="Fan out child tasks from a manifest (parallel phase stub).")
    p_dispatch.add_argument("-m", "--manifest", required=True, help="Dispatch manifest path.")

    p_integrate = sub.add_parser("integrate", help="Rebase and guarded merge to target branch (parallel phase stub).")
    p_integrate.add_argument("-t", "--task", required=True, help="Task ID.")

    p_memory = sub.add_parser("memory", help="Memory sync utilities (stub).")
    p_memory.add_argument("-s", "--subcommand", default="sync", help="Memory subcommand, currently sync.")
    p_memory.add_argument("-t", "--task", help="Task ID.")

    p_audit = sub.add_parser("audit", help="Audit delegated prompts and outputs.")
    audit_sub = p_audit.add_subparsers(dest="audit_command", metavar="AUDIT_COMMAND")
    p_audit_list = audit_sub.add_parser("list", help="List audit records.")
    p_audit_list.add_argument("-l", "--limit", type=int, default=20, help="Maximum records to show.")
    p_audit_show = audit_sub.add_parser("show", help="Show an audit record.")
    p_audit_show.add_argument("-i", "--id", required=True, help="Audit ID.")
    p_audit_show.add_argument("-p", "--show-prompt", action="store_true", help="Include the full delegated prompt.")

    return parser


def _add_delegate_parser(parser: argparse.ArgumentParser, *, default_type: str) -> None:
    _add_delegate_args(parser, default_type=default_type)
    parser.add_argument("-E", "--allow-external", action="store_true", help="Allow invoking the selected external/local worker.")


def _add_delegate_args(parser: argparse.ArgumentParser, *, default_type: str) -> None:
    parser.add_argument("-k", "--task-type", default=default_type, help="Task type: research, summarize, extract, review, verify, plan, classify, brainstorm, log-triage, custom.")
    parser.add_argument("-w", "--worker", default="auto", help="Worker name or auto.")
    parser.add_argument("-l", "--context-level", choices=("brief", "standard", "full"), default="standard", help="Context detail requested from the worker.")
    parser.add_argument("-p", "--prompt", default=None, help="Inline prompt text.")
    parser.add_argument("-f", "--file", type=Path, default=None, help="Read prompt/source context from this file.")
    parser.add_argument("-T", "--title", default=None, help="Optional task title.")
    parser.add_argument("-H", "--high-stakes", action="store_true", help="Mark task as high stakes; routing prefers stronger independent workers.")
    parser.add_argument("-W", "--write-allowed", action="store_true", help="Tell delegated worker that writes are allowed. Default is read-only.")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Also write worker output to this path.")
    parser.add_argument("-j", "--json", action="store_true", help="Print JSON audit metadata instead of normal text after invocation.")


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = find_repo_root(args.repo_root)
    try:
        if args.command == "init":
            cmd_init(repo_root, dry_run=args.dry_run, force=args.force)
            return 0
        if args.command == "doctor":
            return cmd_doctor(repo_root, verbose=args.verbose)
        if args.command == "workers":
            return cmd_workers(repo_root, show_all=args.all, output_json=args.json)
        if args.command in {"delegate", "review", "verify", "prompt"}:
            return cmd_delegate(
                repo_root=repo_root,
                task_type=args.task_type,
                worker_name=args.worker,
                context_level=args.context_level,
                prompt=args.prompt,
                file_path=args.file,
                title=args.title,
                allow_external=False if args.command == "prompt" else args.allow_external,
                high_stakes=args.high_stakes or args.command in {"review", "verify"},
                readonly=not args.write_allowed,
                dry_run=True if args.command == "prompt" else args.dry_run,
                output_path=args.output,
                output_json=args.json,
            )
        if args.command in {"start", "handoff", "resume", "dispatch", "integrate", "memory"}:
            print(
                f"[agent-sync] '{args.command}' is reserved for the sequential/parallel worktree phases. "
                "Delegation/review/verify are implemented now."
            )
            return 1
        if args.command == "audit":
            if args.audit_command == "list":
                return cmd_audit_list(repo_root, limit=args.limit)
            if args.audit_command == "show":
                return cmd_audit_show(repo_root, audit_id=args.id, show_prompt=args.show_prompt)
            parser.error("audit requires a subcommand: list or show")
        parser.print_help()
        return 0
    except (AgentSyncError, OSError, ValueError) as error:
        print(f"agent-sync: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
