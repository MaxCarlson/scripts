"""Provider-neutral launch-context normalization and destination preview."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ContextItem:
    key: str
    value: Any
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class PortableLaunchContext:
    repositories: tuple[Mapping[str, Any], ...] = ()
    working_directory: str | None = None
    explicit_directory_override: str | None = None
    authorized_directories: tuple[str, ...] = ()
    runtime_identity: Mapping[str, Any] = field(default_factory=dict)
    workflow_type: str | None = None
    logical_agent_identity: str | None = None
    terminal_settings: Mapping[str, Any] = field(default_factory=dict)
    instructions: str | None = None
    semantic_settings: Mapping[str, Any] = field(default_factory=dict)
    destination_preferences: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


_PERMISSION_RANK = {"read-only": 0, "workspace-write": 1, "full-access": 2}
def resolve_portable_launch_context(
    source: Mapping[str, Any], destination_provider: str, *,
    capabilities: Mapping[str, set[str] | frozenset[str]] | None = None,
    destination_runtime: Mapping[str, Any] | None = None,
) -> tuple[PortableLaunchContext, list[ContextItem]]:
    """Normalize safe context while retaining unsupported/conflicting items in preview."""
    provider = destination_provider.casefold()
    supported = (capabilities or {}).get(provider, frozenset())
    context = PortableLaunchContext(
        repositories=tuple(source.get("repositories", ())),
        working_directory=source.get("working_directory"),
        explicit_directory_override=source.get("explicit_directory_override"),
        authorized_directories=tuple(source.get("authorized_directories", ())),
        runtime_identity=dict(source.get("runtime_identity", {})),
        workflow_type=source.get("workflow_type"),
        logical_agent_identity=source.get("logical_agent_identity"),
        terminal_settings=dict(source.get("terminal_settings", {})),
        instructions=source.get("instructions"),
        semantic_settings=dict(source.get("semantic_settings", {})),
        destination_preferences=dict(source.get("destination_preferences", {})),
    )
    items: list[ContextItem] = []
    for repo in context.repositories:
        path = repo.get("worktree") or repo.get("root")
        if path and not Path(str(path)).is_dir():
            items.append(ContextItem("repository", dict(repo), "conflicting", "Recorded repository/worktree path is missing."))
        else:
            items.append(ContextItem("repository", dict(repo), "preserved"))
    for directory in context.authorized_directories:
        status = "preserved" if Path(directory).is_dir() else "conflicting"
        reason = None if status == "preserved" else "Authorized directory is missing; it will not be substituted."
        items.append(ContextItem("authorized_directory", directory, status, reason))
    for key, value in context.semantic_settings.items():
        if key not in supported:
            items.append(ContextItem(key, value, "unsupported", "Destination capability is not verified."))
            continue
        if key == "filesystem" and isinstance(value, str) and value in _PERMISSION_RANK:
            target = source.get("destination_filesystem")
            if isinstance(target, str) and target in _PERMISSION_RANK and _PERMISSION_RANK[target] > _PERMISSION_RANK[value]:
                items.append(ContextItem(key, value, "conflicting", "Destination permission would broaden filesystem access."))
                continue
        items.append(ContextItem(key, value, "translated" if source.get("provider") != provider else "preserved"))
    if context.working_directory:
        if not Path(context.working_directory).is_dir():
            items.append(ContextItem("working_directory", context.working_directory, "conflicting", "Working directory is missing; no substitute will be used."))
        else:
            items.append(ContextItem("working_directory", context.working_directory, "preserved"))
    if destination_runtime and context.runtime_identity:
        for key in ("runtime_kind", "distro", "environment_id"):
            expected = context.runtime_identity.get(key)
            actual = destination_runtime.get(key)
            if expected is not None and actual is not None and expected != actual:
                items.append(ContextItem("runtime_identity", dict(context.runtime_identity), "conflicting", f"Destination {key} differs from source identity."))
                break
        else:
            items.append(ContextItem("runtime_identity", dict(context.runtime_identity), "preserved"))
    if context.instructions:
        items.append(ContextItem("instructions", context.instructions, "preserved"))
    if context.destination_preferences.get(provider):
        items.append(ContextItem("destination_preferences", dict(context.destination_preferences[provider]), "restored"))
    return context, items
