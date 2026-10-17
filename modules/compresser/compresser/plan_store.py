"""Atomic persistence for immutable estimation designs and resumable measurements."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import re
import tempfile

from .estimation_models import EstimationPlan
from .workspace import CompressionWorkspace, _unlinked, workspace_publication

_PLAN_ID = re.compile(r"plan-[a-f0-9]{20}\Z")


def _plan_path(workspace: CompressionWorkspace, plan_id: str) -> Path:
    if not isinstance(plan_id, str) or not _PLAN_ID.fullmatch(plan_id):
        raise ValueError("Invalid plan ID")
    path = workspace.plans_dir / f"{plan_id}.json"
    _unlinked(path)
    if path.resolve().parent != workspace.plans_dir.resolve():
        raise ValueError("Plan path escapes the workspace")
    return path


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".plan-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _validate_workspace_plan(workspace: CompressionWorkspace, plan: EstimationPlan) -> None:
    if plan.root.resolve() != workspace.target.resolve() or plan.owner != (
        "mangadl" if workspace.owner == "mangadl-pages" else "compresser"
    ):
        raise ValueError("Plan target or owner does not match workspace")
    if plan.plan_id != f"plan-{plan.design_identity[:20]}":
        raise ValueError("Plan ID does not match immutable design identity")


def save_plan(workspace: CompressionWorkspace, plan: EstimationPlan) -> Path:
    """Publish a plan with an atomic replace under the workspace publication lock."""
    _validate_workspace_plan(workspace, plan)
    path = _plan_path(workspace, plan.plan_id)
    with workspace_publication(workspace):
        _unlinked(path)
        if path.exists() and (not path.is_file() or path.stat().st_nlink > 1):
            raise ValueError("Plan artifact must be a regular file without hardlinks")
        _atomic_write(path, plan.to_dict())
    return path


def load_plan(workspace: CompressionWorkspace, plan_id: str) -> EstimationPlan:
    """Load and verify a plan by its path-safe immutable ID."""
    path = _plan_path(workspace, plan_id)
    if not path.is_file() or path.stat().st_nlink > 1:
        raise ValueError(f"Estimation plan does not exist or is not an owned regular file: {plan_id}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        plan = EstimationPlan.from_dict(payload)
    except (OSError, TypeError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load estimation plan {plan_id}: {exc}") from exc
    _validate_workspace_plan(workspace, plan)
    if plan.plan_id != plan_id:
        raise ValueError("Plan file identity does not match its requested ID")
    return plan


def append_plan_measurements(
    workspace: CompressionWorkspace,
    plan_id: str,
    measurements: tuple[dict, ...] | list[dict],
    *,
    expected_design_identity: str | None = None,
) -> EstimationPlan:
    """Atomically append execution facts without changing the frozen design."""
    path = _plan_path(workspace, plan_id)
    with workspace_publication(workspace):
        current = load_plan(workspace, plan_id)
        if expected_design_identity is not None and current.design_identity != expected_design_identity:
            raise ValueError("Estimation plan design changed; rebuild before recording measurements")
        additions = tuple(dict(item) for item in measurements)
        # Validate the full payload before acquiring a temporary file or replacing the last good plan.
        json.dumps(additions, allow_nan=False)
        updated = replace(current, measurements=(*current.measurements, *additions))
        _unlinked(path)
        _atomic_write(path, updated.to_dict())
    return updated
