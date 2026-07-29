"""Parsing and validation for structured plan state embedded in Markdown."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from development_ledger.models import (
    VALID_ARCHITECTURE_IMPACTS,
    VALID_ARCHITECTURE_ROLES,
    VALID_IMPLEMENTATION_STATES,
    VALID_MANUAL_STATES,
    VALID_REQUEST_RESOLUTIONS,
    VALID_REQUEST_STATES,
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

DEFAULT_POLICY: dict[str, Any] = {
    "session": {
        "target_minutes": 15,
        "max_minutes": 20,
        "max_items": 4,
    },
    "architecture_review": {
        "max_validation_runs": 5,
        "max_plan_revisions": 3,
    },
}


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

    required = (
        "schema_version",
        "plan_id",
        "title",
        "project_root",
        "plan_revision",
        "stage",
        "session",
        "items",
    )
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

    plan_revision = data["plan_revision"]
    if not isinstance(plan_revision, int) or isinstance(plan_revision, bool) or plan_revision < 1:
        raise PlanValidationError(f"plan_revision in {source} must be an integer greater than or equal to 1.")

    if not isinstance(data["stage"], dict) or not data["stage"].get("id"):
        raise PlanValidationError(f"Plan stage in {source} must be an object with a non-empty 'id'.")
    if not isinstance(data["session"], dict):
        raise PlanValidationError(f"Plan session in {source} must be an object.")

    policy = _merge_policy(data.get("policy", {}), source=source)
    session = _validate_session(dict(data["session"]), policy=policy, source=source)

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
        architecture_role = str(raw_item.get("architecture_role", "feature"))
        if architecture_role not in VALID_ARCHITECTURE_ROLES:
            raise PlanValidationError(
                f"Invalid architecture_role {architecture_role!r} for item {item_id} in {source}."
            )
        priority = raw_item.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise PlanValidationError(f"priority for item {item_id} in {source} must be an integer.")
        items.append(
            PlanItem(
                id=item_id,
                title=title,
                kind=str(raw_item.get("kind", "criterion")),
                implementation=implementation,
                tests=_string_list(raw_item.get("tests", []), f"tests for item {item_id}"),
                manual_checks=_string_list(raw_item.get("manual_checks", []), f"manual_checks for item {item_id}"),
                depends_on=_string_list(raw_item.get("depends_on", []), f"depends_on for item {item_id}"),
                blocked_by=_string_list(raw_item.get("blocked_by", []), f"blocked_by for item {item_id}"),
                relevant_files=_string_list(raw_item.get("relevant_files", []), f"relevant_files for item {item_id}"),
                priority=priority,
                architecture_role=architecture_role,
                notes=str(raw_item.get("notes", "")),
            )
        )

    item_ids = {item.id for item in items}
    for item in items:
        unknown_dependencies = sorted(set(item.depends_on) - item_ids)
        if unknown_dependencies:
            raise PlanValidationError(
                f"Item {item.id} in {source} depends on unknown item IDs: {', '.join(unknown_dependencies)}"
            )
        if item.id in item.depends_on:
            raise PlanValidationError(f"Item {item.id} in {source} cannot depend on itself.")

    target_ids = set(_string_list(session.get("target_ids", []), "session.target_ids"))
    unknown_targets = sorted(target_ids - item_ids)
    if unknown_targets:
        raise PlanValidationError(
            f"Session in {source} targets unknown item IDs: {', '.join(unknown_targets)}"
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
        check_item_ids = _string_list(raw_check.get("item_ids", []), f"item_ids for manual check {check_id}")
        unknown = sorted(set(check_item_ids) - item_ids)
        if unknown:
            raise PlanValidationError(
                f"Manual check {check_id} in {source} references unknown item IDs: {', '.join(unknown)}"
            )
        checks.append(
            ManualCheck(
                id=check_id,
                title=_required_text(raw_check, "title", source=f"manual check {check_id} in {source}"),
                item_ids=check_item_ids,
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
        plan_revision=plan_revision,
        stage=dict(data["stage"]),
        session=session,
        items=items,
        manual_checks=checks,
        policy=policy,
        relevant_docs=_string_list(data.get("relevant_docs", []), "relevant_docs"),
        metadata=dict(data.get("metadata", {})),
    )


def render_plan_template(
    *,
    plan_id: str,
    title: str,
    project_root: str,
    policy: dict[str, Any] | None = None,
) -> str:
    """Return a complete Markdown plan template containing a valid state block."""

    effective_policy = _merge_policy(policy or {}, source="plan template")
    session_policy = effective_policy["session"]
    payload = {
        "schema_version": 1,
        "plan_id": plan_id,
        "title": title,
        "project_root": project_root,
        "plan_revision": 1,
        "stage": {"id": "S1", "title": "Initial stage", "status": "planned"},
        "session": {
            "actor": "remote_llm",
            "mode": "hybrid",
            "request": {
                "status": "incorporated",
                "summary": "Create the initial plan before implementation.",
                "resolution": "compatible",
                "affected_ids": ["AC-001"],
                "supersedes": [],
                "conflicts": [],
            },
            "objective": "Define and implement one bounded, dependency-cohesive batch.",
            "hypothesis": "",
            "target_ids": ["AC-001"],
            "selection_rationale": "This is the first independently verifiable prerequisite.",
            "stop_conditions": ["The selected item is implemented and its expected validation is ready."],
            "batch": {
                "profile": "standard",
                "target_minutes": session_policy["target_minutes"],
                "max_minutes": session_policy["max_minutes"],
                "max_items": session_policy["max_items"],
            },
            "environment_dependencies": [],
            "diagnostic_complexity": "normal",
            "architecture_impact": "local",
            "architecture_review": {
                "requested": False,
                "performed": False,
                "summary": "",
                "findings": [],
                "actions": [],
            },
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
                "depends_on": [],
                "blocked_by": [],
                "relevant_files": [],
                "priority": 0,
                "architecture_role": "feature",
            }
        ],
        "manual_checks": [],
        "policy": effective_policy,
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


def _validate_session(session: dict[str, Any], *, policy: dict[str, Any], source: str) -> dict[str, Any]:
    request = session.get("request")
    if not isinstance(request, dict):
        raise PlanValidationError(f"session.request in {source} must be an object.")
    request_status = str(request.get("status", ""))
    if request_status not in VALID_REQUEST_STATES:
        raise PlanValidationError(
            f"Invalid session.request.status {request_status!r} in {source}; "
            f"expected one of {sorted(VALID_REQUEST_STATES)}."
        )
    resolution = str(request.get("resolution", "none"))
    if resolution not in VALID_REQUEST_RESOLUTIONS:
        raise PlanValidationError(
            f"Invalid session.request.resolution {resolution!r} in {source}; "
            f"expected one of {sorted(VALID_REQUEST_RESOLUTIONS)}."
        )
    request["affected_ids"] = _string_list(request.get("affected_ids", []), "session.request.affected_ids")
    request["supersedes"] = _string_list(request.get("supersedes", []), "session.request.supersedes")
    request["conflicts"] = _string_list(request.get("conflicts", []), "session.request.conflicts")
    request["summary"] = str(request.get("summary", "")).strip()
    if request_status == "incorporated" and not request["summary"]:
        raise PlanValidationError(f"session.request.summary in {source} is required when status is incorporated.")
    if request_status == "conflict_pending" and not request["conflicts"]:
        raise PlanValidationError(f"session.request.conflicts in {source} is required when status is conflict_pending.")
    if request_status == "conflict_pending" and resolution != "user_decision_required":
        raise PlanValidationError(
            f"session.request.resolution in {source} must be user_decision_required when conflict is pending."
        )
    session["request"] = request

    session["target_ids"] = _string_list(session.get("target_ids", []), "session.target_ids")
    session["stop_conditions"] = _string_list(session.get("stop_conditions", []), "session.stop_conditions")
    session["environment_dependencies"] = _string_list(
        session.get("environment_dependencies", []), "session.environment_dependencies"
    )
    session["relevant_files"] = _string_list(session.get("relevant_files", []), "session.relevant_files")
    session["selection_rationale"] = str(session.get("selection_rationale", "")).strip()
    if session["target_ids"] and not session["selection_rationale"]:
        raise PlanValidationError(f"session.selection_rationale in {source} is required when target_ids are selected.")

    batch = session.get("batch", {})
    if not isinstance(batch, dict):
        raise PlanValidationError(f"session.batch in {source} must be an object.")
    defaults = policy["session"]
    normalized_batch = {
        "profile": str(batch.get("profile", "standard")),
        "target_minutes": _positive_int(batch.get("target_minutes", defaults["target_minutes"]), "target_minutes", source),
        "max_minutes": _positive_int(batch.get("max_minutes", defaults["max_minutes"]), "max_minutes", source),
        "max_items": _positive_int(batch.get("max_items", defaults["max_items"]), "max_items", source),
    }
    if normalized_batch["max_minutes"] < normalized_batch["target_minutes"]:
        raise PlanValidationError(f"session.batch.max_minutes in {source} cannot be less than target_minutes.")
    session["batch"] = normalized_batch

    architecture_impact = str(session.get("architecture_impact", "none"))
    if architecture_impact not in VALID_ARCHITECTURE_IMPACTS:
        raise PlanValidationError(
            f"Invalid session.architecture_impact {architecture_impact!r} in {source}; "
            f"expected one of {sorted(VALID_ARCHITECTURE_IMPACTS)}."
        )
    session["architecture_impact"] = architecture_impact

    review = session.get("architecture_review", {})
    if not isinstance(review, dict):
        raise PlanValidationError(f"session.architecture_review in {source} must be an object.")
    session["architecture_review"] = {
        "requested": bool(review.get("requested", False)),
        "performed": bool(review.get("performed", False)),
        "summary": str(review.get("summary", "")).strip(),
        "findings": _string_list(review.get("findings", []), "session.architecture_review.findings"),
        "actions": _string_list(review.get("actions", []), "session.architecture_review.actions"),
    }
    if session["architecture_review"]["performed"] and not session["architecture_review"]["summary"]:
        raise PlanValidationError(
            f"session.architecture_review.summary in {source} is required when a review was performed."
        )
    return session


def _merge_policy(policy: Any, *, source: str) -> dict[str, Any]:
    if policy is None:
        policy = {}
    if not isinstance(policy, dict):
        raise PlanValidationError(f"policy in {source} must be an object.")
    merged = deepcopy(DEFAULT_POLICY)
    for section_name in ("session", "architecture_review"):
        section = policy.get(section_name, {})
        if not isinstance(section, dict):
            raise PlanValidationError(f"policy.{section_name} in {source} must be an object.")
        merged[section_name].update(section)

    session = merged["session"]
    session["target_minutes"] = _positive_int(session["target_minutes"], "policy.session.target_minutes", source)
    session["max_minutes"] = _positive_int(session["max_minutes"], "policy.session.max_minutes", source)
    session["max_items"] = _positive_int(session["max_items"], "policy.session.max_items", source)
    if session["max_minutes"] < session["target_minutes"]:
        raise PlanValidationError(f"policy.session.max_minutes in {source} cannot be less than target_minutes.")

    review = merged["architecture_review"]
    review["max_validation_runs"] = _positive_int(
        review["max_validation_runs"], "policy.architecture_review.max_validation_runs", source
    )
    review["max_plan_revisions"] = _positive_int(
        review["max_plan_revisions"], "policy.architecture_review.max_plan_revisions", source
    )
    return merged


def _positive_int(value: Any, label: str, source: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PlanValidationError(f"{label} in {source} must be an integer greater than or equal to 1.")
    return value


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
