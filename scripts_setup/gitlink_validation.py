"""Validate that a checked-out repository matches its parent-tree Gitlink."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path, PurePosixPath


class GitlinkValidationError(RuntimeError):
    """Raised when a parent tree or submodule checkout cannot be verified."""


def _git(repository: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise GitlinkValidationError(
            f"Could not run git for {repository}: {exc}"
        ) from exc
    if result.returncode != 0:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"exit code {result.returncode}"
        )
        raise GitlinkValidationError(f"Git command failed for {repository}: {detail}")
    return result.stdout.strip()


def gitlink_commit(parent_repository: Path, path_in_parent: str) -> str:
    """Read a single Gitlink object ID from HEAD in the parent repository."""
    path = PurePosixPath(path_in_parent)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise GitlinkValidationError(f"Invalid Gitlink path: {path_in_parent!r}")

    output = _git(
        parent_repository, "ls-tree", "HEAD", "--", f":(literal){path.as_posix()}"
    )
    records = [line for line in output.splitlines() if line]
    if len(records) != 1:
        raise GitlinkValidationError(
            f"Parent tree {parent_repository} does not record a Gitlink at {path_in_parent!r}"
        )

    metadata, separator, recorded_path = records[0].partition("\t")
    fields = metadata.split()
    if (
        not separator
        or recorded_path != path.as_posix()
        or len(fields) != 3
        or fields[0] != "160000"
        or fields[1] != "commit"
        or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", fields[2])
    ):
        raise GitlinkValidationError(
            f"Parent tree {parent_repository} does not record a Gitlink at {path_in_parent!r}"
        )
    return fields[2]


def verify_gitlink(
    parent_repository: Path, path_in_parent: str, checkout_repository: Path
) -> str:
    """Require checkout_repository HEAD to equal the parent's recorded Gitlink."""
    expected = gitlink_commit(parent_repository, path_in_parent)
    actual = _git(checkout_repository, "rev-parse", "--verify", "HEAD^{commit}")
    if actual != expected:
        raise GitlinkValidationError(
            f"Checkout {checkout_repository} at {actual} does not match parent Gitlink "
            f"{parent_repository}:{path_in_parent} at {expected}"
        )
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent_repository", type=Path)
    parser.add_argument(
        "path_in_parent", help="Gitlink path recorded in the parent repository tree"
    )
    parser.add_argument("checkout_repository", type=Path)
    parser.add_argument(
        "--label", default=None, help="Human-readable name for the verified submodule"
    )
    args = parser.parse_args()
    label = args.label or args.path_in_parent
    try:
        commit = verify_gitlink(
            args.parent_repository, args.path_in_parent, args.checkout_repository
        )
    except GitlinkValidationError as exc:
        parser.exit(1, f"::error::{exc}\n")
    print(f"Verified {label} Gitlink at {commit}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
