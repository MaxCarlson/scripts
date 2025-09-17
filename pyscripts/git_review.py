#!/usr/bin/env python3
"""
git_revview.py
View historical file contents and diffs from N commits ago (or any commit-ish),
with rename-tracking, clipboard copy, file output, and "as-of" fallback.

Key behaviors
-------------
- --show: print file content(s) as of a revision. If a file didn't exist *at* the
  exact rev, we (by default) fall back to the closest earlier version that does
  exist at or before that rev (rename-aware).
- --diff:
  * default: changes since REV (i.e., REV..HEAD), rename-aware.
  * with -c/--commit: patch for a single commit, rename-aware even when filtered.

Clipboard & Output
------------------
- --clipboard / -b: copy to clipboard (uses user's `clipboard_utils.set_clipboard`).
  * For single-file --show: copies the raw file text at that rev/as-of.
  * Otherwise: copies the printed bundle/diff text.
- --out / -o:
  * --show + one file + path that looks like a regular file: writes raw text there.
  * --show + many files or directory path: writes under <out>/<rev>/<historical_path>.
  * --diff: writes unified diff to a file (or inside a directory with a sensible name).

Rename handling is on by default; disable with --no-follow-renames.
"As-of" fallback is on by default; disable with --exact.

Examples
--------
# Show a file as it was 3 commits ago (follows renames, with as-of fallback):
python scripts/git_revview.py -s -n 3 rotating_aedlpn.py

# Show multiple files from a specific rev and write them out under ./out/HEAD~3/...
python scripts/git_revview.py -s -n 3 -o out rotating_aedlpn.py aebndl_dlpn.py

# Copy the single file's historical contents to clipboard:
python scripts/git_revview.py -s -n 3 -b rotating_aedlpn.py

# Diff since N commits ago (entire repo):
python scripts/git_revview.py -d -n 3

# Patch of a specific commit, filtered to paths (works across renames):
python scripts/git_revview.py -d -n 2 -c aebndl_dlpn.py
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Optional, Sequence, Tuple


class GitError(RuntimeError):
    """Raised for git-related failures."""


# ---------------------------
# git exec helpers
# ---------------------------


def _which_git() -> str:
    exe = shutil.which("git")
    if not exe:
        raise GitError("`git` executable not found on PATH.")
    return exe


def _run_git(
    args: Sequence[str], cwd: Optional[Path] = None
) -> subprocess.CompletedProcess:
    git = _which_git()
    return subprocess.run(
        [git, *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )


def _ensure_ok(proc: subprocess.CompletedProcess, what: str) -> None:
    if proc.returncode != 0:
        raise GitError(
            f"{what} failed (exit {proc.returncode}).\n{proc.stderr.strip()}"
        )


def _rev_to_hash(rev: str, repo_root: Optional[Path]) -> str:
    """Return the full hash for a rev."""
    proc = _run_git(["rev-parse", rev], cwd=repo_root)
    _ensure_ok(proc, "git rev-parse")
    return proc.stdout.strip()


def _rev_from_commits_ago(n: int) -> str:
    if n < 0:
        raise ValueError("commits_ago must be >= 0")
    return f"HEAD~{n}"


def _posix_repo_path(p: Path) -> str:
    return str(PurePosixPath(*p.parts))


def _tree_has_path(rev: str, posix_path: str, repo_root: Optional[Path]) -> bool:
    """Fast existence check: does <rev>:<posix_path> exist?"""
    proc = _run_git(["cat-file", "-e", f"{rev}:{posix_path}"], cwd=repo_root)
    return proc.returncode == 0


# ---------------------------
# Rename-aware path resolution (+ as-of fallback)
# ---------------------------

_HASH_RE = re.compile(r"^[0-9a-f]{40}$")


def _parse_name_status_line(line: str) -> Optional[tuple[str, str, str]]:
    """
    Parse a 'git log --name-status' line.

    Returns:
      ('Rxxx', old, new) for renames
      ('M', path, '') for modify
      ('A', path, '') for add
      ('D', path, '') for delete
      None if unparsable
    """
    parts = line.rstrip("\n").split("\t")
    if not parts:
        return None
    code = parts[0]
    if code.startswith("R") and len(parts) == 3:
        return code, parts[1], parts[2]
    if code in {"M", "A", "D"} and len(parts) == 2:
        return code, parts[1], ""
    return None


def _follow_log_blocks(
    provided_path: Path,
    repo_root: Optional[Path] = None,
) -> list[tuple[str, str]]:
    """
    Build [(commit_hash, path_at_that_commit), ...] newest -> oldest for provided path,
    following renames.

    We walk `git log --follow --find-renames --name-status --format=%H -- <path>`,
    keeping a rolling `current_path` newest->older. For each commit, we record the
    *name at that commit* (i.e., after the changes of that commit).
    """
    repo_root = repo_root or Path.cwd()
    posix = _posix_repo_path(provided_path)
    proc = _run_git(
        [
            "log",
            "--follow",
            "--find-renames",
            "--name-status",
            "--format=%H",
            "--",
            posix,
        ],
        cwd=repo_root,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return []

    current_path = posix  # name at HEAD to start
    current_commit: Optional[str] = None
    pending_changes: List[tuple[str, str, str]] = []
    out: list[tuple[str, str]] = []

    def _apply_pending_renames():
        nonlocal current_path, pending_changes
        for code, old, new in pending_changes:
            if code.startswith("R") and new == current_path:
                current_path = old
        pending_changes = []

    for raw in proc.stdout.splitlines():
        if _HASH_RE.match(raw):
            # finalize previous block (record name at that commit), then step older
            if current_commit is not None:
                out.append((current_commit, current_path))
                _apply_pending_renames()
            current_commit = raw
            continue

        parsed = _parse_name_status_line(raw)
        if parsed:
            pending_changes.append(parsed)

    # Final block
    if current_commit is not None:
        out.append((current_commit, current_path))
        _apply_pending_renames()

    return out  # newest -> oldest


def resolve_path_at_commit(
    provided_path: Path,
    target_rev: str,
    repo_root: Optional[Path] = None,
) -> str:
    """
    Resolve the file path to use at `target_rev`, following renames backward as needed.

    If <target_rev>:<provided> exists, uses it. Otherwise, tries to find the historical
    name by stepping back through renames newer->older until we reach that commit.
    """
    repo_root = repo_root or Path.cwd()
    posix = _posix_repo_path(provided_path)
    if _tree_has_path(target_rev, posix, repo_root):
        return posix

    target_hash = _rev_to_hash(target_rev, repo_root)
    blocks = _follow_log_blocks(provided_path, repo_root)
    if not blocks:
        return posix

    # Walk newest->oldest, stepping name older between commits.
    current_path = posix
    for commit_hash, name_at_commit in blocks:
        # name_at_commit is the post-commit name at that commit in the log sequence
        # Ensure current_path tracks that.
        current_path = name_at_commit
        if commit_hash == target_hash:
            return current_path

        # Step older by applying renames collected between these commits
        # (handled inside _follow_log_blocks already).

    # If target commit wasn't in the path's history, return the oldest derived name.
    return current_path


def _is_ancestor(ancestor: str, descendant: str, repo_root: Optional[Path]) -> bool:
    """True if `ancestor` is an ancestor of (or equal to) `descendant`."""
    proc = _run_git(
        ["merge-base", "--is-ancestor", ancestor, descendant], cwd=repo_root
    )
    return proc.returncode == 0


def last_existing_path_on_or_before_rev(
    provided_path: Path,
    target_rev: str,
    repo_root: Optional[Path] = None,
) -> Optional[Tuple[str, str]]:
    """
    Find the *closest earlier or equal* commit to `target_rev` in the path's
    rename-following history where the file exists in the tree at `target_rev`.
    Returns (commit_hash, path_at_that_commit) or None.

    This enables "as-of" semantics: if the file doesn't exist at the exact rev,
    we still show the latest version at or before that point.
    """
    repo_root = repo_root or Path.cwd()
    target_hash = _rev_to_hash(target_rev, repo_root)
    blocks = _follow_log_blocks(provided_path, repo_root)
    if not blocks:
        return None

    # Newest -> oldest. We want the newest commit in this history that's an
    # ancestor of target_rev, *and* whose name exists in target_rev's tree.
    for commit_hash, name_at_commit in blocks:
        if _is_ancestor(commit_hash, target_hash, repo_root):
            if _tree_has_path(target_rev, name_at_commit, repo_root):
                return (commit_hash, name_at_commit)
            # If path name differs at target_rev due to following rename steps,
            # keep scanning older history.

    return None


# ---------------------------
# Content and diff operations
# ---------------------------


def get_file_text_at_rev(
    rev: str,
    path_at_rev: str,
    repo_root: Optional[Path] = None,
) -> Optional[str]:
    """Return file text at rev if present, else None."""
    repo_root = repo_root or Path.cwd()
    proc = _run_git(["show", f"{rev}:{path_at_rev}"], cwd=repo_root)
    if proc.returncode != 0:
        return None
    return proc.stdout


def show_file_contents_at_rev(
    rev: str,
    files: Iterable[Path],
    repo_root: Optional[Path] = None,
    follow_renames: bool = True,
    as_of: bool = True,
) -> tuple[str, dict[Path, tuple[str, Optional[str]]]]:
    """
    Return:
      (pretty_bundle_text, per_file_map)
    Where per_file_map[file] = (resolved_posix_path_used, content_or_None)

    The bundle text looks like:
      ===== FILE: foo.py [src/core/foo.py] @ HEAD~3 =====
      <contents or "<< File not found at HEAD~3 >>">
    """
    repo_root = repo_root or Path.cwd()
    outputs: List[str] = []
    mapping: dict[Path, tuple[str, Optional[str]]] = {}

    for f in files:
        user_posix = _posix_repo_path(f)
        path_at_rev = (
            resolve_path_at_commit(f, rev, repo_root) if follow_renames else user_posix
        )
        text = get_file_text_at_rev(rev, path_at_rev, repo_root=repo_root)

        # As-of fallback: if missing exactly at rev, use the nearest earlier version.
        if text is None and as_of:
            found = last_existing_path_on_or_before_rev(f, rev, repo_root)
            if found is not None:
                _commit_hash, name_at_commit = found
                maybe = get_file_text_at_rev(rev, name_at_commit, repo_root)
                if maybe is not None:
                    path_at_rev, text = name_at_commit, maybe

        header = f"===== FILE: {f} [{path_at_rev}] @ {rev} ====="
        outputs.append(header)
        if text is None:
            outputs.append(f"<< File not found at {rev} >>\n")
        else:
            outputs.append(text.rstrip("\n") + "\n")

        mapping[f] = (path_at_rev, text)

    return ("\n".join(outputs).rstrip() + ("\n" if outputs else "")), mapping


def diff_since_rev(
    since_rev: str,
    files: Optional[Iterable[Path]] = None,
    repo_root: Optional[Path] = None,
) -> str:
    repo_root = repo_root or Path.cwd()
    args: List[str] = ["diff", "--find-renames", since_rev, "HEAD"]
    paths = list(files or [])
    if paths:
        args.append("--")
        args.extend(str(p) for p in paths)

    proc = _run_git(args, cwd=repo_root)
    _ensure_ok(proc, "git diff (since)")
    return proc.stdout


def diff_specific_commit(
    commit_rev: str,
    files: Optional[Iterable[Path]] = None,
    repo_root: Optional[Path] = None,
    follow_renames: bool = True,
) -> str:
    """
    Show the patch introduced by `commit_rev`, optionally filtered to file paths.
    When filtering, resolve each path to its *historical* name at commit_rev so
    filtering works even across renames. Use -M to *show* rename hunks.
    """
    repo_root = repo_root or Path.cwd()
    args: List[str] = ["show", "--patch", "-M", commit_rev]
    paths = list(files or [])
    if paths:
        args.append("--")
        if follow_renames:
            resolved = [resolve_path_at_commit(p, commit_rev, repo_root) for p in paths]
            args.extend(resolved)
        else:
            args.extend(str(p) for p in paths)

    proc = _run_git(args, cwd=repo_root)
    _ensure_ok(proc, "git show (commit)")
    return proc.stdout


# ---------------------------
# Clipboard + File output helpers
# ---------------------------


def _clipboard_set(text: str) -> None:
    """
    Try to use user's clipboard module. If unavailable, raise a friendly error.
    """
    try:
        import clipboard_utils  # provided by user
    except Exception as e:
        raise GitError(
            "Clipboard requested but `clipboard_utils` could not be imported. "
            "Install/activate your module or run without --clipboard."
        ) from e
    try:
        clipboard_utils.set_clipboard(text)
    except Exception as e:  # pragma: no cover (OS-specific)
        raise GitError(f"Failed to copy to clipboard: {e}") from e


def _write_text_to_path(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _choose_diff_outfile_path(base: Path, rev: str, since_mode: bool) -> Path:
    if base.is_dir():
        fname = f"diff-{rev}-to-HEAD.patch" if since_mode else f"commit-{rev}.patch"
        return base / fname
    return base


# ---------------------------
# CLI
# ---------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="View file contents or diffs from N commits ago (or a commit-ish).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        add_help=True,
    )

    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "-s",
        "--show",
        action="store_true",
        help="Show file contents at a past revision.",
    )
    mode.add_argument("-d", "--diff", action="store_true", help="Show diffs.")

    revgrp = p.add_mutually_exclusive_group(required=True)
    revgrp.add_argument(
        "-n",
        "--commits_ago",
        type=int,
        help="Number of commits ago (HEAD~N). Use 0 for HEAD.",
    )
    revgrp.add_argument(
        "-r", "--rev", type=str, help="Commit-ish (hash, tag, branch, etc.)."
    )

    p.add_argument(
        "-c",
        "--commit",
        action="store_true",
        help="When using --diff: show the patch for that specific commit (commit vs parent). "
        "Omit to show changes since that revision (rev..HEAD).",
    )

    # Output / side-effects
    p.add_argument(
        "-b", "--clipboard", action="store_true", help="Copy result to clipboard."
    )
    p.add_argument(
        "-o", "--out", type=str, default="", help="Write result to this path."
    )
    p.add_argument(
        "-R",
        "--repo",
        type=str,
        default=".",
        help="Path to the repository root (or any child path).",
    )

    # Rename behavior (default on)
    try:
        p.add_argument(
            "--follow-renames",
            default=True,
            action=argparse.BooleanOptionalAction,
            help="Follow renames when resolving historical paths (enabled by default).",
        )
    except Exception:
        p.add_argument(
            "--follow-renames",
            action="store_true",
            default=True,
            help=argparse.SUPPRESS,
        )
        p.add_argument(
            "--no-follow-renames",
            action="store_false",
            dest="follow_renames",
            help=argparse.SUPPRESS,
        )

    # As-of behavior (default on)
    try:
        p.add_argument(
            "--asof",
            dest="asof",
            default=True,
            action=argparse.BooleanOptionalAction,
            help="If the file doesn't exist at the exact rev, use the closest earlier version (enabled by default).",
        )
    except Exception:
        p.add_argument(
            "--asof", action="store_true", default=True, help=argparse.SUPPRESS
        )
        p.add_argument(
            "--exact", action="store_false", dest="asof", help=argparse.SUPPRESS
        )

    p.add_argument(
        "files",
        nargs="*",
        help="Optional files. Required for --show. Optional for --diff (repo-wide if omitted).",
    )

    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        ns = parse_args(argv)
        repo_root = Path(ns.repo).resolve()
        rev = (
            _rev_from_commits_ago(ns.commits_ago)
            if ns.commits_ago is not None
            else ns.rev
        )
        files = [Path(f) for f in ns.files]
        out_path = Path(ns.out) if ns.out else None

        if ns.show:
            if not files:
                print("error: --show requires at least one file path.", file=sys.stderr)
                return 2

            bundle, per_file = show_file_contents_at_rev(
                rev,
                files,
                repo_root=repo_root,
                follow_renames=ns.follow_renames,
                as_of=ns.asof,
            )

            # Always print bundle to stdout
            sys.stdout.write(bundle)

            # Clipboard handling
            if ns.clipboard:
                if len(files) == 1:
                    _resolved, content = per_file[files[0]]
                    if content is None:
                        raise GitError(f"Cannot copy: file not found at {rev}.")
                    _clipboard_set(content)
                else:
                    _clipboard_set(bundle)

            # File output handling
            if out_path:
                if len(files) == 1 and not out_path.exists() and out_path.suffix:
                    # Treat as a file path
                    _, content = per_file[files[0]]
                    if content is None:
                        raise GitError(f"Cannot write: file not found at {rev}.")
                    _write_text_to_path(out_path, content)
                else:
                    # Treat as directory: write under <out>/<rev>/<resolved_path>
                    base = out_path
                    base.mkdir(parents=True, exist_ok=True)
                    for _user_path, (resolved_path, content) in per_file.items():
                        if content is None:
                            continue
                        target = base / rev / Path(resolved_path)
                        _write_text_to_path(target, content)

            return 0

        # Diffs
        if ns.commit:
            out = diff_specific_commit(
                rev,
                files or None,
                repo_root=repo_root,
                follow_renames=ns.follow_renames,
            )
            since_mode = False
        else:
            out = diff_since_rev(rev, files or None, repo_root=repo_root)
            since_mode = True

        sys.stdout.write(out)

        if ns.clipboard:
            _clipboard_set(out)

        if out_path:
            target = _choose_diff_outfile_path(out_path, rev, since_mode)
            _write_text_to_path(target, out)

        return 0

    except GitError as ge:
        print(str(ge), file=sys.stderr)
        return 1
    except Exception as ex:
        print(f"Unexpected error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
