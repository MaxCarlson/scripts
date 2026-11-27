"""Core service layer for GUI-agent session continuity (Phase 1 M1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .environment import (
    assert_sqlite_writer_allowed,
    detect_runtime_kind,
    is_windows_mount_path,
    is_wsl2,
    load_or_create_environment,
    resolve_environment_selector,
    resolve_home_dir,
)
from .errors import ContinuityError, ErrorCode
from .events import append_event, discover_spool_roots, read_spool_events
from .identifiers import (
    generate_id,
    generate_workflow_id,
    normalize_gui_url,
    normalize_path_canonical,
    normalize_repo_identity,
    now_utc_iso,
    validate_slug,
)
from .materializer import SQLiteMaterializer, SyncResult
from .models import (
    AssociationRecord,
    AssociationStatus,
    EnvironmentInfo,
    EventEnvelope,
    EventType,
    EvidenceLevel,
    Provider,
    SessionLifecycleStatus,
    Workflow,
    WorkflowStatus,
)
from .providers import ProviderAdapter, ResumePlan, default_adapters

SCHEMA_EVENT_VERSION = 1
ADAPTER_VERSION = "0.1.0"
_VALID_PROVIDERS = {p.value for p in Provider}
_VALID_LIFECYCLE = {s.value for s in SessionLifecycleStatus}


@dataclass(slots=True)
class MutationPreview:
    """Result returned by mutating operations (dry-run or applied)."""

    action: str
    applied: bool
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "applied": self.applied,
            "summary": self.summary,
            "details": self.details,
            "events": self.events,
        }


class ContinuityService:
    """High-level registry, event emission, continuity query, and diagnostic API."""

    def __init__(
        self,
        home_dir: Path | str | None = None,
        *,
        adapters: dict[str, ProviderAdapter] | None = None,
        allow_unsafe_cross_os: bool = False,
    ) -> None:
        self.home_dir = resolve_home_dir(home_dir)
        self.materializer = SQLiteMaterializer(self.home_dir, allow_unsafe_cross_os=allow_unsafe_cross_os)
        self.adapters = adapters if adapters is not None else default_adapters()
        self.allow_unsafe_cross_os = allow_unsafe_cross_os

    def _can_write_sqlite(self) -> bool:
        if self.allow_unsafe_cross_os:
            return True
        return not (is_wsl2() and is_windows_mount_path(self.materializer.db_path))

    def _sync_if_safe(self) -> SyncResult | None:
        if not self._can_write_sqlite():
            return None
        return self.materializer.sync_from_spools()

    def _validate_provider(self, provider: str) -> str:
        norm = provider.strip().lower()
        if norm not in _VALID_PROVIDERS:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                f"Unsupported provider {provider!r}. Expected one of: {', '.join(sorted(_VALID_PROVIDERS))}.",
                {"provider": provider},
            )
        return norm

    def _emit_and_materialize(self, events: list[EventEnvelope]) -> None:
        if not events:
            return
        items: list[tuple[EventEnvelope, str | None, str]] = []
        for ev in events:
            spool_path = append_event(self.home_dir, ev)
            items.append((ev, str(spool_path), ""))
        if self._can_write_sqlite():
            self.materializer.ingest_events(items)

    def _ensure_environment_event(
        self,
        env: EnvironmentInfo,
        known_envs: list[EnvironmentInfo],
        ts: str,
    ) -> list[EventEnvelope]:
        if any(e.environment_id == env.environment_id for e in known_envs):
            return []
        return [
            EventEnvelope(
                event_id=generate_id("evt"),
                event_schema_version=SCHEMA_EVENT_VERSION,
                event_type=EventType.ENVIRONMENT_REGISTERED.value,
                provider=None,
                environment_id=env.environment_id,
                native_session_id=None,
                source_timestamp=ts,
                observed_timestamp=ts,
                source_adapter_version=ADAPTER_VERSION,
                payload=env.to_dict(),
            )
        ]

    # ------------------------------------------------------------------
    # Workflow Management
    # ------------------------------------------------------------------

    def add_workflow(
        self,
        *,
        slug: str,
        title: str | None = None,
        urls: list[str] | None = None,
        repo_paths: list[str] | None = None,
        apply: bool = False,
    ) -> MutationPreview:
        """Register a new ChatGPT GUI workflow (dry-run unless apply=True)."""
        self._sync_if_safe()
        norm_slug = validate_slug(slug)
        clean_title = (title or norm_slug).strip()
        if not clean_title:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Workflow title cannot be empty.")

        existing = self.materializer.list_workflows(status="all")
        for wf in existing:
            if wf.slug == norm_slug:
                raise ContinuityError(
                    ErrorCode.WORKFLOW_ALREADY_EXISTS,
                    f"Workflow slug {norm_slug!r} already exists ({wf.workflow_id}).",
                    {"workflow_id": wf.workflow_id, "slug": wf.slug},
                )

        taken_ids = {wf.workflow_id for wf in existing}
        wf_id = generate_workflow_id(taken_ids)
        ts = now_utc_iso()

        gui_entries: list[dict[str, Any]] = []
        for idx, raw_url in enumerate(urls or []):
            clean_url, canonical_url = normalize_gui_url(raw_url)
            gui_entries.append(
                {
                    "gui_ref_id": generate_id("gui"),
                    "workflow_id": wf_id,
                    "url": clean_url,
                    "canonical_url": canonical_url,
                    "title": clean_title if idx == 0 else None,
                    "relationship": "primary" if idx == 0 else "continuation",
                    "status": "active",
                    "created_at": ts,
                }
            )

        norm_repos = []
        seen_repos: set[str] = set()
        for r in repo_paths or []:
            canon = normalize_repo_identity(r)
            if canon and canon not in seen_repos:
                seen_repos.add(canon)
                norm_repos.append(canon)

        local_env = load_or_create_environment(self.home_dir, persist=apply)
        known_envs = self.materializer.list_environments()
        events = self._ensure_environment_event(local_env, known_envs, ts)
        events.append(
            EventEnvelope(
                event_id=generate_id("evt"),
                event_schema_version=SCHEMA_EVENT_VERSION,
                event_type=EventType.WORKFLOW_REGISTERED.value,
                provider=None,
                environment_id=local_env.environment_id,
                native_session_id=None,
                source_timestamp=ts,
                observed_timestamp=ts,
                source_adapter_version=ADAPTER_VERSION,
                payload={
                    "workflow_id": wf_id,
                    "slug": norm_slug,
                    "title": clean_title,
                    "repo_paths": norm_repos,
                    "status": WorkflowStatus.ACTIVE.value,
                    "created_at": ts,
                    "gui_conversations": gui_entries,
                },
            )
        )

        if apply:
            self._emit_and_materialize(events)

        handoff_instruction = f"Begin each implementation handoff with `Workflow-ID: {wf_id}`."
        return MutationPreview(
            action="wf.add",
            applied=apply,
            summary=(
                f"Registered workflow {norm_slug!r} ({wf_id})"
                if apply
                else f"Dry-run: would register workflow {norm_slug!r} ({wf_id})"
            ),
            details={
                "workflow_id": wf_id,
                "slug": norm_slug,
                "title": clean_title,
                "repo_paths": norm_repos,
                "gui_conversations": gui_entries,
                "handoff_instruction": handoff_instruction,
            },
            events=[e.to_dict() for e in events],
        )

    def list_workflows(self, *, status: str = "active") -> list[Workflow]:
        self._sync_if_safe()
        return self.materializer.list_workflows(status=status)

    def show_workflow(self, identifier: str) -> dict[str, Any]:
        """Return detailed metadata and continuity summary for one workflow."""
        return self.find_sessions(workflow_identifier=identifier)

    def archive_workflow(self, identifier: str, *, apply: bool = False) -> MutationPreview:
        self._sync_if_safe()
        wf = self.materializer.get_workflow(identifier)
        if wf is None:
            raise ContinuityError(ErrorCode.WORKFLOW_NOT_FOUND, f"Workflow not found: {identifier!r}")
        local_env = load_or_create_environment(self.home_dir, persist=apply)
        ts = now_utc_iso()
        events = [
            EventEnvelope(
                event_id=generate_id("evt"),
                event_schema_version=SCHEMA_EVENT_VERSION,
                event_type=EventType.WORKFLOW_ARCHIVED.value,
                provider=None,
                environment_id=local_env.environment_id,
                native_session_id=None,
                source_timestamp=ts,
                observed_timestamp=ts,
                source_adapter_version=ADAPTER_VERSION,
                payload={"workflow_id": wf.workflow_id, "slug": wf.slug},
            )
        ]
        if apply:
            self._emit_and_materialize(events)
        return MutationPreview(
            action="wf.archive",
            applied=apply,
            summary=(
                f"Archived workflow {wf.slug} ({wf.workflow_id})"
                if apply
                else f"Dry-run: would archive workflow {wf.slug} ({wf.workflow_id})"
            ),
            details={"workflow_id": wf.workflow_id, "slug": wf.slug},
            events=[e.to_dict() for e in events],
        )

    def add_gui_conversation(
        self,
        identifier: str,
        *,
        url: str,
        title: str | None = None,
        relationship: str = "continuation",
        apply: bool = False,
    ) -> MutationPreview:
        """Associate an additional ChatGPT GUI conversation URL with an existing workflow."""
        self._sync_if_safe()
        wf = self.materializer.get_workflow(identifier)
        if wf is None:
            raise ContinuityError(ErrorCode.WORKFLOW_NOT_FOUND, f"Workflow not found: {identifier!r}")
        clean_url, canonical_url = normalize_gui_url(url)
        local_env = load_or_create_environment(self.home_dir, persist=apply)
        ts = now_utc_iso()
        gui_ref_id = generate_id("gui")
        events = [
            EventEnvelope(
                event_id=generate_id("evt"),
                event_schema_version=SCHEMA_EVENT_VERSION,
                event_type=EventType.WORKFLOW_GUI_LINKED.value,
                provider=None,
                environment_id=local_env.environment_id,
                native_session_id=None,
                source_timestamp=ts,
                observed_timestamp=ts,
                source_adapter_version=ADAPTER_VERSION,
                payload={
                    "gui_ref_id": gui_ref_id,
                    "workflow_id": wf.workflow_id,
                    "url": clean_url,
                    "canonical_url": canonical_url,
                    "title": title.strip() if title else None,
                    "relationship": relationship.strip() or "continuation",
                    "created_at": ts,
                },
            )
        ]
        if apply:
            self._emit_and_materialize(events)
        return MutationPreview(
            action="wf.gui_add",
            applied=apply,
            summary=(
                f"Linked GUI conversation {canonical_url} to {wf.slug} ({wf.workflow_id})"
                if apply
                else f"Dry-run: would link GUI conversation {canonical_url} to {wf.slug} ({wf.workflow_id})"
            ),
            details={
                "gui_ref_id": gui_ref_id,
                "workflow_id": wf.workflow_id,
                "url": clean_url,
                "canonical_url": canonical_url,
                "relationship": relationship,
            },
            events=[e.to_dict() for e in events],
        )

    # ------------------------------------------------------------------
    # Manual Session Association & Lifecycle
    # ------------------------------------------------------------------

    def link_session(
        self,
        *,
        workflow_identifier: str,
        provider: str,
        native_session_id: str,
        environment_selector: str | None = None,
        cwd: str | None = None,
        repo_path: str | None = None,
        title: str | None = None,
        evidence_level: str = EvidenceLevel.CONFIRMED.value,
        note: str | None = None,
        supersede: bool = False,
        apply: bool = False,
    ) -> MutationPreview:
        """Manually associate a native provider session with a registered workflow."""
        self._sync_if_safe()
        norm_provider = self._validate_provider(provider)
        session_id = native_session_id.strip()
        if not session_id:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Session ID cannot be empty.")

        wf = self.materializer.get_workflow(workflow_identifier)
        if wf is None:
            raise ContinuityError(ErrorCode.WORKFLOW_NOT_FOUND, f"Workflow not found: {workflow_identifier!r}")

        level = evidence_level.strip().lower()
        if level not in {EvidenceLevel.CONFIRMED.value, EvidenceLevel.CANDIDATE.value}:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                f"Manual link evidence level must be 'confirmed' or 'candidate', got {evidence_level!r}.",
            )

        local_env = load_or_create_environment(self.home_dir, persist=apply)
        known_envs = self.materializer.list_environments()
        target_env = resolve_environment_selector(environment_selector, known_envs, local_env)

        existing_assocs = self.materializer.list_associations(
            provider=norm_provider,
            environment_id=target_env.environment_id,
            native_session_id=session_id,
        )
        other_active = [
            a
            for a in existing_assocs
            if a.workflow_id != wf.workflow_id
            and a.status in (AssociationStatus.ACTIVE.value, AssociationStatus.CONFLICT.value)
            and a.evidence_level in (EvidenceLevel.CONFIRMED.value, EvidenceLevel.STRONG.value)
        ]

        if other_active and level == EvidenceLevel.CONFIRMED.value and not supersede:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                (
                    f"Session ({norm_provider}, {target_env.environment_id}, {session_id}) already has an active "
                    f"association with workflow {other_active[0].workflow_id}. "
                    "Pass --supersede (-X) to supersede the existing association or use --level candidate."
                ),
                {
                    "existing_workflows": [a.workflow_id for a in other_active],
                    "target_workflow": wf.workflow_id,
                    "provider": norm_provider,
                    "environment_id": target_env.environment_id,
                    "native_session_id": session_id,
                },
            )

        ts = now_utc_iso()
        events = self._ensure_environment_event(target_env, known_envs, ts)

        cwd_canon = normalize_path_canonical(cwd)
        repo_id = normalize_repo_identity(repo_path or cwd)
        events.append(
            EventEnvelope(
                event_id=generate_id("evt"),
                event_schema_version=SCHEMA_EVENT_VERSION,
                event_type=EventType.SESSION_REGISTERED.value,
                provider=norm_provider,
                environment_id=target_env.environment_id,
                native_session_id=session_id,
                source_timestamp=ts,
                observed_timestamp=ts,
                source_adapter_version=ADAPTER_VERSION,
                payload={
                    "environment": target_env.to_dict(),
                    "cwd_native": cwd,
                    "cwd_canonical": cwd_canon,
                    "repository_identity": repo_id,
                    "native_title": title.strip() if title else None,
                    "first_observed_at": ts,
                    "last_seen_at": ts,
                    "metadata_source": "manual",
                },
            )
        )

        supersede_ids = [a.association_id for a in other_active] if (supersede and level == EvidenceLevel.CONFIRMED.value) else []
        assoc_status = (
            AssociationStatus.CONFLICT.value
            if (other_active and level == EvidenceLevel.CANDIDATE.value)
            else AssociationStatus.ACTIVE.value
        )
        assoc_id = generate_id("assoc")
        events.append(
            EventEnvelope(
                event_id=generate_id("evt"),
                event_schema_version=SCHEMA_EVENT_VERSION,
                event_type=EventType.ASSOCIATION_CREATED.value,
                provider=norm_provider,
                environment_id=target_env.environment_id,
                native_session_id=session_id,
                source_timestamp=ts,
                observed_timestamp=ts,
                source_adapter_version=ADAPTER_VERSION,
                payload={
                    "association_id": assoc_id,
                    "workflow_id": wf.workflow_id,
                    "evidence_level": level,
                    "association_method": "manual_link" if level == EvidenceLevel.CONFIRMED.value else "manual_candidate",
                    "evidence_summary": note or ("Explicit manual user link" if level == "confirmed" else "Candidate association"),
                    "evidence_reference": None,
                    "status": assoc_status,
                    "supersede_association_ids": supersede_ids,
                    "confirmed_at": ts if level == EvidenceLevel.CONFIRMED.value else None,
                    "created_at": ts,
                    "detail": {"note": note, "superseded_ids": supersede_ids},
                },
            )
        )

        if apply:
            self._emit_and_materialize(events)

        return MutationPreview(
            action="link",
            applied=apply,
            summary=(
                f"Linked ({norm_provider}, {target_env.environment_id}, {session_id}) -> {wf.slug} ({wf.workflow_id}) [{level}]"
                if apply
                else f"Dry-run: would link ({norm_provider}, {target_env.environment_id}, {session_id}) -> {wf.slug} ({wf.workflow_id}) [{level}]"
            ),
            details={
                "association_id": assoc_id,
                "workflow_id": wf.workflow_id,
                "slug": wf.slug,
                "provider": norm_provider,
                "environment_id": target_env.environment_id,
                "native_session_id": session_id,
                "evidence_level": level,
                "status": assoc_status,
                "superseded_association_ids": supersede_ids,
            },
            events=[e.to_dict() for e in events],
        )

    def unlink_session(
        self,
        *,
        workflow_identifier: str,
        provider: str,
        native_session_id: str,
        environment_selector: str | None = None,
        note: str | None = None,
        apply: bool = False,
    ) -> MutationPreview:
        """Unlink an active association between a workflow and a native session."""
        self._sync_if_safe()
        norm_provider = self._validate_provider(provider)
        session_id = native_session_id.strip()
        wf = self.materializer.get_workflow(workflow_identifier)
        if wf is None:
            raise ContinuityError(ErrorCode.WORKFLOW_NOT_FOUND, f"Workflow not found: {workflow_identifier!r}")

        local_env = load_or_create_environment(self.home_dir, persist=apply)
        known_envs = self.materializer.list_environments()
        target_env = resolve_environment_selector(environment_selector, known_envs, local_env)

        assocs = self.materializer.list_associations(
            workflow_id=wf.workflow_id,
            provider=norm_provider,
            environment_id=target_env.environment_id,
            native_session_id=session_id,
        )
        targets = [
            a
            for a in assocs
            if a.status in (AssociationStatus.ACTIVE.value, AssociationStatus.CONFLICT.value)
        ]
        if not targets:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_UNKNOWN,
                f"No active association found between {wf.slug} ({wf.workflow_id}) and ({norm_provider}, {target_env.environment_id}, {session_id}).",
            )

        ts = now_utc_iso()
        events = [
            EventEnvelope(
                event_id=generate_id("evt"),
                event_schema_version=SCHEMA_EVENT_VERSION,
                event_type=EventType.ASSOCIATION_UNLINKED.value,
                provider=norm_provider,
                environment_id=target_env.environment_id,
                native_session_id=session_id,
                source_timestamp=ts,
                observed_timestamp=ts,
                source_adapter_version=ADAPTER_VERSION,
                payload={
                    "association_id": a.association_id,
                    "workflow_id": wf.workflow_id,
                    "note": note,
                },
            )
            for a in targets
        ]
        if apply:
            self._emit_and_materialize(events)

        return MutationPreview(
            action="unlink",
            applied=apply,
            summary=(
                f"Unlinked {len(targets)} association(s) for ({norm_provider}, {target_env.environment_id}, {session_id}) from {wf.slug}"
                if apply
                else f"Dry-run: would unlink {len(targets)} association(s) from {wf.slug}"
            ),
            details={
                "workflow_id": wf.workflow_id,
                "unlinked_association_ids": [a.association_id for a in targets],
            },
            events=[e.to_dict() for e in events],
        )

    def reject_candidate(
        self,
        *,
        workflow_identifier: str,
        provider: str,
        native_session_id: str,
        environment_selector: str | None = None,
        note: str | None = None,
        apply: bool = False,
    ) -> MutationPreview:
        """Persistently reject a candidate or conflicting association."""
        self._sync_if_safe()
        norm_provider = self._validate_provider(provider)
        session_id = native_session_id.strip()
        wf = self.materializer.get_workflow(workflow_identifier)
        if wf is None:
            raise ContinuityError(ErrorCode.WORKFLOW_NOT_FOUND, f"Workflow not found: {workflow_identifier!r}")

        local_env = load_or_create_environment(self.home_dir, persist=apply)
        known_envs = self.materializer.list_environments()
        target_env = resolve_environment_selector(environment_selector, known_envs, local_env)

        assocs = self.materializer.list_associations(
            workflow_id=wf.workflow_id,
            provider=norm_provider,
            environment_id=target_env.environment_id,
            native_session_id=session_id,
        )
        targets = [
            a
            for a in assocs
            if a.status in (AssociationStatus.ACTIVE.value, AssociationStatus.CONFLICT.value)
        ]
        if not targets:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_UNKNOWN,
                f"No candidate or active association found to reject for {wf.slug} and ({norm_provider}, {target_env.environment_id}, {session_id}).",
            )

        ts = now_utc_iso()
        events = [
            EventEnvelope(
                event_id=generate_id("evt"),
                event_schema_version=SCHEMA_EVENT_VERSION,
                event_type=EventType.ASSOCIATION_CANDIDATE_REJECTED.value,
                provider=norm_provider,
                environment_id=target_env.environment_id,
                native_session_id=session_id,
                source_timestamp=ts,
                observed_timestamp=ts,
                source_adapter_version=ADAPTER_VERSION,
                payload={
                    "association_id": a.association_id,
                    "workflow_id": wf.workflow_id,
                    "note": note,
                },
            )
            for a in targets
        ]
        if apply:
            self._emit_and_materialize(events)

        return MutationPreview(
            action="reject",
            applied=apply,
            summary=(
                f"Rejected {len(targets)} association(s) for ({norm_provider}, {target_env.environment_id}, {session_id})"
                if apply
                else f"Dry-run: would reject {len(targets)} association(s)"
            ),
            details={"rejected_association_ids": [a.association_id for a in targets]},
            events=[e.to_dict() for e in events],
        )

    def update_session_status(
        self,
        *,
        provider: str,
        native_session_id: str,
        lifecycle_status: str,
        environment_selector: str | None = None,
        apply: bool = False,
    ) -> MutationPreview:
        """Update a tracked session's lifecycle status (active|paused|completed|abandoned)."""
        self._sync_if_safe()
        norm_provider = self._validate_provider(provider)
        status_norm = lifecycle_status.strip().lower()
        if status_norm not in _VALID_LIFECYCLE:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                f"Invalid lifecycle status {lifecycle_status!r}. Expected one of: {', '.join(sorted(_VALID_LIFECYCLE))}.",
            )
        local_env = load_or_create_environment(self.home_dir, persist=apply)
        known_envs = self.materializer.list_environments()
        target_env = resolve_environment_selector(environment_selector, known_envs, local_env)
        sess = self.materializer.get_session(norm_provider, target_env.environment_id, native_session_id.strip())
        if sess is None:
            raise ContinuityError(
                ErrorCode.SESSION_NOT_FOUND,
                f"Session ({norm_provider}, {target_env.environment_id}, {native_session_id.strip()}) is not registered.",
            )
        ts = now_utc_iso()
        events = [
            EventEnvelope(
                event_id=generate_id("evt"),
                event_schema_version=SCHEMA_EVENT_VERSION,
                event_type=EventType.SESSION_STATUS_CHANGED.value,
                provider=norm_provider,
                environment_id=target_env.environment_id,
                native_session_id=sess.native_session_id,
                source_timestamp=ts,
                observed_timestamp=ts,
                source_adapter_version=ADAPTER_VERSION,
                payload={"lifecycle_status": status_norm},
            )
        ]
        if apply:
            self._emit_and_materialize(events)
        return MutationPreview(
            action="status",
            applied=apply,
            summary=(
                f"Updated session {sess.native_session_id} status to {status_norm}"
                if apply
                else f"Dry-run: would update session {sess.native_session_id} status to {status_norm}"
            ),
            details={
                "provider": norm_provider,
                "environment_id": target_env.environment_id,
                "native_session_id": sess.native_session_id,
                "lifecycle_status": status_norm,
            },
            events=[e.to_dict() for e in events],
        )

    # ------------------------------------------------------------------
    # Continuity Queries & Inbox
    # ------------------------------------------------------------------

    def find_sessions(
        self,
        *,
        workflow_identifier: str,
        provider: str | None = None,
        environment_selector: str | None = None,
        include_candidates: bool = False,
    ) -> dict[str, Any]:
        """Find sessions associated with a workflow and compute distinct continuity pointers."""
        self._sync_if_safe()
        wf = self.materializer.get_workflow(workflow_identifier)
        if wf is None:
            raise ContinuityError(ErrorCode.WORKFLOW_NOT_FOUND, f"Workflow not found: {workflow_identifier!r}")

        norm_provider = self._validate_provider(provider) if provider else None
        known_envs = {e.environment_id: e for e in self.materializer.list_environments()}
        env_filter_id: str | None = None
        if environment_selector:
            local_env = load_or_create_environment(self.home_dir, persist=False)
            resolved_env = resolve_environment_selector(environment_selector, list(known_envs.values()), local_env)
            env_filter_id = resolved_env.environment_id

        all_assocs = self.materializer.list_associations(
            workflow_id=wf.workflow_id,
            provider=norm_provider,
            environment_id=env_filter_id,
        )
        allowed_levels = {EvidenceLevel.CONFIRMED.value, EvidenceLevel.STRONG.value}
        if include_candidates:
            allowed_levels.add(EvidenceLevel.CANDIDATE.value)

        active_assocs = [
            a
            for a in all_assocs
            if a.status == AssociationStatus.ACTIVE.value and a.evidence_level in allowed_levels
        ]

        records: list[dict[str, Any]] = []
        warnings: list[str] = []
        for assoc in active_assocs:
            sess = self.materializer.get_session(assoc.provider, assoc.environment_id, assoc.native_session_id)
            if sess is None:
                continue
            env_info = known_envs.get(sess.environment_id)
            runtime_kind = env_info.runtime_kind if env_info else ""
            adapter = self.adapters.get(sess.provider)
            resume_plan: ResumePlan | None = None
            if adapter is not None:
                resume_plan = adapter.resolve_resume_command(
                    sess.native_session_id,
                    cwd=sess.cwd_native,
                    environment_id=sess.environment_id,
                    runtime_kind=runtime_kind,
                )
            records.append(
                {
                    "session": sess.to_dict(),
                    "association": assoc.to_dict(),
                    "environment": env_info.to_dict() if env_info else {"environment_id": sess.environment_id},
                    "resume": resume_plan.to_dict() if resume_plan else None,
                }
            )

        # Conflict / candidate warnings for this workflow
        conflicts = [a for a in all_assocs if a.status == AssociationStatus.CONFLICT.value]
        candidates = [
            a
            for a in all_assocs
            if a.status == AssociationStatus.ACTIVE.value and a.evidence_level == EvidenceLevel.CANDIDATE.value
        ]
        if conflicts:
            warnings.append(f"{len(conflicts)} conflicting association(s) require review (`agents inbox`).")
        if candidates and not include_candidates:
            warnings.append(f"{len(candidates)} candidate association(s) awaiting confirmation (`agents inbox`).")

        def _pick_latest(key_fn) -> dict[str, Any] | None:
            eligible = [(key_fn(r["session"]), r) for r in records if key_fn(r["session"])]
            if not eligible:
                return None
            eligible.sort(key=lambda item: item[0], reverse=True)
            top = eligible[0][1]
            return {
                "provider": top["session"]["provider"],
                "environment_id": top["session"]["environment_id"],
                "native_session_id": top["session"]["native_session_id"],
                "timestamp": eligible[0][0],
            }

        latest_by_provider: dict[str, Any] = {}
        for p in sorted(_VALID_PROVIDERS):
            sub = [r for r in records if r["session"]["provider"] == p]
            if sub:
                sub.sort(
                    key=lambda r: (
                        r["session"]["last_completed_turn_at"]
                        or r["session"]["last_turn_at"]
                        or r["session"]["last_seen_at"]
                        or r["session"]["first_observed_at"]
                    ),
                    reverse=True,
                )
                top = sub[0]
                latest_by_provider[p] = {
                    "provider": p,
                    "environment_id": top["session"]["environment_id"],
                    "native_session_id": top["session"]["native_session_id"],
                    "last_seen_at": top["session"]["last_seen_at"],
                    "last_turn_at": top["session"]["last_turn_at"],
                }

        continuity = {
            "latest_created": _pick_latest(lambda s: s["created_at"]),
            "latest_seen": _pick_latest(lambda s: s["last_seen_at"] or s["first_observed_at"]),
            "latest_turn": _pick_latest(lambda s: s["last_turn_at"]),
            "latest_completed_turn": _pick_latest(lambda s: s["last_completed_turn_at"]),
            "latest_by_provider": latest_by_provider,
            "latest_reported_summary": None,
            "latest_validated_checkpoint": None,
        }

        return {
            "workflow": wf.to_dict(),
            "sessions": records,
            "continuity": continuity,
            "warnings": warnings,
        }

    def list_inbox(
        self,
        *,
        workflow_identifier: str | None = None,
        provider: str | None = None,
        environment_selector: str | None = None,
    ) -> dict[str, Any]:
        """List unlinked sessions, candidate associations, and association conflicts."""
        self._sync_if_safe()
        wf_filter: str | None = None
        if workflow_identifier:
            wf = self.materializer.get_workflow(workflow_identifier)
            if wf is None:
                raise ContinuityError(ErrorCode.WORKFLOW_NOT_FOUND, f"Workflow not found: {workflow_identifier!r}")
            wf_filter = wf.workflow_id

        norm_provider = self._validate_provider(provider) if provider else None
        known_envs = {e.environment_id: e for e in self.materializer.list_environments()}
        env_filter_id: str | None = None
        if environment_selector:
            local_env = load_or_create_environment(self.home_dir, persist=False)
            env_filter_id = resolve_environment_selector(
                environment_selector, list(known_envs.values()), local_env
            ).environment_id

        sessions = self.materializer.list_sessions(provider=norm_provider, environment_id=env_filter_id)
        all_assocs = self.materializer.list_associations(provider=norm_provider, environment_id=env_filter_id)

        by_session: dict[tuple[str, str, str], list[AssociationRecord]] = {}
        for a in all_assocs:
            by_session.setdefault((a.provider, a.environment_id, a.native_session_id), []).append(a)

        unlinked: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []

        for s in sessions:
            key = (s.provider, s.environment_id, s.native_session_id)
            s_assocs = by_session.get(key, [])
            active_confirmed = [
                a
                for a in s_assocs
                if a.status == AssociationStatus.ACTIVE.value
                and a.evidence_level in (EvidenceLevel.CONFIRMED.value, EvidenceLevel.STRONG.value)
            ]
            if not active_confirmed and not wf_filter:
                unlinked.append(s.to_dict())

        for a in all_assocs:
            if wf_filter and a.workflow_id != wf_filter:
                continue
            if a.status == AssociationStatus.CONFLICT.value:
                conflicts.append(a.to_dict())
            elif a.status == AssociationStatus.ACTIVE.value and a.evidence_level == EvidenceLevel.CANDIDATE.value:
                candidates.append(a.to_dict())

        return {
            "unlinked_sessions": unlinked,
            "candidate_associations": candidates,
            "conflict_associations": conflicts,
        }

    def discover_native_sessions(
        self,
        *,
        provider: str | None = None,
        limit: int = 50,
        apply: bool = False,
    ) -> dict[str, Any]:
        """Discover native sessions read-only from installed providers and optionally register new ones."""
        self._sync_if_safe()
        targets = [self._validate_provider(provider)] if provider else sorted(_VALID_PROVIDERS)
        local_env = load_or_create_environment(self.home_dir, persist=apply)
        known_envs = self.materializer.list_environments()

        discovered: list[dict[str, Any]] = []
        new_events: list[EventEnvelope] = []
        ts = now_utc_iso()

        for p_name in targets:
            adapter = self.adapters.get(p_name)
            if adapter is None:
                continue
            for item in adapter.discover_sessions(limit=limit):
                sid = str(item.get("native_session_id") or "").strip()
                if not sid:
                    continue
                existing = self.materializer.get_session(p_name, local_env.environment_id, sid)
                is_new = existing is None
                discovered.append({**item, "environment_id": local_env.environment_id, "already_tracked": not is_new})
                if is_new:
                    new_events.append(
                        EventEnvelope(
                            event_id=generate_id("evt"),
                            event_schema_version=SCHEMA_EVENT_VERSION,
                            event_type=EventType.SESSION_REGISTERED.value,
                            provider=p_name,
                            environment_id=local_env.environment_id,
                            native_session_id=sid,
                            source_timestamp=item.get("last_seen_at") or ts,
                            observed_timestamp=ts,
                            source_adapter_version=ADAPTER_VERSION,
                            payload={
                                "environment": local_env.to_dict(),
                                "cwd_native": item.get("cwd"),
                                "cwd_canonical": normalize_path_canonical(item.get("cwd")),
                                "repository_identity": normalize_repo_identity(item.get("cwd")),
                                "native_title": item.get("native_title"),
                                "native_created_at": item.get("native_created_at"),
                                "first_observed_at": ts,
                                "last_seen_at": item.get("last_seen_at") or ts,
                                "last_turn_at": item.get("last_turn_at"),
                                "parent_session_id": item.get("parent_session_id"),
                                "surface": item.get("surface"),
                                "native_version": item.get("native_version"),
                                "metadata_source": item.get("metadata_source", "native_discovery"),
                            },
                        )
                    )

        if apply and new_events:
            env_events = self._ensure_environment_event(local_env, known_envs, ts)
            self._emit_and_materialize(env_events + new_events)

        return {
            "action": "discover",
            "applied": apply,
            "discovered_count": len(discovered),
            "new_sessions_count": len(new_events),
            "sessions": discovered,
            "summary": (
                f"Registered {len(new_events)} new native session(s) out of {len(discovered)} discovered."
                if apply
                else f"Dry-run: discovered {len(discovered)} native session(s) ({len(new_events)} new)."
            ),
        }

    # ------------------------------------------------------------------
    # Rebuild & Diagnostics
    # ------------------------------------------------------------------

    def rebuild_index(self, *, apply: bool = False) -> dict[str, Any]:
        """Preview or execute a full atomic rebuild of index.sqlite from durable events."""
        assert_sqlite_writer_allowed(self.materializer.db_path, allow_unsafe_cross_os=self.allow_unsafe_cross_os)
        roots = discover_spool_roots(self.home_dir)
        scan = read_spool_events(roots, optional_roots={self.home_dir / "events"})
        if not apply:
            return {
                "action": "rebuild",
                "applied": False,
                "summary": f"Dry-run: would replay {len(scan.records)} valid event(s) into {self.materializer.db_path}",
                "spool_roots": [str(r) for r in roots],
                "valid_events": len(scan.records),
                "issues": [{"file_path": i.file_path, "reason": i.reason} for i in scan.issues],
                "db_path": str(self.materializer.db_path),
            }
        res = self.materializer.rebuild_from_spools()
        out = res.to_dict()
        out["action"] = "rebuild"
        out["applied"] = True
        out["summary"] = (
            f"Rebuilt {res.db_path} from {res.total_spool_events} spool event(s) "
            f"({res.ingested_count} applied, {len(res.issues)} issue(s))."
        )
        return out

    def diagnose(self) -> dict[str, Any]:
        """Collect read-only diagnostic state across storage, environment, and providers."""
        local_env = load_or_create_environment(self.home_dir, persist=False)
        spool_roots = discover_spool_roots(self.home_dir)
        scan = read_spool_events(spool_roots, optional_roots={self.home_dir / "events"})
        db_snap = self.materializer.get_diagnostics_snapshot()
        can_write = self._can_write_sqlite()

        providers_report: dict[str, Any] = {}
        for name, adapter in sorted(self.adapters.items()):
            providers_report[name] = adapter.get_health_status().to_dict()

        status = "ok"
        warnings: list[str] = []
        if scan.issues:
            status = "degraded"
            warnings.append(f"{len(scan.issues)} corrupt or unreadable event spool file(s) detected.")
        if not can_write:
            warnings.append("WSL2 runtime is observing a Windows-mounted SQLite path; direct SQLite writes are disabled.")
        if db_snap["db_exists"] and db_snap["integrity"] != "ok":
            status = "error"
            warnings.append(f"SQLite integrity check returned: {db_snap['integrity']}. Run `agents rebuild -a`.")

        return {
            "status": status,
            "home_dir": str(self.home_dir),
            "runtime_kind": detect_runtime_kind(),
            "environment": local_env.to_dict(),
            "sqlite_writer_allowed": can_write,
            "database": db_snap,
            "spools": {
                "roots": [str(r) for r in spool_roots],
                "valid_event_count": len(scan.records),
                "issue_count": len(scan.issues),
                "issues": [{"file_path": i.file_path, "reason": i.reason} for i in scan.issues],
            },
            "providers": providers_report,
            "warnings": warnings,
        }
