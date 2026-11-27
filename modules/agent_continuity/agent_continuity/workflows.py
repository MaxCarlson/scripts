"""Prepared workflow discovery, additive init, authoritative runtime identity, handoff validation, and activity reconciliation (LLMD-50..54)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class WorkflowResourceBridge(Protocol):
    """Read-only workflow-instructions/v1 bridge contract."""

    def list_resources(self, provider: str, runtime: str) -> Sequence[Mapping[str, Any]]: ...

    def read_resource(self, resource_id: str, revision: str | None = None) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class ResourceStatus:
    resource_id: str
    revision: str
    digest: str
    provider: str
    runtime: str
    status: str  # available | missing | changed | unsupported | unavailable
    installed: bool
    callable: bool
    runtime_verified: bool
    detail: str | None = None


def discover_workflow_resources(
    bridge: WorkflowResourceBridge | None,
    *,
    provider: str,
    runtime: str,
    expected_digests: Mapping[str, str] | None = None,
) -> list[ResourceStatus]:
    """LLMD-50: Discover workflow instruction resources without mutating global config or installing hooks."""
    if bridge is None:
        return [
            ResourceStatus(
                resource_id="<bridge>",
                revision="",
                digest="",
                provider=provider,
                runtime=runtime,
                status="unavailable",
                installed=False,
                callable=False,
                runtime_verified=False,
                detail="workflow-instructions/v1 bridge is unavailable",
            )
        ]
    try:
        descriptors = list(bridge.list_resources(provider, runtime))
    except Exception as exc:
        return [
            ResourceStatus(
                resource_id="<bridge>",
                revision="",
                digest="",
                provider=provider,
                runtime=runtime,
                status="unavailable",
                installed=False,
                callable=False,
                runtime_verified=False,
                detail=f"bridge error: {type(exc).__name__}",
            )
        ]
    results: list[ResourceStatus] = []
    for item in descriptors:
        rid = str(item.get("resource_id") or "")
        rev = str(item.get("revision") or "")
        digest = str(item.get("digest") or "")
        installed = bool(item.get("installed", False))
        callable_flag = bool(item.get("callable", False))
        verified = bool(item.get("runtime_verified", False))
        supported = bool(item.get("supported", True))
        if not supported:
            status = "unsupported"
        elif not installed:
            status = "missing"
        elif expected_digests and rid in expected_digests and expected_digests[rid] != digest:
            status = "changed"
        elif not callable_flag:
            status = "unavailable"
        else:
            status = "available"
        results.append(
            ResourceStatus(
                resource_id=rid,
                revision=rev,
                digest=digest,
                provider=provider,
                runtime=runtime,
                status=status,
                installed=installed,
                callable=callable_flag,
                runtime_verified=verified,
                detail=item.get("detail"),
            )
        )
    return results


def prepare_additive_workflow_init(
    *,
    provider: str,
    runtime: str,
    is_new_session: bool,
    resources: Sequence[ResourceStatus],
    custom_instruction_path: str | None = None,
    supported_providers: frozenset[str] = frozenset({"codex", "agy", "claude"}),
) -> dict[str, Any]:
    """LLMD-51: Prepare one-time additive workflow provenance for new native sessions only."""
    if not is_new_session:
        return {"applied": False, "reason": "resume_never_replays_init", "provenance": []}
    if provider not in supported_providers:
        return {
            "applied": False,
            "status": "unsupported",
            "reason": f"provider {provider!r} does not support additive workflow initialization",
            "provenance": [],
        }
    provenance = [
        {"resource_id": r.resource_id, "revision": r.revision, "digest": r.digest, "status": r.status}
        for r in resources
        if r.status == "available"
    ]
    blocked = [
        {"resource_id": r.resource_id, "status": r.status, "detail": r.detail}
        for r in resources
        if r.status in {"missing", "changed", "unsupported", "unavailable"}
    ]
    return {
        "applied": bool(provenance or custom_instruction_path),
        "status": "degraded" if blocked else "ready",
        "provider": provider,
        "runtime": runtime,
        "custom_instruction_path": custom_instruction_path,
        "provenance": provenance,
        "limitations": blocked,
    }


def resolve_authoritative_runtime_identity(
    *,
    trusted_slot: Mapping[str, Any] | None,
    trusted_observation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """LLMD-52: Resolve authoritative runtime identity from trusted metadata, never prompt/handoff text."""
    if trusted_slot is None and trusted_observation is None:
        return {"authority": "unavailable", "gui_alias": None, "agent_name": None, "slot_id": None}
    if trusted_slot is None:
        return {"authority": "unmanaged", "gui_alias": None, "agent_name": None, "slot_id": None}
    if trusted_observation and trusted_observation.get("conflict"):
        return {
            "authority": "contradictory",
            "gui_alias": trusted_slot.get("gui_alias"),
            "agent_name": trusted_slot.get("name"),
            "slot_id": trusted_slot.get("slot_id"),
        }
    return {
        "authority": "managed",
        "gui_alias": trusted_slot.get("gui_alias"),
        "agent_name": trusted_slot.get("name"),
        "slot_id": trusted_slot.get("slot_id"),
    }


_RECIPIENT_HEADER_RE = re.compile(r"^\s*To-Agent\s*:\s*(.+?)\s*$", re.IGNORECASE)
_AGENT_HEADER_RE = re.compile(r"^\s*Agent\s*:\s*(?:#(\d+)\s*[—–-]\s*)?(.+?)\s*$", re.IGNORECASE)


def validate_addressed_handoff(
    text: str,
    *,
    authoritative_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """LLMD-53: Validate addressed handoff recipient deterministically, ignoring code fences and blockquotes."""
    authority = authoritative_identity.get("authority")
    if authority in {"unavailable", "unmanaged", "contradictory"}:
        return {"valid": False, "outcome": authority, "recipients": []}

    parsed: list[tuple[int | None, str]] = []
    in_fence = False
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or stripped.startswith(">"):
            continue
        agent_match = _AGENT_HEADER_RE.match(raw_line)
        if agent_match:
            num = int(agent_match.group(1)) if agent_match.group(1) is not None else None
            parsed.append((num, agent_match.group(2).strip()))
            continue
        match = _RECIPIENT_HEADER_RE.match(raw_line)
        if match:
            parsed.append((None, match.group(1).strip()))

    unique = list(dict.fromkeys(parsed))
    recipients = [name for _, name in unique]
    if not unique:
        return {"valid": False, "outcome": "unaddressed", "recipients": []}
    if len(unique) > 1:
        return {"valid": False, "outcome": "contradictory_headers", "recipients": recipients}

    header_num, recipient = unique[0]
    expected_name = str(authoritative_identity.get("agent_name") or "")
    expected_num = authoritative_identity.get("agent_number")
    if header_num is not None and expected_num is not None and header_num != int(expected_num):
        return {"valid": False, "outcome": "mismatch", "recipients": recipients, "expected": expected_name}
    if recipient != expected_name:
        return {"valid": False, "outcome": "mismatch", "recipients": recipients, "expected": expected_name}
    return {"valid": True, "outcome": "matched", "recipients": recipients}


def reconcile_activity_and_associations(
    events: Iterable[Mapping[str, Any]],
    *,
    provider_evidence: Mapping[tuple[str, str, str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """LLMD-54: Reconcile exact session selections from immutable events without letting late observations win."""
    ordered = sorted(
        events,
        key=lambda ev: (
            str(ev.get("source_timestamp") or ev.get("observed_timestamp") or ""),
            int(ev.get("sequence") or 0),
            str(ev.get("event_id") or ""),
        ),
    )
    selected_by_slot: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    duplicates = 0
    for ev in ordered:
        eid = str(ev.get("event_id") or "")
        if eid and eid in seen_ids:
            duplicates += 1
            continue
        if eid:
            seen_ids.add(eid)
        slot_id = str(ev.get("slot_id") or "")
        if not slot_id:
            continue
        ts = str(ev.get("source_timestamp") or ev.get("observed_timestamp") or "")
        seq = int(ev.get("sequence") or 0)
        key = (ts, seq, eid)
        prev = selected_by_slot.get(slot_id)
        if prev is not None and prev["_order_key"] > key:
            continue
        identity = (str(ev.get("provider") or ""), str(ev.get("environment_id") or ""), str(ev.get("native_session_id") or ""))
        ev_status = "unknown"
        if provider_evidence is not None:
            meta = provider_evidence.get(identity)
            ev_status = "verified" if meta else "unknown"
        selected_by_slot[slot_id] = {
            "slot_id": slot_id,
            "provider": identity[0],
            "environment_id": identity[1],
            "native_session_id": identity[2],
            "evidence_status": ev_status,
            "_order_key": key,
        }
    for row in selected_by_slot.values():
        row.pop("_order_key", None)
    return {
        "selections": selected_by_slot,
        "duplicates_skipped": duplicates,
        "fingerprint": hashlib.sha256(str(sorted(seen_ids)).encode()).hexdigest()[:16],
    }
