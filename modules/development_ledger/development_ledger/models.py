"""Typed domain models used by the development ledger."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

VALID_IMPLEMENTATION_STATES = {"planned", "in_progress", "implemented", "blocked", "deferred"}
VALID_MANUAL_STATES = {"pending", "passed", "failed", "blocked", "waived"}
VALID_TEST_STATES = {"passed", "failed", "error", "skipped"}
VALID_ACTORS = {"remote_llm", "local_llm", "user", "validator", "unknown"}
VALID_MODES = {"hybrid", "local", "remote", "manual"}
VALID_REQUEST_STATES = {"no_new_request", "incorporated", "conflict_pending"}
VALID_REQUEST_RESOLUTIONS = {"none", "compatible", "explicit_user_override", "user_decision_required"}
VALID_ARCHITECTURE_IMPACTS = {"none", "local", "cross_cutting", "foundational"}
VALID_ARCHITECTURE_ROLES = {"feature", "foundation", "integration", "verification", "migration"}


@dataclass(slots=True)
class NormalizedTest:
    """One normalized automated check from any supported result source."""

    id: str
    name: str
    status: str
    suite: str = ""
    source: str = ""
    file: str = ""
    classname: str = ""
    duration_seconds: float = 0.0
    message: str = ""
    item_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlanItem:
    """A feature, requirement, acceptance criterion, or task tracked by a plan."""

    id: str
    title: str
    kind: str = "criterion"
    implementation: str = "planned"
    tests: list[str] = field(default_factory=list)
    manual_checks: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)
    priority: int = 0
    architecture_role: str = "feature"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ManualCheck:
    """A user-executed validation step that cannot be completed automatically."""

    id: str
    title: str
    item_ids: list[str]
    instructions: list[str]
    expected: str
    platform: str = "any"
    status: str = "pending"
    safety: str = "non_destructive"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlanState:
    """Structured state embedded in an active Markdown plan."""

    schema_version: int
    plan_id: str
    title: str
    project_root: str
    plan_revision: int
    stage: dict[str, Any]
    session: dict[str, Any]
    items: list[PlanItem]
    manual_checks: list[ManualCheck]
    policy: dict[str, Any] = field(default_factory=dict)
    relevant_docs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def item_map(self) -> dict[str, PlanItem]:
        return {item.id: item for item in self.items}

    def manual_check_map(self) -> dict[str, ManualCheck]:
        return {check.id: check for check in self.manual_checks}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "title": self.title,
            "project_root": self.project_root,
            "plan_revision": self.plan_revision,
            "stage": self.stage,
            "session": self.session,
            "items": [item.to_dict() for item in self.items],
            "manual_checks": [check.to_dict() for check in self.manual_checks],
            "policy": self.policy,
            "relevant_docs": self.relevant_docs,
            "metadata": self.metadata,
        }
