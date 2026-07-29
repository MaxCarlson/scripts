"""Parsing and validation for structured plan state embedded in Markdown."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from development_ledger.models import (
    VALID_IMPLEMENTATION_STATES,
    VALID_MANUAL_STATES,
    ManualCheck,
    PlanItem,
    PlanState,
)

START_MARKER = "<!-- development-ledger:state:start -->"
END_MARKER = "<!-- development-ledger:state:end -->"
_BLOCK_RE = re.compile(
    re.escape(START_MARKER) + r"\s*```json\s*(?P<payload>.*?)\s*```\s*" + re.escape(END_MARKER),
    re.DOTALL,
)


class PlanValidationError(ValueError):
    """Raised when a plan's structured state is missing or invalid."""


def load_plan(path: Path) -> PlanState:
    """Load and validate a plan document from ``path``."""

    text = path.read_text(encoding="utf-8")
    return parse_plan_text(text, source=str(path))


def parse_plan_text(text: str, *, source: str = "<memory>") -> PlanState:
    """Parse a structured plan-state JSON block from Markdown text."""

    match = _BLOCK_RE.search(text)
    if not match:
        raise PlanValidationError(
            f"No development-ledger state block found in {source}. "
            f"Expected markers {START_MARKER!r} and {END_MARKER!r}."
        )

    try:
        data = json.loads(match.group("payload"))
    except json.JSONDecodeError as exc:
        raise PlanValidationError(f"Invalid JSON in development-ledger state block at {source}: {exc}") from exc

    return plan_from_dict(data, source=source)


def plan_from_dict(data: dict[str, Any], *, source: str = "<dict>") -> PlanState:
    """Validate a plan-state dictionary and convert it to typed models."""

    if not isinstance(data, dict):
        raise PlanValidationError(f"Plan state in {source} must be a JSON object.")

    required = ("schema_version", "plan_id", "title", "project_root", "stage", "session", "items")
    missing = [name for name in required if name not in data]
    if missing:
        raise PlanValidationError(f"Plan state in {source} is missing required fields: {', '.join(missing)}")

    if data["schema_version"] != 1:
        raise PlanValidationError(
            f"Unsupported plan schema version {data['schema_version']!r} in {source}; expected 1."
        )

    for field_name in ("plan_id", "title", "project_root"):
        if not isinstance(data[field_name], str) or not data[field_name].strip():
            raise PlanValidationError(f"Plan field {field_name!r} in {source} must be a non-empty string.")

    if not isinstance(data["stage"], dict) or not data["stage"].get("id"):
        raise PlanValidationError(f"Plan stage in {source} must be an object with a non-empty 'id'.")
    if not isinstance(data["session"], dict):
        raise PlanValidationError(f"Plan session in {source} must be an object.")

    raw_items = data["items"]
    if not isinstance(raw_items, list) or not raw_items:
        raise PlanValidationError(f"Plan items in {source} must be a non-empty list.")

    items: list[PlanItem] = []
    seen_item_ids: set[str] = set()
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise PlanValidationError(f"Plan item {index} in {source} must be an object.")
        item_id = _required_text(raw_item, "id", source=f"item {index} in {source}")
        title = _required_text(raw_item, "title", source=f"item {item_id} in {source}")
        if item_id in seen_item_ids:
            raise PlanValidationError(f"Duplicate plan item ID {item_id!r} in {source}.")
        seen_item_ids.add(item_id)
        implementation = str(raw_item.get("implementation", "planned"))
        if implementation not in VALID_IMPLEMENTATION_STATES:
            raise PlanValidationError(
                f"Invalid implementation state {implementation!r} for item {item_id} in {source}."
            )
        items.append(
            PlanItem(
                id=item_id,
                title=title,
                kind=str(raw_item.get("kind", "criterion")),
                implementation=implementation,
                tests=_string_list(raw_item.get("tests", []), f"tests for item {item_id}"),
                manual_checks=_string_list(raw_item.get("manual_checks", []), f"manual_checks for item {item_id}"),
                blocked_by=_string_list(raw_item.get("blocked_by", []), f"blocked_by for item {item_id}"),
                relevant_files=_string_list(raw_item.get("relevant_files", []), f"relevant_files for item {item_id}"),
                notes=str(raw_item.get("notes", "")),
            )
        )

    checks: list[ManualCheck] = []
    seen_check_ids: set[str] = set()
    for index, raw_check in enumerate(data.get("manual_checks", [])):
        if not isinstance(raw_check, dict):
            raise PlanValidationError(f"Manual check {index} in {source} must be an object.")
        check_id = _required_text(raw_check, "id", source=f"manual check {index} in {source}")
        if check_id in seen_check_ids:
            raise PlanValidationError(f"Duplicate manual-check ID {check_id!r} in {source}.")
        seen_check_ids.add(check_id)
        status = str(raw_check.get("status", "pending"))
        if status not in VALID_MANUAL_STATES:
            raise PlanValidationError(f"Invalid manual-check state {status!r} for {check_id} in {source}.")
        item_ids = _string_list(raw_check.get("item_ids", []), f"item_ids for manual check {check_id}")
        unknown = sorted(set(item_ids) - seen_item_ids)
        if unknown:
            raise PlanValidationError(
                f"Manual check {check_id} in {source} references unknown item IDs: {', '.join(unknown)}"
            )
        checks.append(
            ManualCheck(
                id=check_id,
                title=_required_text(raw_check, "title", source=f"manual check {check_id} in {source}"),
                item_ids=item_ids,
                instructions=_string_list(raw_check.get("instructions", []), f"instructions for {check_id}"),
                expected=_required_text(raw_check, "expected", source=f"manual check {check_id} in {source}"),
                platform=str(raw_check.get("platform", "any")),
                status=status,
                safety=str(raw_check.get("safety", "non_destructive")),
                notes=str(raw_check.get("notes", "")),
            )
        )

    unknown_check_refs = sorted(
        {check_id for item in items for check_id in item.manual_checks if check_id not in seen_check_ids}
    )
    if unknown_check_refs:
        raise PlanValidationError(
            f"Plan items in {source} reference unknown manual-check IDs: {', '.join(unknown_check_refs)}"
        )

    return PlanState(
        schema_version=1,
        plan_id=data["plan_id"].strip(),
        title=data["title"].strip(),
        project_root=data["project_root"].strip(),
        stage=dict(data["stage"]),
        session=dict(data["session"]),
        items=items,
        manual_checks=checks,
        relevant_docs=_string_list(data.get("relevant_docs", []), "relevant_docs"),
        metadata=dict(data.get("metadata", {})),
    )


def render_plan_template(*, plan_id: str, title: str, project_root: str) -> str:
    """Return a complete Markdown plan template containing a valid state block."""

    payload = {
        "schema_version": 1,
        "plan_id": plan_id,
        "title": title,
        "project_root": project_root,
        "stage": {"id": "S1", "title": "Initial stage", "status": "planned"},
        "session": {
            "actor": "remote_llm",
            "mode": "hybrid",
            "objective": "Define the first bounded implementation objective.",
            "hypothesis": "",
            "target_ids": ["AC-001"],
            "environment_dependencies": [],
            "relevant_files": [],
        },
        "items": [
            {
                "id": "AC-001",
                "kind": "criterion",
                "title": "Replace this with a measurable acceptance criterion.",
                "implementation": "planned",
                "tests": [],
                "manual_checks": [],
                "blocked_by": [],
                "relevant_files": [],
            }
        ],
        "manual_checks": [],
        "relevant_docs": [],
    }
    formatted = json.dumps(payload, indent=4, ensure_ascii=False)
    return (
        f"# {title}\n\n"
        "## Objective\n\nDescribe the plan objective.\n\n"
        "## Development Ledger State\n\n"
        f"{START_MARKER}\n```json\n{formatted}\n```\n{END_MARKER}\n\n"
        "## Design Notes\n\nAdd architecture, tradeoffs, and implementation detail here.\n"
    )


def _required_text(data: dict[str, Any], field_name: str, *, source: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise PlanValidationError(f"Field {field_name!r} for {source} must be a non-empty string.")
    return value.strip()


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PlanValidationError(f"{label} must be a list of strings.")
    return [item for item in value if item]
