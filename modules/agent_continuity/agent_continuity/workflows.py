"""Prepared workflow discovery, additive init, authoritative runtime identity, handoff validation, and activity reconciliation (LLMD-50..54)."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class WorkflowResourceBridge(Protocol):
    """Read-only workflow-instructions/v1 bridge contract."""

    def list_resources(
        self, provider: str, runtime: str, *, selection: str = "standard"
    ) -> Sequence[Mapping[str, Any]]: ...

    def read_resource(
        self, resource_id: str, revision: str | None = None, *, selection: str = "standard"
    ) -> Mapping[str, Any] | None: ...


class LocalAgentBridgeWorkflowAdapter:
    """Lazy read-only adapter to ``local_agent_bridge.workflow_resources``."""

    def __init__(self, *, supported_providers: frozenset[str] = frozenset({"codex", "agy"})) -> None:
        self.supported_providers = supported_providers

    def list_resources(
        self, provider: str, runtime: str, *, selection: str = "standard"
    ) -> list[dict[str, Any]]:
        from local_agent_bridge.workflow_resources import resolve_workflow_resources

        payload = resolve_workflow_resources(selection)
        if payload.get("schema_version") != 1 or payload.get("selection") != selection:
            raise ValueError("local_agent_bridge returned an unsupported workflow resource schema or selection")
        entries = payload.get("resources")
        if not isinstance(entries, list):
            raise ValueError("local_agent_bridge schema-v1 resources must be an ordered list")
        supported = provider in self.supported_providers and runtime in {"windows", "wsl", "linux", "macos"}
        items: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ValueError("local_agent_bridge schema-v1 resource must be an object")
            resource_id, content, digest = entry.get("id"), entry.get("content"), entry.get("sha256")
            if not all(isinstance(value, str) for value in (resource_id, content, digest)):
                raise ValueError("local_agent_bridge schema-v1 resource requires string id, content, and sha256")
            actual_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            digest_ok = bool(digest) and actual_digest == digest
            items.append(
                {
                    "schema_version": 1,
                    "selection": selection,
                    "resource_id": resource_id,
                    "revision": digest[:12],
                    "digest": digest if digest_ok else actual_digest,
                    "path": str(entry.get("path") or ""),
                    "content": content if digest_ok else None,
                    "installed": digest_ok,
                    "callable": digest_ok,
                    # Resolver integrity and provider runtime loading are distinct evidence.
                    "runtime_verified": False,
                    "supported": supported,
                    "detail": None if digest_ok else "resource digest mismatch",
                }
            )
        return items

    def read_resource(
        self, resource_id: str, revision: str | None = None, *, selection: str = "standard"
    ) -> dict[str, Any] | None:
        for item in self.list_resources("codex", "windows", selection=selection):
            if item["resource_id"] == resource_id and (revision is None or item["revision"] == revision):
                return item
        return None


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
    content: str | None = None
    path: str | None = None


def discover_workflow_resources(
    bridge: WorkflowResourceBridge | None,
    *,
    provider: str,
    runtime: str,
    selection: str = "standard",
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
        descriptors = list(bridge.list_resources(provider, runtime, selection=selection))
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
        content = item.get("content")
        if content is None and hasattr(bridge, "read_resource") and installed and callable_flag and supported:
            try:
                snap = bridge.read_resource(rid, rev or None, selection=selection)
                if snap and snap.get("content") is not None:
                    content = str(snap["content"])
                    snap_digest = str(snap.get("digest") or digest)
                    if snap_digest and hashlib.sha256(content.encode("utf-8")).hexdigest() != snap_digest:
                        content = None
                        installed = False
            except Exception:
                content = None
        if content is not None and digest:
            actual_digest = hashlib.sha256(str(content).encode("utf-8")).hexdigest()
            if actual_digest != digest:
                content = None
                installed = False
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
                content=str(content) if content is not None else None,
                path=str(item.get("path")) if item.get("path") is not None else None,
            )
        )
    return results


def prepare_additive_workflow_init(
    *,
    provider: str,
    runtime: str,
    is_new_session: bool,
    resources: Sequence[ResourceStatus],
    selection: str | None = "standard",
    custom_instruction_path: str | None = None,
    custom_instruction_paths: Sequence[str] = (),
    effective_cwd: str | None = None,
    expected_digests: Mapping[str, str] | None = None,
    allow_replacement: bool = False,
    supported_providers: frozenset[str] = frozenset({"codex", "agy"}),
) -> dict[str, Any]:
    """LLMD-51: Prepare one-time additive workflow provenance and prompt for new native sessions only."""
    if not is_new_session:
        return {
            "applied": False,
            "status": "skipped_resume",
            "reason": "resume_never_replays_init",
            "provider_qualified": False,
            "provider_behavior_observed": False,
            "provider_snapshot_status": "not_observable",
            "prompt_submitted": False,
            "delivery_confirmed": False,
            "provenance": [],
            "resource_snapshot": None,
            "delivery_prompt": None,
        }
    requested_custom_paths = list(custom_instruction_paths)
    if custom_instruction_path and custom_instruction_path not in requested_custom_paths:
        requested_custom_paths.append(custom_instruction_path)
    if selection is None and not requested_custom_paths:
        return {
            "applied": False,
            "status": "untyped_legacy",
            "reason": "untyped legacy slot retains existing initialization behavior",
            "provider_qualified": False,
            "provider_behavior_observed": False,
            "provider_snapshot_status": "not_observable",
            "prompt_submitted": False,
            "delivery_confirmed": False,
            "provenance": [],
            "resource_snapshot": None,
            "delivery_prompt": None,
        }
    effective_selection = selection or "standard"
    if provider not in supported_providers:
        return {
            "applied": False,
            "status": "unsupported",
            "reason": f"provider {provider!r} has no qualified additive workflow initialization surface",
            "provider_qualified": False,
            "provider_behavior_observed": False,
            "provider_snapshot_status": "unsupported",
            "prompt_submitted": False,
            "delivery_confirmed": False,
            "provenance": [],
            "resource_snapshot": None,
            "delivery_prompt": None,
        }
    provenance: list[dict[str, Any]] = []
    prompt_parts: list[str] = []
    blocked: list[dict[str, Any]] = []
    by_id: dict[str, list[ResourceStatus]] = {}
    for resource in resources:
        by_id.setdefault(resource.resource_id, []).append(resource)
    deduplicated: list[ResourceStatus] = []
    for resource_id, candidates in by_id.items():
        digests = {candidate.digest for candidate in candidates}
        if len(digests) > 1:
            blocked.append({
                "resource_id": resource_id,
                "status": "conflicting",
                "detail": "duplicate resource identity has different content digests",
            })
            continue
        deduplicated.append(candidates[0])
    for r in deduplicated:
        if r.status != "available":
            if r.status in {"missing", "changed", "unsupported", "unavailable"}:
                blocked.append({"resource_id": r.resource_id, "status": r.status, "detail": r.detail})
            continue
        if r.content is None:
            blocked.append(
                {
                    "resource_id": r.resource_id,
                    "status": "unavailable",
                    "detail": "resource metadata was present without verifiable content",
                }
            )
            continue
        entry: dict[str, Any] = {
            "resource_id": r.resource_id,
            "revision": r.revision,
            "digest": r.digest,
            "status": r.status,
            "selection": effective_selection,
            "integrity_verified": True,
            "installed": r.installed,
            "callable": r.callable,
        }
        if r.path:
            entry["path"] = r.path
        provenance.append(entry)
        prompt_parts.append(f"[{r.resource_id}@{r.revision}]\n{r.content}")
    custom_snapshot_paths: set[str] = set()
    base_dir = Path(effective_cwd).resolve() if effective_cwd else Path.cwd()
    for requested_path in requested_custom_paths:
        raw_path = Path(requested_path)
        custom_file = (raw_path if raw_path.is_absolute() else base_dir / raw_path).resolve()
        canonical_path = (
            str(custom_file) if runtime in {"wsl", "linux", "macos"} else os.path.normcase(str(custom_file))
        )
        custom_resource_id = "custom:" + hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()
        if canonical_path in custom_snapshot_paths:
            continue
        custom_snapshot_paths.add(canonical_path)
        try:
            if not custom_file.is_file():
                raise FileNotFoundError(str(custom_file))
            raw = custom_file.read_bytes()
            content = raw.decode("utf-8")
        except FileNotFoundError:
            blocked.append({
                "resource_id": custom_resource_id,
                "path": str(custom_file),
                "status": "missing",
                "detail": "custom instruction file does not exist",
            })
            continue
        except (OSError, UnicodeError) as exc:
            blocked.append({
                "resource_id": custom_resource_id,
                "path": str(custom_file),
                "status": "unavailable",
                "detail": f"custom instruction file cannot be read as UTF-8 ({type(exc).__name__})",
            })
            continue
        custom_digest = hashlib.sha256(raw).hexdigest()
        legacy_resource_id = f"custom:{custom_file.name}"
        expected_digest = (expected_digests or {}).get(custom_resource_id)
        if expected_digest is None:
            expected_digest = (expected_digests or {}).get(legacy_resource_id)
        if expected_digest is not None and expected_digest != custom_digest and not allow_replacement:
            blocked.append({
                "resource_id": custom_resource_id,
                "path": str(custom_file),
                "status": "changed",
                "detail": "custom instruction file bytes differ from the selected session snapshot",
            })
            continue
        provenance.append(
            {
                "resource_id": custom_resource_id,
                "revision": custom_digest[:12],
                "digest": custom_digest,
                "status": "available",
                "selection": effective_selection,
                "integrity_verified": True,
                "installed": True,
                "callable": True,
                "path": str(custom_file),
            }
        )
        prompt_parts.append(f"[{custom_resource_id}@{custom_digest[:12]}]\n{content}")
    # A requested resource that is missing, changed, or unreadable blocks the full
    # additive payload; silently submitting only a subset would change instructions.
    delivery_prompt = "\n\n".join(prompt_parts) if prompt_parts and not blocked else None
    resource_snapshot = {
        "schema_version": 2,
        "selection": effective_selection,
        "resources": [
            {
                **{"id": entry["resource_id"], "revision": entry["revision"], "sha256": entry["digest"]},
                **({"kind": "custom_file"} if entry.get("path") else {}),
                **({"path": entry["path"]} if entry.get("path") else {}),
            }
            for entry in provenance
        ],
    }
    return {
        "applied": bool(provenance and delivery_prompt),
        "status": "degraded" if blocked else ("ready" if provenance else "unavailable"),
        "selection": effective_selection,
        "provider": provider,
        "runtime": runtime,
        "provider_qualified": False,
        "delivery_capability": f"{provider}_bootstrap_prompt" if provider in supported_providers else None,
        "provider_behavior_observed": False,
        "provider_snapshot_status": "prompt_submitted; effective-loaded-context-unverified",
        "prompt_submitted": False,
        "delivery_confirmed": False,
        "custom_instruction_path": requested_custom_paths[0] if len(requested_custom_paths) == 1 else None,
        "custom_instruction_paths": [str(Path(path).resolve() if Path(path).is_absolute()
                                          else (base_dir / path).resolve()) for path in requested_custom_paths],
        "provenance": provenance,
        "resource_snapshot": resource_snapshot,
        "limitations": blocked,
        "delivery_prompt": delivery_prompt,
    }


def preview_custom_instruction_paths(
    paths: Sequence[str], *, effective_cwd: str | None, runtime: str,
) -> list[dict[str, Any]]:
    """Inspect custom instruction sources without returning or persisting their contents."""
    base_dir = Path(effective_cwd).resolve() if effective_cwd else Path.cwd()
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for requested_path in paths:
        raw_path = Path(requested_path)
        path = (raw_path if raw_path.is_absolute() else base_dir / raw_path).resolve()
        canonical_path = (
            str(path) if runtime in {"wsl", "linux", "macos"} else os.path.normcase(str(path))
        )
        resource_id = "custom:" + hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()
        if canonical_path in seen:
            continue
        seen.add(canonical_path)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            results.append({"id": resource_id, "path": str(path), "status": "missing"})
        except OSError:
            results.append({"id": resource_id, "path": str(path), "status": "unavailable"})
        else:
            results.append({
                "id": resource_id,
                "path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "status": "available",
            })
    return results


def resolve_authoritative_runtime_identity(
    *,
    trusted_slot: Mapping[str, Any] | None,
    trusted_observation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """LLMD-52: Resolve authoritative runtime identity from trusted metadata, never prompt/handoff text."""
    if trusted_slot is None and trusted_observation is None:
        return {"authority": "unavailable", "gui_alias": None, "agent_name": None, "slot_id": None, "agent_number": None}
    if trusted_slot is None:
        return {"authority": "unmanaged", "gui_alias": None, "agent_name": None, "slot_id": None, "agent_number": None}
    if trusted_observation is None:
        return {
            "authority": "unavailable",
            "gui_alias": trusted_slot.get("gui_alias"),
            "agent_name": trusted_slot.get("name"),
            "slot_id": trusted_slot.get("slot_id"),
            "agent_number": trusted_slot.get("agent_number"),
        }
    obs_management = str(trusted_observation.get("management") or "managed")
    obs_slot_id = trusted_observation.get("slot_id")
    obs_num = trusted_observation.get("agent_number")
    obs_name = trusted_observation.get("agent_name")
    obs_session = trusted_observation.get("native_session_id")
    current = trusted_slot.get("current") or {}
    slot_session = current.get("native_session_id")
    contradiction = bool(trusted_observation.get("conflict")) or obs_management == "conflict"
    if obs_slot_id is not None and obs_slot_id != trusted_slot.get("slot_id"):
        contradiction = True
    if obs_num is not None and trusted_slot.get("agent_number") is not None and int(obs_num) != int(trusted_slot["agent_number"]):
        contradiction = True
    if obs_name is not None and obs_name != trusted_slot.get("name"):
        contradiction = True
    if obs_session is not None and slot_session is not None and obs_session != slot_session:
        contradiction = True
    if contradiction:
        return {
            "authority": "contradictory",
            "gui_alias": trusted_slot.get("gui_alias"),
            "agent_name": trusted_slot.get("name"),
            "slot_id": trusted_slot.get("slot_id"),
            "agent_number": trusted_slot.get("agent_number"),
        }
    if obs_management == "unmanaged":
        return {
            "authority": "unmanaged",
            "gui_alias": trusted_slot.get("gui_alias"),
            "agent_name": trusted_slot.get("name"),
            "slot_id": trusted_slot.get("slot_id"),
            "agent_number": trusted_slot.get("agent_number"),
        }
    if obs_management != "managed":
        return {
            "authority": "unavailable",
            "gui_alias": trusted_slot.get("gui_alias"),
            "agent_name": trusted_slot.get("name"),
            "slot_id": trusted_slot.get("slot_id"),
            "agent_number": trusted_slot.get("agent_number"),
        }
    return {
        "authority": "managed",
        "gui_alias": trusted_slot.get("gui_alias"),
        "agent_name": trusted_slot.get("name"),
        "slot_id": trusted_slot.get("slot_id"),
        "agent_number": trusted_slot.get("agent_number"),
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
    if header_num is not None:
        if expected_num is None:
            return {"valid": False, "outcome": "unverified_number", "recipients": recipients, "expected": expected_name}
        if header_num != int(expected_num):
            return {"valid": False, "outcome": "mismatch", "recipients": recipients, "expected": expected_name}
    if recipient != expected_name:
        return {"valid": False, "outcome": "mismatch", "recipients": recipients, "expected": expected_name}
    return {"valid": True, "outcome": "matched", "recipients": recipients, "agent_number": expected_num}


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
