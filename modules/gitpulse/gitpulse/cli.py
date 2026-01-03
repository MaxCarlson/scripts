"""Command line interface for GitPulse git utility commands."""

from __future__ import annotations

import argparse
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

LOG = logging.getLogger(__name__)


class GitPulseError(RuntimeError):
    """Raised for command execution errors within GitPulse."""


class GitRunner:
    """Runs git commands inside a target repository."""

    def __init__(self, repo_path: Path, dry_run: bool = False) -> None:
        self.repo_path = repo_path
        self.dry_run = dry_run

    def run(self, git_args: Sequence[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
        """Execute a git command, optionally capturing stdout/stderr."""
        cmd = ["git", *git_args]
        printable = " ".join(cmd)
        if self.dry_run:
            LOG.info("[dry-run] %s", printable)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        LOG.debug("Running: %s", printable)
        try:
            return subprocess.run(
                cmd,
                cwd=self.repo_path,
                check=True,
                text=True,
                capture_output=capture_output,
            )
        except subprocess.CalledProcessError as exc:
            raise GitPulseError(f"Command '{printable}' failed with exit code {exc.returncode}") from exc


def ask_yes_no(prompt: str, assume_yes: bool) -> bool:
    """Prompt the user for confirmation."""
    if assume_yes:
        LOG.debug("Auto-confirmed prompt: %s", prompt)
        return True
    reply = input(f"{prompt} [y/N]: ").strip().lower()
    return reply in {"y", "yes"}


def build_default_commit_message(porcelain_status: str) -> str:
    """Create a generic commit message derived from staged changes."""
    lines = [line for line in porcelain_status.splitlines() if line.strip()]
    if not lines:
        return "Update repository"
    file_count = len(lines)
    modifiers = {line[:2].strip() for line in lines}
    descriptor_parts = []
    if any(token.startswith("M") for token in modifiers):
        descriptor_parts.append("modify")
    if any(token.startswith("A") for token in modifiers):
        descriptor_parts.append("add")
    if any(token.startswith("D") for token in modifiers):
        descriptor_parts.append("remove")
    descriptor = "/".join(descriptor_parts) if descriptor_parts else "update"
    plural = "file" if file_count == 1 else "files"
    return f"{descriptor.title()} {file_count} {plural}"


def show_log_graph(runner: GitRunner, limit: int) -> None:
    """Render a decorated git log graph."""
    args = [
        "log",
        "--graph",
        "--decorate",
        "--oneline",
        "--all",
        f"-{limit}",
    ]
    runner.run(args)


def show_diff_from_history(runner: GitRunner, commits_back: int) -> None:
    """Show diff between HEAD and a previous commit."""
    if commits_back < 1:
        raise GitPulseError("Commit count must be at least 1")
    target = f"HEAD~{commits_back}"
    runner.run(["diff", target])


def run_combo_commands(runner: GitRunner, steps: Sequence[Sequence[str]]) -> None:
    """Execute a series of git commands sequentially."""
    for step in steps:
        runner.run(step)


def run_smart_commit(
    runner: GitRunner,
    paths: list[str] | None,
    commit_message: str | None,
    assume_yes: bool,
) -> None:
    """Stage changes, confirm, commit, and optionally sync with remote."""
    if paths:
        runner.run(["add", "--", *paths])
    else:
        runner.run(["add", "--all"])

    status_short = runner.run(["status", "--porcelain"], capture_output=True).stdout
    runner.run(["status"])
    if not status_short.strip():
        raise GitPulseError("No staged changes detected; aborting commit.")

    if not ask_yes_no("Proceed with commit", assume_yes):
        LOG.info("Commit aborted by user.")
        return

    default_message = commit_message or build_default_commit_message(status_short)
    message = default_message
    if not commit_message and not assume_yes:
        manual = input(f"Enter commit message [{default_message}]: ").strip()
        if manual:
            message = manual

    runner.run(["commit", "-m", message])

    if ask_yes_no("Pull latest changes before pushing", assume_yes):
        runner.run(["pull"])
    if ask_yes_no("Push committed changes", assume_yes):
        runner.run(["push"])


def run_rebase_update(runner: GitRunner, assume_yes: bool) -> None:
    """Fetch and rebase current branch onto its upstream."""
    runner.run(["fetch", "--all", "--prune"])
    branch = runner.run(["rev-parse", "--abbrev-ref", "HEAD"], capture_output=True).stdout.strip()
    if not branch:
        raise GitPulseError("Unable to determine current branch for rebase.")
    target = f"origin/{branch}"
    if not ask_yes_no(f"Rebase onto {target}", assume_yes):
        LOG.info("Rebase aborted by user.")
        return
    runner.run(["rebase", target])


def run_stash_sync(runner: GitRunner) -> None:
    """Stash changes, pull latest with rebase, and pop the stash."""
    runner.run(["stash", "push", "--include-untracked"])
    try:
        runner.run(["pull", "--rebase"])
    finally:
        runner.run(["stash", "pop"])


def run_clean_reset(runner: GitRunner, assume_yes: bool) -> None:
    """Hard reset and clean working tree."""
    if not ask_yes_no("Reset and clean the working tree", assume_yes):
        LOG.info("Clean reset aborted by user.")
        return
    runner.run(["reset", "--hard", "HEAD"])
    runner.run(["clean", "-fd"])


@dataclass(frozen=True)
class ComboCommand:
    """Data representation for simple git command sequences."""

    name: str
    description: str
    steps: Sequence[Sequence[str]]
    confirm: bool = False


COMBO_COMMANDS: dict[str, ComboCommand] = {
    "sync": ComboCommand(
        name="sync",
        description="Run 'git pull' followed by 'git push'.",
        steps=[["pull"], ["push"]],
    ),
    "status-pull": ComboCommand(
        name="status-pull",
        description="Show status, then pull remote changes.",
        steps=[["status"], ["pull"]],
    ),
    "refresh": ComboCommand(
        name="refresh",
        description="Fetch all remotes with prune, then show concise status.",
        steps=[["fetch", "--all", "--prune"], ["status", "-sb"]],
    ),
    "stash-sync": ComboCommand(
        name="stash-sync",
        description="Stash changes, pull with rebase, and pop the stash.",
        steps=[["stash", "push", "--include-untracked"], ["pull", "--rebase"], ["stash", "pop"]],
    ),
    "tag-sync": ComboCommand(
        name="tag-sync",
        description="Fetch and prune remote tags.",
        steps=[["fetch", "--tags", "--prune"]],
    ),
    "branch-report": ComboCommand(
        name="branch-report",
        description="Fetch remote metadata and show verbose branch list.",
        steps=[["fetch", "--all", "--prune"], ["branch", "-vv"]],
    ),
}


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="gk",
        description="GitPulse: curated git command combinations and helpers.",
    )
    parser.add_argument(
        "-R",
        "--repo-path",
        default=".",
        help="Path to the repository (default: current directory).",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Log git commands without executing them.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        "--confirm",
        dest="yes",
        action="store_true",
        help="Automatically reply yes to confirmation prompts.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    for combo in COMBO_COMMANDS.values():
        combo_parser = subparsers.add_parser(combo.name, help=combo.description, description=combo.description)
        combo_parser.set_defaults(func=_combo_handler_factory(combo.name))

    rebase_parser = subparsers.add_parser(
        "rebase-update",
        help="Fetch all remotes and rebase current branch onto origin.",
        description="Fetch remotes and rebase the current branch onto matching origin branch.",
    )
    rebase_parser.set_defaults(func=_rebase_handler)

    clean_parser = subparsers.add_parser(
        "clean-reset",
        help="Reset to HEAD and clean untracked files (destructive).",
        description="Hard reset to HEAD and remove untracked files.",
    )
    clean_parser.set_defaults(func=_clean_handler)

    log_parser = subparsers.add_parser(
        "log-graph",
        help="Show a decorated log graph for the repository.",
        description="Render `git log --graph --decorate --oneline --all` with an optional limit.",
    )
    log_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=100,
        help="Number of commits to include in the graph (default: 100).",
    )
    log_parser.set_defaults(func=_log_handler)

    diff_parser = subparsers.add_parser(
        "diff-back",
        help="Show the diff between HEAD and N commits back.",
        description="Show differences between current tree and HEAD~N.",
    )
    diff_parser.add_argument(
        "-c",
        "--commit-count",
        type=int,
        required=True,
        help="How many commits to go back for the diff (must be >= 1).",
    )
    diff_parser.set_defaults(func=_diff_handler)

    commit_parser = subparsers.add_parser(
        "smart-commit",
        help="Stage, review, commit, and optionally sync changes.",
        description="Guide through staging paths, reviewing status, committing, and optionally syncing.",
    )
    commit_parser.add_argument(
        "-p",
        "--paths",
        nargs="+",
        help="Specific file paths to stage (default: stage all tracked changes).",
    )
    commit_parser.add_argument(
        "-m",
        "--message",
        help="Commit message to use without prompting.",
    )
    commit_parser.set_defaults(func=_commit_handler)

    return parser


def _combo_handler_factory(combo_name: str) -> Callable[[argparse.Namespace, GitRunner], None]:
    """Generate handlers for combo commands."""

    def handler(args: argparse.Namespace, runner: GitRunner) -> None:
        combo = COMBO_COMMANDS[combo_name]
        if combo.name == "stash-sync":
            run_stash_sync(runner)
            return
        if combo.confirm:
            if not ask_yes_no(f"Execute {combo.name}?", args.yes):
                LOG.info("%s aborted by user.", combo.name)
                return
        run_combo_commands(runner, combo.steps)

    return handler


def _log_handler(args: argparse.Namespace, runner: GitRunner) -> None:
    show_log_graph(runner, args.limit)


def _diff_handler(args: argparse.Namespace, runner: GitRunner) -> None:
    show_diff_from_history(runner, args.commit_count)


def _commit_handler(args: argparse.Namespace, runner: GitRunner) -> None:
    run_smart_commit(runner, args.paths, args.message, args.yes)


def _rebase_handler(args: argparse.Namespace, runner: GitRunner) -> None:
    run_rebase_update(runner, args.yes)


def _clean_handler(args: argparse.Namespace, runner: GitRunner) -> None:
    run_clean_reset(runner, args.yes)


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    repo_path = Path(args.repo_path).expanduser().resolve()
    runner = GitRunner(repo_path=repo_path, dry_run=args.dry_run)
    try:
        args.func(args, runner)
    except GitPulseError as exc:
        LOG.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
