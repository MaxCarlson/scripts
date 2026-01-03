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


@dataclass(frozen=True)
class StatusItem:
    """Represents a single porcelain status entry."""

    staged_code: str
    work_code: str
    path: str
    raw: str


@dataclass
class StatusSummary:
    """Collection of staged and unstaged entries."""

    raw: str
    staged: list[StatusItem]
    unstaged: list[StatusItem]
    untracked: list[StatusItem]

    @property
    def has_staged(self) -> bool:
        return bool(self.staged)

    @property
    def has_unstaged(self) -> bool:
        return bool(self.unstaged)


def parse_status_summary(porcelain_status: str) -> StatusSummary:
    """Parse porcelain status output into staged/unstaged groups."""
    staged: list[StatusItem] = []
    unstaged: list[StatusItem] = []
    untracked: list[StatusItem] = []
    for line in porcelain_status.splitlines():
        if not line.strip():
            continue
        if line.startswith("??"):
            path = line[3:].strip()
            item = StatusItem(staged_code="?", work_code="?", path=path, raw=line)
            untracked.append(item)
            unstaged.append(item)
            continue
        if len(line) < 4:
            continue
        stage_code = line[0]
        work_code = line[1]
        path = line[3:].strip()
        item = StatusItem(staged_code=stage_code, work_code=work_code, path=path, raw=line)
        if stage_code != " ":
            staged.append(item)
        if work_code != " ":
            unstaged.append(item)
    return StatusSummary(raw=porcelain_status, staged=staged, unstaged=unstaged, untracked=untracked)


def build_commit_message_from_items(entries: Sequence[StatusItem]) -> str:
    """Generate a commit message summarizing staged files by type."""
    if not entries:
        return "Update repository"
    groups: dict[str, list[str]] = {"Modified": [], "Added": [], "Deleted": [], "Updated": []}
    label_map = {"M": "Modified", "A": "Added", "D": "Deleted"}
    for item in entries:
        code = item.staged_code.strip()
        label = label_map.get(code, "Updated")
        groups[label].append(item.path)
    parts: list[str] = []
    for label in ("Modified", "Added", "Deleted", "Updated"):
        if groups[label]:
            parts.append(f"{label}: {', '.join(groups[label])}")
    return "; ".join(parts) if parts else "Update repository"


def build_default_commit_message(porcelain_status: str) -> str:
    """Create a generic commit message derived from staged changes."""
    summary = parse_status_summary(porcelain_status)
    return build_commit_message_from_items(summary.staged)


def get_status_summary(runner: GitRunner) -> StatusSummary:
    """Fetch and parse the porcelain status from git."""
    status_text = runner.run(["status", "--porcelain"], capture_output=True).stdout
    return parse_status_summary(status_text)


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

    summary = get_status_summary(runner)
    runner.run(["status"])
    if not summary.staged:
        raise GitPulseError("No staged changes detected; aborting commit.")

    if not ask_yes_no("Proceed with commit", assume_yes):
        LOG.info("Commit aborted by user.")
        return

    default_message = commit_message or build_commit_message_from_items(summary.staged)
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


def ask_commit_action(has_unstaged: bool, assume_yes: bool) -> str:
    """Prompt for committing staged changes, optionally enabling split flow."""
    if assume_yes:
        return "yes"
    options = "[y]es/[n]o"
    if has_unstaged:
        options += "/[s]plit"
    prompt = f"Commit staged changes before pushing? ({options}): "
    while True:
        reply = input(prompt).strip().lower()
        if reply in {"y", "yes"}:
            return "yes"
        if reply in {"n", "no"}:
            return "no"
        if has_unstaged and reply in {"s", "split"}:
            return "split"
        print("Please answer with y, n, or s.")


def collect_commit_message(entries: Sequence[StatusItem], assume_yes: bool) -> str:
    """Return a commit message, optionally allowing manual edits."""
    default_message = build_commit_message_from_items(entries)
    if assume_yes:
        return default_message
    manual = input(f"Enter commit message [{default_message}]: ").strip()
    return manual or default_message


def run_sync_flow(runner: GitRunner, assume_yes: bool) -> None:
    """Show status, pull, optionally commit staged/unstaged changes, and push."""
    runner.run(["status"])
    runner.run(["pull"])
    summary = get_status_summary(runner)
    split_requested = False

    if summary.staged:
        action = ask_commit_action(has_unstaged=summary.has_unstaged, assume_yes=assume_yes)
        if action in {"yes", "split"}:
            message = collect_commit_message(summary.staged, assume_yes)
            runner.run(["commit", "-m", message])
            summary = get_status_summary(runner)
            split_requested = action == "split"
        else:
            LOG.info("Skipping commit while syncing staged changes.")

    if summary.has_unstaged:
        stage_prompt = (
            "Stage remaining unstaged changes for split commit"
            if split_requested
            else "Run 'git add' on unstaged changes before pushing"
        )
        if ask_yes_no(stage_prompt, assume_yes):
            runner.run(["add", "--all"])
            summary = get_status_summary(runner)
            if summary.staged:
                commit_prompt = (
                    "Commit newly staged changes after split"
                    if split_requested
                    else "Commit freshly staged changes before pushing"
                )
                if ask_yes_no(commit_prompt, assume_yes):
                    message = collect_commit_message(summary.staged, assume_yes)
                    runner.run(["commit", "-m", message])
                    summary = get_status_summary(runner)
                else:
                    LOG.info("Skipped committing newly staged changes.")
        else:
            LOG.info("Leaving unstaged changes untouched.")

    runner.run(["push"])


@dataclass(frozen=True)
class ComboCommand:
    """Data representation for simple git command sequences."""

    name: str
    description: str
    steps: Sequence[Sequence[str]]
    aliases: Sequence[str]
    confirm: bool = False


SYNC_ALIASES = ("sy", "s")
REBASE_ALIASES = ("ru", "u")
CLEAN_ALIASES = ("cr", "c")
LOG_ALIASES = ("lg", "l")
DIFF_ALIASES = ("db", "d")
COMMIT_ALIASES = ("sc", "m")


COMBO_COMMANDS: dict[str, ComboCommand] = {
    "status-pull": ComboCommand(
        name="status-pull",
        description="Show status, then pull remote changes.",
        steps=[["status"], ["pull"]],
        aliases=("sp", "p"),
    ),
    "refresh": ComboCommand(
        name="refresh",
        description="Fetch all remotes with prune, then show concise status.",
        steps=[["fetch", "--all", "--prune"], ["status", "-sb"]],
        aliases=("rf", "r"),
    ),
    "stash-sync": ComboCommand(
        name="stash-sync",
        description="Stash changes, pull with rebase, and pop the stash.",
        steps=[["stash", "push", "--include-untracked"], ["pull", "--rebase"], ["stash", "pop"]],
        aliases=("ss", "z"),
    ),
    "tag-sync": ComboCommand(
        name="tag-sync",
        description="Fetch and prune remote tags.",
        steps=[["fetch", "--tags", "--prune"]],
        aliases=("ts", "t"),
    ),
    "branch-report": ComboCommand(
        name="branch-report",
        description="Fetch remote metadata and show verbose branch list.",
        steps=[["fetch", "--all", "--prune"], ["branch", "-vv"]],
        aliases=("br", "b"),
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

    sync_parser = subparsers.add_parser(
        "sync",
        aliases=list(SYNC_ALIASES),
        help="Sync repository: status, pull, optional staged commit, push.",
        description="Display status, pull the remote, optionally commit staged changes, then push.",
    )
    sync_parser.set_defaults(func=_sync_handler)

    for combo in COMBO_COMMANDS.values():
        combo_parser = subparsers.add_parser(
            combo.name,
            aliases=list(combo.aliases),
            help=combo.description,
            description=combo.description,
        )
        combo_parser.set_defaults(func=_combo_handler_factory(combo.name))

    rebase_parser = subparsers.add_parser(
        "rebase-update",
        aliases=list(REBASE_ALIASES),
        help="Fetch all remotes and rebase current branch onto origin.",
        description="Fetch remotes and rebase the current branch onto matching origin branch.",
    )
    rebase_parser.set_defaults(func=_rebase_handler)

    clean_parser = subparsers.add_parser(
        "clean-reset",
        aliases=list(CLEAN_ALIASES),
        help="Reset to HEAD and clean untracked files (destructive).",
        description="Hard reset to HEAD and remove untracked files.",
    )
    clean_parser.set_defaults(func=_clean_handler)

    log_parser = subparsers.add_parser(
        "log-graph",
        aliases=list(LOG_ALIASES),
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
        aliases=list(DIFF_ALIASES),
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
        aliases=list(COMMIT_ALIASES),
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


def _sync_handler(args: argparse.Namespace, runner: GitRunner) -> None:
    run_sync_flow(runner, args.yes)


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
