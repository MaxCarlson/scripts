"""Reusable command registry, collision detection, and entry-point validation."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import re
import shutil
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from scripts_help._repo_root import find_repo_root
from scripts_help.registry import REGISTRY

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CommandEntry:
    """Canonical representation of a registered command or shell alias/function."""

    name: str
    program_id: str
    invoked_name: str
    kind: str
    source: str
    target: str
    description: str = ""
    platforms: tuple[str, ...] = ("windows", "linux", "wsl", "termux")
    shell_adapter_required: bool = False
    distribution: str | None = None
    entry_point: str | None = None
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CollisionRecord:
    """Detected command name collision across registry or PATH."""

    name: str
    collision_type: str
    sources: tuple[str, ...]
    details: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EntryPointValidation:
    """Read-only validation result for a registered command."""

    name: str
    program_id: str
    kind: str
    status: str  # ok, missing_target, import_error, unsupported_platform, skipped
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def current_platform_tag() -> str:
    """Return normalized platform tag: windows, wsl, termux, macos, or linux."""
    if os.name == "nt":
        return "windows"
    if "ANDROID_ROOT" in os.environ or Path("/data/data/com.termux").exists():
        return "termux"
    if sys.platform == "darwin":
        return "macos"
    try:
        rel = os.uname().release.lower()
        if "microsoft" in rel:
            return "wsl"
    except AttributeError:
        pass
    return "linux"


def _walk_scripts_help_registry() -> Iterable[dict[str, Any]]:
    def walk(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
        yield from node.get("items", ())
        for sub in node.get("subcategories", {}).values():
            yield from walk(sub)

    for category in REGISTRY.values():
        yield from walk(category)


def _descriptions_by_path() -> dict[str, str]:
    by_path: dict[str, str] = {}
    for item in _walk_scripts_help_registry():
        path = str(item.get("path", "")).replace("\\", "/")
        desc = str(item.get("desc", "")).strip()
        if path and desc:
            by_path[path] = desc
    return by_path


def _module_command_descriptions(
    repo_root: Path,
    source_paths: Iterable[str],
) -> dict[str, dict[str, str]]:
    """Load explicit scripts-help summaries for commands owned by modules."""
    descriptions: dict[str, dict[str, str]] = {}
    for source_path in sorted(set(source_paths)):
        relative_path = Path(source_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            continue
        module_dir = repo_root / relative_path
        pyproject = module_dir / "pyproject.toml"
        if not module_dir.is_dir() or not pyproject.is_file():
            continue
        try:
            project_data = tomllib.loads(pyproject.read_text(encoding="utf-8", errors="replace"))
        except (OSError, tomllib.TOMLDecodeError):
            continue

        raw = project_data.get("tool", {}).get("scripts_help", {}).get("descriptions", {})
        if not isinstance(raw, dict):
            continue
        command_descriptions = {
            str(name): str(description).strip()
            for name, description in raw.items()
            if str(description).strip()
        }
        if command_descriptions:
            descriptions[f"modules/{module_dir.name}"] = command_descriptions
    return descriptions


def _load_manifest_commands(repo_root: Path, descriptions: dict[str, str]) -> list[CommandEntry]:
    manifest_path = repo_root / "scripts_manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    raw_commands = data.get("commands", {})
    if not isinstance(raw_commands, dict):
        return []

    module_descriptions = _module_command_descriptions(
        repo_root,
        (
            str(info.get("source_path", "")).replace("\\", "/")
            for info in raw_commands.values()
            if isinstance(info, dict)
        ),
    )
    entries: list[CommandEntry] = []
    for name, info in sorted(raw_commands.items()):
        if not isinstance(info, dict):
            continue
        source_path = str(info.get("source_path", "")).replace("\\", "/")
        kind = str(info.get("kind", "command"))
        target = str(info.get("entry_point") or info.get("target") or "")
        desc = module_descriptions.get(source_path, {}).get(name) or descriptions.get(source_path, "")
        entries.append(
            CommandEntry(
                name=name,
                program_id=str(info.get("program_id", f"command:{name}")),
                invoked_name=name,
                kind=kind,
                source="scripts_manifest",
                target=target,
                description=desc,
                platforms=("windows", "linux", "wsl", "termux"),
                shell_adapter_required=False,
                distribution=info.get("distribution"),
                entry_point=info.get("entry_point"),
                version=info.get("version"),
            )
        )
    return entries


def _load_pyproject_console_scripts(
    repo_root: Path,
    existing_names: set[str],
    descriptions: dict[str, str],
) -> list[CommandEntry]:
    """Supplement manifest with any [project.scripts] declared in modules/*/pyproject.toml."""
    modules_dir = repo_root / "modules"
    if not modules_dir.is_dir():
        return []

    assignment = re.compile(r"""^\s*["']?([^"'=]+?)["']?\s*=\s*["']([^"']+)["']\s*(?:#.*)?$""")
    version_re = re.compile(r"""(?m)^\s*version\s*=\s*["']([^"']+)["']""")
    name_re = re.compile(r"""(?m)^\s*name\s*=\s*["']([^"']+)["']""")

    entries: list[CommandEntry] = []
    for mod in sorted(modules_dir.iterdir()):
        pyproject = mod / "pyproject.toml"
        if not mod.is_dir() or not pyproject.is_file():
            continue
        try:
            text = pyproject.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m_scripts = re.search(r"(?ms)^\[project\.scripts\]\s*(.*?)(?=^\[|\Z)", text)
        if not m_scripts:
            continue

        m_proj = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", text)
        proj_sec = m_proj.group(1) if m_proj else ""
        dist_m = name_re.search(proj_sec)
        ver_m = version_re.search(proj_sec)
        dist = dist_m.group(1).strip() if dist_m else mod.name
        ver = ver_m.group(1).strip() if ver_m else None
        rel_mod = f"modules/{mod.name}"
        project_desc_m = re.search(r'''(?m)^\s*description\s*=\s*["']([^"']*)["']''', proj_sec)
        project_desc = project_desc_m.group(1).strip() if project_desc_m else ""
        command_descriptions: dict[str, str] = {}
        try:
            project_data = tomllib.loads(text)
            raw_descriptions = (
                project_data.get("tool", {}).get("scripts_help", {}).get("descriptions", {})
            )
            if isinstance(raw_descriptions, dict):
                command_descriptions = {
                    str(name): str(value).strip()
                    for name, value in raw_descriptions.items()
                    if str(value).strip()
                }
        except (tomllib.TOMLDecodeError, AttributeError):
            pass
        module_desc = descriptions.get(rel_mod, "") or project_desc

        for raw_line in m_scripts.group(1).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parsed = assignment.match(line)
            if not parsed:
                continue
            cmd = parsed.group(1).strip()
            target = parsed.group(2).strip()
            if cmd in existing_names:
                continue
            existing_names.add(cmd)
            entries.append(
                CommandEntry(
                    name=cmd,
                    program_id=f"module:{dist}",
                    invoked_name=cmd,
                    kind="console_script",
                    source="pyproject",
                    target=target,
                    description=command_descriptions.get(cmd, module_desc),
                    platforms=("windows", "linux", "wsl", "termux"),
                    shell_adapter_required=False,
                    distribution=dist,
                    entry_point=target,
                    version=ver,
                )
            )
    return entries


def load_command_registry(repo_root: Path | None = None) -> list[CommandEntry]:
    """Load unified command entries from scripts_manifest.json, scripts_help, and pyproject.toml."""
    root = repo_root or find_repo_root()
    descriptions = _descriptions_by_path()
    entries = _load_manifest_commands(root, descriptions)
    existing_names = {e.name for e in entries}
    entries.extend(_load_pyproject_console_scripts(root, existing_names, descriptions))

    # Ensure `ag` is represented as requiring an optional shell adapter for live shell inventory
    if "ag" not in existing_names:
        entries.append(
            CommandEntry(
                name="ag",
                program_id="module:scripts_help",
                invoked_name="ag",
                kind="console_script",
                source="scripts_help",
                target="scripts_help.ag:main",
                description="Search registered Python commands and live shell aliases/functions",
                platforms=("windows", "linux", "wsl", "termux"),
                shell_adapter_required=True,
                distribution="scripts_help",
                entry_point="scripts_help.ag:main",
            )
        )
    return sorted(entries, key=lambda e: (e.name.lower(), e.source))


def search_commands(
    entries: Sequence[CommandEntry],
    pattern: str,
    *,
    kind: str | None = None,
    source: str | None = None,
    case_sensitive: bool = False,
) -> list[CommandEntry]:
    """Filter command entries by regex pattern on name, target, or description."""
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rx = re.compile(pattern, flags)
    except re.error:
        rx = re.compile(re.escape(pattern), flags)

    results: list[CommandEntry] = []
    for entry in entries:
        if kind and kind != "all" and entry.kind.lower() != kind.lower():
            continue
        if source and source != "all" and entry.source.lower() != source.lower():
            continue
        if rx.search(entry.name) or rx.search(entry.target) or rx.search(entry.description):
            results.append(entry)
    return results


def resolve_command(entries: Sequence[CommandEntry], name: str) -> list[CommandEntry]:
    """Return exact matches (or case-insensitive fallback) for a command name."""
    exact = [e for e in entries if e.name == name]
    if exact:
        return exact
    lower = name.lower()
    return [e for e in entries if e.name.lower() == lower]


def _is_toolkit_path(candidate: Path, repo_root: Path | None) -> bool:
    if repo_root is None:
        return False
    try:
        resolved = candidate.resolve()
        root_resolved = repo_root.resolve()
        return str(resolved).lower().startswith(str(root_resolved).lower())
    except OSError:
        return False


def detect_collisions(
    entries: Sequence[CommandEntry],
    *,
    repo_root: Path | None = None,
    path_env: str | None = None,
    check_path: bool = True,
) -> list[CollisionRecord]:
    """Detect duplicate names, case-insensitive clashes, and external PATH collisions."""
    collisions: list[CollisionRecord] = []

    by_exact: dict[str, list[CommandEntry]] = {}
    by_lower: dict[str, list[CommandEntry]] = {}
    for e in entries:
        by_exact.setdefault(e.name, []).append(e)
        by_lower.setdefault(e.name.lower(), []).append(e)

    for name, group in sorted(by_exact.items()):
        if len(group) > 1:
            collisions.append(
                CollisionRecord(
                    name=name,
                    collision_type="duplicate_name",
                    sources=tuple(sorted({g.source for g in group})),
                    details=f"{len(group)} entries share exact name '{name}': "
                    + ", ".join(f"{g.source}:{g.kind}" for g in group),
                )
            )

    for lower_name, group in sorted(by_lower.items()):
        distinct_cases = {g.name for g in group}
        if len(distinct_cases) > 1:
            collisions.append(
                CollisionRecord(
                    name=lower_name,
                    collision_type="case_clash",
                    sources=tuple(sorted({g.source for g in group})),
                    details=f"Case-insensitive clash: {sorted(distinct_cases)}",
                )
            )

    if check_path:
        env_path = path_env if path_env is not None else os.environ.get("PATH", "")
        known_builtin_risks = {
            "ag": "Unix Silver Searcher (`ag`) if installed on PATH",
            "sfc": "Windows System File Checker (`sfc.exe`)",
            "gcb": "PowerShell built-in alias for `Get-Clipboard`",
            "scb": "PowerShell built-in alias for `Set-Clipboard`",
        }
        for name in sorted({e.name for e in entries}):
            found = shutil.which(name, path=env_path)
            if found:
                found_path = Path(found)
                if not _is_toolkit_path(found_path, repo_root):
                    collisions.append(
                        CollisionRecord(
                            name=name,
                            collision_type="path_external",
                            sources=("path",),
                            details=f"External executable on PATH: {found}",
                        )
                    )
            elif name in known_builtin_risks and os.name == "nt" and name in ("gcb", "scb"):
                collisions.append(
                    CollisionRecord(
                        name=name,
                        collision_type="shell_builtin",
                        sources=("pwsh",),
                        details=f"Known shell built-in alias: {known_builtin_risks[name]}",
                    )
                )

    return collisions


def validate_entry_points(
    entries: Sequence[CommandEntry],
    *,
    repo_root: Path | None = None,
) -> list[EntryPointValidation]:
    """Read-only validation of registered console scripts and script targets."""
    root = repo_root or find_repo_root()
    plat = current_platform_tag()
    results: list[EntryPointValidation] = []

    for entry in entries:
        if entry.platforms and plat not in entry.platforms:
            results.append(
                EntryPointValidation(
                    name=entry.name,
                    program_id=entry.program_id,
                    kind=entry.kind,
                    status="unsupported_platform",
                    details=f"Platform '{plat}' not in {entry.platforms}",
                )
            )
            continue

        if entry.kind == "console_script":
            ep = entry.entry_point or entry.target
            if ":" not in ep:
                results.append(
                    EntryPointValidation(
                        name=entry.name,
                        program_id=entry.program_id,
                        kind=entry.kind,
                        status="skipped",
                        details=f"Non-module target '{ep}'",
                    )
                )
                continue
            mod_name, attr_name = ep.split(":", 1)
            try:
                mod = importlib.import_module(mod_name)
                if not hasattr(mod, attr_name):
                    results.append(
                        EntryPointValidation(
                            name=entry.name,
                            program_id=entry.program_id,
                            kind=entry.kind,
                            status="import_error",
                            details=f"Module '{mod_name}' has no attribute '{attr_name}'",
                        )
                    )
                else:
                    results.append(
                        EntryPointValidation(
                            name=entry.name,
                            program_id=entry.program_id,
                            kind=entry.kind,
                            status="ok",
                            details=ep,
                        )
                    )
            except Exception as exc:
                results.append(
                    EntryPointValidation(
                        name=entry.name,
                        program_id=entry.program_id,
                        kind=entry.kind,
                        status="import_error",
                        details=f"{type(exc).__name__}: {exc}",
                    )
                )
        elif entry.kind in ("python_file", "shell_script"):
            target_path = root / entry.target
            if target_path.is_file():
                results.append(
                    EntryPointValidation(
                        name=entry.name,
                        program_id=entry.program_id,
                        kind=entry.kind,
                        status="ok",
                        details=str(target_path),
                    )
                )
            else:
                results.append(
                    EntryPointValidation(
                        name=entry.name,
                        program_id=entry.program_id,
                        kind=entry.kind,
                        status="missing_target",
                        details=f"Missing file: {target_path}",
                    )
                )
        else:
            results.append(
                EntryPointValidation(
                    name=entry.name,
                    program_id=entry.program_id,
                    kind=entry.kind,
                    status="skipped",
                    details=f"Kind '{entry.kind}' not validated statically",
                )
            )

    return results
