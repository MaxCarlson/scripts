"""Provider-neutral launch-context normalization and destination preview."""

from __future__ import annotations

import json
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
    provider: str | None = None
    repositories: tuple[Mapping[str, Any], ...] = ()
    working_directory: str | None = None
    explicit_directory_override: str | None = None
    authorized_directories: tuple[str, ...] = ()
    runtime_identity: Mapping[str, Any] = field(default_factory=dict)
    workflow_type: str | None = None
    workflow_resource_snapshot: Mapping[str, Any] | None = None
    workflow_custom_instruction_path: str | None = None
    logical_agent_identity: str | None = None
    terminal_settings: Mapping[str, Any] = field(default_factory=dict)
    instructions: str | None = None
    semantic_settings: Mapping[str, Any] = field(default_factory=dict)
    destination_preferences: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


_PERMISSION_RANK = {
    "read-only": 0,
    "workspace-write": 1,
    "danger-full-access": 2,
    "full-access": 2,
}


def _path_status(path: str, runtime_identity: Mapping[str, Any]) -> tuple[str, str | None]:
    """Check host paths locally; defer WSL path existence to the provider-runtime validator."""
    if runtime_identity.get("runtime_kind") == "wsl":
        return "preserved", "Path identity is retained; existence must be verified inside the selected WSL runtime."
    if Path(path).is_dir():
        return "preserved", None
    return "conflicting", "Recorded path is missing; no substitute will be used."

# These capabilities correspond to managed parser/argv support in dispatcher_cli.
VERIFIED_CAPABILITIES: dict[str, frozenset[str]] = {
    "codex": frozenset({"reasoning_effort", "filesystem", "approval", "search", "additional_directories",
                        "no_alt_screen", "no_daemon", "strict_config"}),
    "agy": frozenset({"reasoning_effort", "additional_directories"}),
    "claude": frozenset({"reasoning_effort", "additional_directories"}),
}


def provider_settings_argv(provider: str, settings: Mapping[str, Any]) -> list[str]:
    """Encode already-validated settings for the same provider; never copy raw argv."""
    values: dict[str, Any] = dict(settings)
    argv: list[str] = []
    if provider == "codex":
        for keys, option in (("sandbox", "--sandbox"), ("approval_policy", "--ask-for-approval"),
                             ("model", "--model"), ("profile provider_profile", "--profile")):
            key = next((candidate for candidate in keys.split() if values.get(candidate) is not None), None)
            if key:
                argv.extend((option, str(values[key])))
        if values.get("reasoning_effort"):
            argv.extend(("--config", f"model_reasoning_effort={values['reasoning_effort']}"))
        if values.get("search"):
            argv.append("--search")
        for path in values.get("add_dirs", values.get("additional_directories", [])):
            argv.extend(("--add-dir", str(path)))
        for key, option in (("enabled_features", "--enable"), ("disabled_features", "--disable")):
            for value in values.get(key, []):
                argv.extend((option, str(value)))
        for key, option in (("no_alt_screen", "--no-alt-screen"),
                            ("no_daemon", "--no-daemon"), ("strict_config", "--strict-config"),
                            ("auto_approval", "--approve-for-me")):
            if values.get(key):
                argv.append(option)
    elif provider == "claude":
        for keys, option in (("model", "--model"), ("effort reasoning_effort", "--effort"),
                             ("permission_mode", "--permission-mode"), ("provider_profile agent", "--agent")):
            key = next((candidate for candidate in keys.split() if values.get(candidate) is not None), None)
            if key:
                argv.extend((option, str(values[key])))
        for path in values.get("add_dirs", values.get("additional_directories", [])):
            argv.extend(("--add-dir", str(path)))
    elif provider == "agy":
        mapped = {key: values[key] for key in ("model", "effort", "sandbox", "agent") if key in values}
        directories = values.get("additional_directories", values.get("add_dirs"))
        if directories:
            mapped["additional_directories"] = directories
        if "reasoning_effort" in values:
            mapped["effort"] = values["reasoning_effort"]
        if "provider_profile" in values:
            mapped["agent"] = values["provider_profile"]
        if mapped:
            argv.extend(("--settings", json.dumps(mapped, ensure_ascii=False, separators=(",", ":"))))
    return argv


def resolve_portable_launch_context(
    source: Mapping[str, Any], destination_provider: str, *,
    capabilities: Mapping[str, set[str] | frozenset[str]] | None = None,
    destination_runtime: Mapping[str, Any] | None = None,
) -> tuple[PortableLaunchContext, list[ContextItem]]:
    """Normalize safe context while retaining unsupported/conflicting items in preview."""
    provider = destination_provider.casefold()
    supported = (capabilities or {}).get(provider, frozenset())
    context = PortableLaunchContext(
        provider=source.get("provider"),
        repositories=tuple(source.get("repositories", ())),
        working_directory=source.get("working_directory"),
        explicit_directory_override=source.get("explicit_directory_override"),
        authorized_directories=tuple(source.get("authorized_directories", ())),
        runtime_identity=dict(source.get("runtime_identity", {})),
        workflow_type=source.get("workflow_type"),
        workflow_resource_snapshot=(dict(source["workflow_resource_snapshot"])
                                    if isinstance(source.get("workflow_resource_snapshot"), Mapping) else None),
        workflow_custom_instruction_path=source.get("workflow_custom_instruction_path"),
        logical_agent_identity=source.get("logical_agent_identity"),
        terminal_settings=dict(source.get("terminal_settings", {})),
        instructions=source.get("instructions"),
        semantic_settings=dict(source.get("semantic_settings", {})),
        destination_preferences=dict(source.get("destination_preferences", {})),
    )
    items: list[ContextItem] = []
    for repo in context.repositories:
        path = repo.get("worktree") or repo.get("root")
        if path:
            status, reason = _path_status(str(path), context.runtime_identity)
            items.append(ContextItem("repository", dict(repo), status, reason))
        else:
            items.append(ContextItem("repository", dict(repo), "preserved"))
    for directory in context.authorized_directories:
        status, reason = _path_status(directory, context.runtime_identity)
        items.append(ContextItem("authorized_directory", directory, status, reason))
    for key, value in context.semantic_settings.items():
        if key not in supported:
            items.append(ContextItem(key, value, "unsupported", "Destination capability is not verified."))
            continue
        if key == "filesystem":
            if not isinstance(value, str) or value not in _PERMISSION_RANK:
                items.append(ContextItem(
                    key, value, "unsupported", "Filesystem setting has no verified portable permission mapping."
                ))
                continue
            target = source.get("destination_filesystem")
            if isinstance(target, str) and target in _PERMISSION_RANK and _PERMISSION_RANK[target] > _PERMISSION_RANK[value]:
                items.append(ContextItem(key, value, "conflicting", "Destination permission would broaden filesystem access."))
                continue
        items.append(ContextItem(key, value, "translated" if source.get("provider") != provider else "preserved"))
    if context.working_directory:
        status, reason = _path_status(context.working_directory, context.runtime_identity)
        items.append(ContextItem("working_directory", context.working_directory, status, reason))
    if context.explicit_directory_override:
        status, reason = _path_status(context.explicit_directory_override, context.runtime_identity)
        items.append(ContextItem("explicit_directory_override", context.explicit_directory_override, status, reason))
    if context.workflow_type:
        items.append(ContextItem("workflow_type", context.workflow_type, "preserved"))
    if context.logical_agent_identity:
        items.append(ContextItem("logical_agent_identity", context.logical_agent_identity, "preserved"))
    for key, value in context.terminal_settings.items():
        status = "preserved" if key in supported else "unsupported"
        reason = None if status == "preserved" else "Destination terminal setting is not verified."
        items.append(ContextItem(f"terminal:{key}", value, status, reason))
    if context.workflow_resource_snapshot:
        items.append(ContextItem(
            "workflow_resource_snapshot", dict(context.workflow_resource_snapshot), "restored",
            "Resource identities and digests are retained; provider-loaded context and resume persistence are unverified.",
        ))
    if context.workflow_custom_instruction_path:
        path = context.workflow_custom_instruction_path
        status = "preserved" if Path(path).is_file() else "conflicting"
        reason = None if status == "preserved" else "Custom instruction source is missing; no replacement will be used."
        items.append(ContextItem("workflow_custom_instruction_path", path, status, reason))
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
