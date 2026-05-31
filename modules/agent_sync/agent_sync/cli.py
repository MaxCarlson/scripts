"""agent-sync CLI entry point."""
import argparse
import sys
from pathlib import Path


def _find_repo_root() -> Path:
    """Walk up from cwd looking for .git directory."""
    here = Path.cwd()
    for parent in [here, *here.parents]:
        if (parent / ".git").exists():
            return parent
    return here


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-sync",
        description="Deterministic multi-agent coordination for git repositories",
    )
    parser.add_argument(
        "-r", "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detect from cwd)",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Print planned changes without executing",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # init
    sub.add_parser("init", help="Bootstrap DB, provider configs, and docs")

    # doctor
    p_doctor = sub.add_parser("doctor", help="Verify hooks, DB, and provider setup")
    p_doctor.add_argument("-v", "--verbose", action="store_true")

    # start (stub — implemented in Phase 2)
    p_start = sub.add_parser("start", help="Start or attach a task to an agent")
    p_start.add_argument("-t", "--task", required=True, help="Task ID")
    p_start.add_argument("-a", "--agent", required=True, help="Agent name")
    p_start.add_argument("-s", "--slug", default="work", help="Branch slug")

    # handoff (stub)
    p_handoff = sub.add_parser("handoff", help="Freeze run and prepare next agent")
    p_handoff.add_argument("-t", "--task", required=True)
    p_handoff.add_argument("-a", "--agent", required=True, help="Target agent")

    # resume (stub)
    p_resume = sub.add_parser("resume", help="Reconstruct state and relaunch agent")
    p_resume.add_argument("-t", "--task", required=True)

    # dispatch (stub)
    p_dispatch = sub.add_parser("dispatch", help="Fan out child tasks from a manifest")
    p_dispatch.add_argument("-m", "--manifest", required=True)

    # review (stub)
    p_review = sub.add_parser("review", help="Launch reviewer agent against task branch")
    p_review.add_argument("-t", "--task", required=True)
    p_review.add_argument("-a", "--agent", required=True)

    # integrate (stub)
    p_integrate = sub.add_parser("integrate", help="Rebase + guarded merge to target branch")
    p_integrate.add_argument("-t", "--task", required=True)

    # memory (stub)
    p_memory = sub.add_parser("memory", help="Memory sync utilities")
    p_memory.add_argument("subcommand", nargs="?", help="e.g. sync")
    p_memory.add_argument("-t", "--task", help="Task ID")

    args = parser.parse_args(argv)
    repo_root = args.repo_root or _find_repo_root()

    if args.command == "init":
        from agent_sync.commands.init import cmd_init
        cmd_init(repo_root, dry_run=args.dry_run)
        return 0

    if args.command == "doctor":
        from agent_sync.commands.doctor import cmd_doctor
        return cmd_doctor(repo_root, verbose=args.verbose)

    if args.command in ("start", "handoff", "resume", "dispatch", "review",
                        "integrate", "memory"):
        phase = "2" if args.command in ("start", "handoff", "resume") else "3"
        print(
            f"[agent-sync] '{args.command}' is implemented in Phase {phase}. "
            f"See agent_sync/docs/plans/PLAN-{phase}-{'SEQUENTIAL' if phase == '2' else 'PARALLEL'}.md"
        )
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
