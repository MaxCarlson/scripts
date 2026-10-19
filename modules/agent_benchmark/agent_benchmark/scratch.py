"""Cooperative trial-local scratch permission, never a shared-server env override."""

import os
from pathlib import Path, PureWindowsPath

SCOPE_POLICY = "trial-local-scratch-v1"
SCRATCH_NAME = ".agent-bench-scratch"


def validate_policy(policy: str | None) -> None:
    if policy not in (None, SCOPE_POLICY):
        raise ValueError(f"Unknown scope policy: {policy!r}")


def reserved_path(name: str) -> bool:
    return name.replace("\\", "/").split("/")[0].casefold() == SCRATCH_NAME.casefold()


def safe_spelling(value: str) -> bool:
    """Reject Windows aliases/ADS/device paths rather than granting ambiguous writes."""
    if os.name != "nt":
        return True
    path = PureWindowsPath(value)
    if path.drive and not path.root or path.root and not path.drive:
        return False
    if str(path).startswith(("\\\\?\\", "\\\\.\\")):
        return False
    return all(
        not part.endswith((".", " ")) and ":" not in part and not PureWindowsPath(part).is_reserved()
        for part in path.parts
        if part != path.anchor and part not in (".", "..")
    )


def is_scratch(workspace: Path, target: Path, policy: str | None) -> bool:
    validate_policy(policy)
    if policy is None or not safe_spelling(str(target)):
        return False
    try:
        base = workspace.resolve()
        relative = target.resolve().relative_to(base)
        if not reserved_path(relative.as_posix()) or len(relative.parts) < 2:
            return False
        if any(part.casefold() == ".git" for part in relative.parts):
            return False
        # An extant alias is never granted scratch permission, even if it points
        # back inside this workspace. Snapshot capture rejects links independently.
        for path in (target, *target.parents):
            if path == base:
                break
            if path.is_symlink() or path.is_junction():
                return False
        if target.is_file() and target.stat().st_nlink > 1:
            return False
        return True
    except (OSError, ValueError, RuntimeError):
        return False


def temp_environment(workspace: Path) -> dict[str, str]:
    """Settings a worker must apply inside each command, not to the shared server."""
    scratch = workspace.resolve() / SCRATCH_NAME
    if not scratch.is_dir() or scratch.is_symlink() or scratch.is_junction():
        raise ValueError("Trial scratch must be an ordinary directory")
    return {name: str(scratch) for name in ("TMPDIR", "TEMP", "TMP")}


def provenance(workspace: Path) -> dict:
    return {
        "policy_version": SCOPE_POLICY,
        "relative_path": SCRATCH_NAME,
        "path": str(workspace.resolve() / SCRATCH_NAME),
        "environment": temp_environment(workspace),
        "environment_delivery": "worker_command_local",
        "automatic_server_redirection": False,
    }


def prompt_instructions(workspace: Path) -> str:
    scratch = temp_environment(workspace)["TEMP"]
    # Avoid embedding shell-evaluated path literals: derive from the absolute cwd.
    return (
        f"\nScope policy {SCOPE_POLICY}: only task-allowed deliverables and the trial-local scratch "
        f"directory {scratch} may be written. This policy supplements fixture editing limits only for scratch; "
        "task deliverables and other restrictions stay unchanged. Use scratch for temporary scripts, tests and caches; "
        "scratch is evidence, not a deliverable, and is excluded from hidden verifier input. "
        "Do not modify .git or protected task files, create links/hardlinks/junctions, or write external paths. "
        "OpenCode's shared temp path is not allowed by this benchmark even when its tools permit it. "
        "For every shell command launching a program that may use temporary files, set TMPDIR, TEMP and TMP "
        "to the absolute trial scratch path in that same command before launching the program. "
        f"PowerShell from the workspace: $env:TEMP = Join-Path (Get-Location).Path '{SCRATCH_NAME}'; "
        "$env:TMP = $env:TEMP; $env:TMPDIR = $env:TEMP; then run the program. "
        "For other shells use their command-local environment syntax with the same absolute path. "
        "Settings do not persist between tool commands. Prefer explicit scratch paths when APIs allow them. "
        "These are worker instructions; the shared server environment has not been changed."
    )
