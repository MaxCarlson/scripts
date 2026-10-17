"""Explicit, token-bound recovery UI shared by both compression commands."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .transactions import inspect_recovery, recover


def recovery_plan(directory: Path) -> dict:
    """Preview one exact directory; do not recursively sweep a library."""
    resolved = directory.expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"Recovery directory does not exist: {resolved}")
    candidate = inspect_recovery(resolved)
    payload = {"schema": 1, "kind": "compresser-recovery", "directory": str(resolved), "candidate": candidate}
    token = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {**payload, "confirmation_token": token}


def run_recovery(
    directory: Path, *, apply: bool = False, confirmation: str | None = None, as_json: bool = False
) -> int:
    """Preview or apply exactly the reviewed recovery record."""
    plan = recovery_plan(directory)
    if apply:
        if confirmation != plan["confirmation_token"]:
            raise ValueError("Recovery confirmation mismatch; preview again and use -C TOKEN with -w")
        plan["recovered"] = recover(
            directory,
            apply=True,
            expected_journal_hash=plan["candidate"]["journal_sha256"] if plan["candidate"] else None,
        )
    else:
        plan["recovered"] = 0
    if as_json:
        print(json.dumps(plan, indent=2))
    else:
        candidate = plan["candidate"]
        print(f"Recovery directory: {plan['directory']}")
        if candidate:
            print(f"  Action: {candidate['action']}")
            print(f"  Original: {candidate['original']}")
            print(f"  Output: {candidate['output']}")
            print(f"  Confirmation token: {plan['confirmation_token']}")
            print(f"  Recovered: {plan['recovered']}" if apply else "  Preview only. Add -w -C TOKEN to apply.")
        else:
            print("  No pending compression transaction.")
    return 0
