"""Validate changes to source trees whose canonical owners are other repositories."""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
from pathlib import PurePosixPath

from scripts_setup.shared_packages import SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION
from scripts_setup.transferred_modules import TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION


def check_changes(changes: list[tuple[str, str, str, str]], exceptions: list[dict[str, str]], *, toolkit: set[str] | None = None, shared: set[str] | None = None) -> list[str]:
    """Return violations for changed transferred files without exact, explained exceptions."""
    errors = []
    toolkit = toolkit if toolkit is not None else set(TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION)
    shared = shared if shared is not None else set(SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION)
    for action, path, before, after in changes:
        parts = PurePosixPath(path).parts
        if len(parts) < 3 or parts[0] != "modules":
            continue
        module = parts[1]
        if module in shared:
            owner = "shared-python-modules"
        elif module in toolkit:
            owner = "llm-agent-toolkit"
        else:
            continue
        allowed = any(
            entry.get("path") == path and entry.get("action") == action and entry.get("before") == before and entry.get("after") == after
            and isinstance(entry.get("reason"), str) and entry["reason"].strip()
            for entry in exceptions if isinstance(entry, dict)
        )
        if not allowed:
            errors.append(f"{action} {path}: canonical owner is {owner}; add an exact reviewed exception for retirement or reconciliation")
    return errors


def registry_at(revision: str, path: str, name: str) -> set[str]:
    """Read literal registry keys from a revision without executing its code."""
    source = subprocess.run(["git", "show", f"{revision}:{path}"], check=True, capture_output=True, text=True).stdout
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
                raise ValueError(f"Invalid ownership registry {name}")
            return set(value)
    raise ValueError(f"Missing ownership registry {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-b", "--base", required=True, help="Git base commit")
    parser.add_argument("-e", "--end", default="HEAD", help="Git head commit")
    args = parser.parse_args()
    result = subprocess.run(
        ["git", "diff", "--raw", "--no-abbrev", "-z", "--no-renames", args.base, args.end, "--"],
        check=True, capture_output=True,
    )
    fields = result.stdout.decode("utf-8").split("\0")
    changes = [(fields[i].split()[4], fields[i + 1], fields[i].split()[2], fields[i].split()[3]) for i in range(0, len(fields) - 1, 2)]
    exception_path = ".github/source-ownership-exceptions.json"
    content = subprocess.run(["git", "show", f"{args.end}:{exception_path}"], check=True, capture_output=True, text=True)
    exceptions = json.loads(content.stdout)
    if not isinstance(exceptions, list):
        raise ValueError("Source ownership exceptions must be a JSON list")
    toolkit = set(TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION) | registry_at(
        args.base, "scripts_setup/transferred_modules.py", "TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION"
    )
    shared = set(SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION) | registry_at(
        args.base, "scripts_setup/shared_packages.py", "SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION"
    )
    errors = check_changes(changes, exceptions, toolkit=toolkit, shared=shared)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())


