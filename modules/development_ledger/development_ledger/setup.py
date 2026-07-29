"""Cross-repository setup and managed instruction-file injection."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Iterable

MANAGED_START = "<!-- development-ledger:managed-instructions:start -->"
MANAGED_END = "<!-- development-ledger:managed-instructions:end -->"
GENERATED_MARKER = "<!-- development-ledger:generated-template:v1 -->"
CONFIG_FILENAME = ".development-ledger.json"
SUPPORTED_AGENTS = ("codex", "claude", "gemini", "copilot")


class SetupError(ValueError):
    """Raised when a setup request is unsafe or cannot be represented."""


@dataclass(slots=True)
class SetupOperation:
    """One planned filesystem operation."""

    path: str
    action: str
    reason: str
    content: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class SetupResult:
    """Complete dry-run or applied setup result."""

    repo_root: str
    scopes: list[str]
    agents: list[str]
    operations: list[SetupOperation]

    @property
    def has_conflicts(self) -> bool:
        return any(operation.action == "conflict" for operation in self.operations)

    @property
    def changed_count(self) -> int:
        return sum(operation.action in {"create", "update"} for operation in self.operations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_root": self.repo_root,
            "scopes": self.scopes,
            "agents": self.agents,
            "changed_count": self.changed_count,
            "has_conflicts": self.has_conflicts,
            "operations": [operation.to_dict() for operation in self.operations],
        }


def plan_repository_setup(
    repo_root: Path,
    *,
    scopes: Iterable[str] = (),
    modules: Iterable[str] = (),
    all_modules: bool = False,
    agents: Iterable[str] = (),
    repository_name: str = "",
    force: bool = False,
) -> SetupResult:
    """Build a non-mutating cross-repository setup plan."""

    root = repo_root.expanduser().resolve()
    if not root.is_dir():
        raise SetupError(f"Repository root does not exist or is not a directory: {root}")

    selected_agents = _normalize_agents(agents)
    scope_paths = _resolve_scopes(root, scopes=scopes, modules=modules, all_modules=all_modules)
    repo_name = repository_name.strip() or root.name
    operations: list[SetupOperation] = []

    workflow_path = root / "docs" / "agent" / "DEVELOPMENT_LEDGER_WORKFLOW.md"
    root_values = {
        "REPOSITORY_NAME": repo_name,
        "SCOPE_PATH": ".",
        "DOCS_PATH": "docs",
        "ROOT_WORKFLOW_PATH": "docs/agent/DEVELOPMENT_LEDGER_WORKFLOW.md",
        "ROOT_WORKFLOW_IMPORT": "./docs/agent/DEVELOPMENT_LEDGER_WORKFLOW.md",
        "AGENTS_IMPORT": "./AGENTS.md",
    }

    operations.append(_plan_managed_instruction(root / "AGENTS.md", _template("agents-root.md", root_values)))
    if "claude" in selected_agents:
        operations.append(_plan_managed_instruction(root / "CLAUDE.md", _template("claude-root.md", root_values)))
    if "gemini" in selected_agents:
        operations.append(_plan_managed_instruction(root / "GEMINI.md", _template("gemini-root.md", root_values)))
    if "copilot" in selected_agents:
        operations.append(
            _plan_managed_instruction(root / ".github" / "copilot-instructions.md", _template("copilot-root.md", root_values))
        )

    operations.extend(
        [
            _plan_owned_file(workflow_path, _template("workflow.md", root_values), force=force),
            _plan_create_only(root / "docs" / "README.md", _template("docs-readme.md", root_values)),
            _plan_create_only(root / "docs" / "HANDOFF.md", _template("handoff.md", root_values)),
            _plan_create_only(root / "docs" / "plans" / "README.md", _template("plans-readme.md", root_values)),
        ]
    )

    for scope in scope_paths:
        if scope == Path("."):
            continue
        scope_root = root / scope
        scope_text = scope.as_posix()
        docs_path = f"{scope_text}/docs"
        workflow_relative = Path(os.path.relpath(workflow_path, scope_root)).as_posix()
        values = {
            "REPOSITORY_NAME": repo_name,
            "SCOPE_PATH": scope_text,
            "DOCS_PATH": docs_path,
            "ROOT_WORKFLOW_PATH": workflow_relative,
            "ROOT_WORKFLOW_IMPORT": f"./{workflow_relative}" if not workflow_relative.startswith(".") else workflow_relative,
            "AGENTS_IMPORT": "./AGENTS.md",
        }
        operations.append(_plan_managed_instruction(scope_root / "AGENTS.md", _template("agents-scope.md", values)))
        if "claude" in selected_agents:
            operations.append(_plan_managed_instruction(scope_root / "CLAUDE.md", _template("claude-scope.md", values)))
        if "gemini" in selected_agents:
            operations.append(_plan_managed_instruction(scope_root / "GEMINI.md", _template("gemini-scope.md", values)))
        if "copilot" in selected_agents:
            slug = _scope_slug(scope)
            copilot_values = dict(values)
            copilot_values["APPLY_TO"] = f"{scope_text}/**"
            operations.append(
                _plan_owned_file(
                    root / ".github" / "instructions" / f"development-ledger-{slug}.instructions.md",
                    _template("copilot-scope.md", copilot_values),
                    force=force,
                )
            )
        operations.extend(
            [
                _plan_create_only(scope_root / "docs" / "README.md", _template("scope-docs-readme.md", values)),
                _plan_create_only(scope_root / "docs" / "HANDOFF.md", _template("handoff.md", values)),
                _plan_create_only(scope_root / "docs" / "plans" / "README.md", _template("plans-readme.md", values)),
            ]
        )

    config_path = root / CONFIG_FILENAME
    config_content = _merged_config(
        config_path,
        repository_name=repo_name,
        scope_paths=scope_paths,
        agents=selected_agents,
        force=force,
    )
    operations.append(_plan_json_file(config_path, config_content, force=force))

    return SetupResult(
        repo_root=str(root),
        scopes=[scope.as_posix() for scope in scope_paths],
        agents=list(selected_agents),
        operations=_deduplicate_operations(root, operations),
    )


def apply_setup(result: SetupResult) -> None:
    """Apply all non-conflicting create/update operations from a setup plan."""

    if result.has_conflicts:
        conflicts = [operation.path for operation in result.operations if operation.action == "conflict"]
        raise SetupError("Refusing to apply setup with conflicts: " + ", ".join(conflicts))
    root = Path(result.repo_root)
    for operation in result.operations:
        if operation.action not in {"create", "update"}:
            continue
        path = root / operation.path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.development-ledger.tmp")
        temporary.write_text(operation.content, encoding="utf-8", newline="\n")
        temporary.replace(path)


def _resolve_scopes(
    root: Path,
    *,
    scopes: Iterable[str],
    modules: Iterable[str],
    all_modules: bool,
) -> list[Path]:
    candidates = [Path(".")]
    candidates.extend(Path(value) for value in scopes)
    for module in modules:
        if not module or Path(module).name != module or "/" in module or "\\" in module:
            raise SetupError(f"Module names must be one path segment: {module!r}")
        candidates.append(Path("modules") / module)
    if all_modules:
        module_root = root / "modules"
        if module_root.is_dir():
            candidates.extend(path.relative_to(root) for path in sorted(module_root.iterdir()) if path.is_dir())

    normalized: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.is_absolute() or ".." in candidate.parts:
            raise SetupError(f"Scope must be repository-relative and cannot contain '..': {candidate}")
        normalized_scope = Path(".") if str(candidate) in {"", "."} else Path(candidate.as_posix().strip("/"))
        scope_root = (root / normalized_scope).resolve()
        try:
            scope_root.relative_to(root)
        except ValueError as exc:
            raise SetupError(f"Scope escapes repository root: {candidate}") from exc
        if not scope_root.is_dir():
            raise SetupError(f"Scope directory does not exist: {normalized_scope.as_posix()}")
        key = normalized_scope.as_posix()
        if key not in seen:
            seen.add(key)
            normalized.append(normalized_scope)
    return normalized


def _normalize_agents(agents: Iterable[str]) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(value.lower() for value in agents)) or SUPPORTED_AGENTS
    unknown = sorted(set(values) - set(SUPPORTED_AGENTS))
    if unknown:
        raise SetupError("Unsupported agent target(s): " + ", ".join(unknown))
    return values


def _template(name: str, values: dict[str, str]) -> str:
    template = resources.files("development_ledger").joinpath("templates", name).read_text(encoding="utf-8")
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    unresolved = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", template)))
    if unresolved:
        raise SetupError(f"Template {name} has unresolved tokens: {', '.join(unresolved)}")
    return template.rstrip() + "\n"


def _plan_managed_instruction(path: Path, managed_block: str) -> SetupOperation:
    if not path.exists():
        header = f"# {path.stem} Instructions\n\n" if path.name != "copilot-instructions.md" else "# Repository Instructions\n\n"
        return SetupOperation(str(path), "create", "Create native agent instruction file.", header + managed_block)

    existing = path.read_text(encoding="utf-8")
    start_count = existing.count(MANAGED_START)
    end_count = existing.count(MANAGED_END)
    if start_count != end_count or start_count > 1:
        return SetupOperation(str(path), "conflict", "Malformed or duplicate managed instruction markers.")
    if start_count == 1:
        start = existing.index(MANAGED_START)
        end = existing.index(MANAGED_END, start) + len(MANAGED_END)
        merged = existing[:start] + managed_block.rstrip() + existing[end:]
    else:
        merged = managed_block.rstrip() + "\n\n" + existing
    merged = merged.rstrip() + "\n"
    action = "unchanged" if merged == existing else "update"
    reason = "Managed instruction block is current." if action == "unchanged" else "Inject or refresh managed instructions."
    return SetupOperation(str(path), action, reason, merged if action == "update" else "")


def _plan_owned_file(path: Path, content: str, *, force: bool) -> SetupOperation:
    if not path.exists():
        return SetupOperation(str(path), "create", "Create development-ledger managed file.", content)
    existing = path.read_text(encoding="utf-8")
    if existing == content:
        return SetupOperation(str(path), "unchanged", "Managed file is current.")
    if existing.startswith(GENERATED_MARKER) or force:
        return SetupOperation(str(path), "update", "Refresh development-ledger managed file.", content)
    return SetupOperation(str(path), "conflict", "Existing unmarked file would be overwritten; use --force to replace it.")


def _plan_create_only(path: Path, content: str) -> SetupOperation:
    if path.exists():
        return SetupOperation(str(path), "unchanged", "Existing user-maintained file was preserved.")
    return SetupOperation(str(path), "create", "Create initial user-maintained scaffold.", content)


def _merged_config(
    path: Path,
    *,
    repository_name: str,
    scope_paths: list[Path],
    agents: tuple[str, ...],
    force: bool,
) -> str:
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            if not force:
                raise SetupError(f"Invalid JSON in existing {path}: {exc}") from exc
            loaded = {}
        if not isinstance(loaded, dict):
            if not force:
                raise SetupError(f"Existing {path} must contain a JSON object.")
            loaded = {}
        existing = loaded

    existing["schema_version"] = 1
    existing["repository_name"] = repository_name
    existing["instruction_strategy"] = "essential-inline-plus-native-imports"
    prior_agents = existing.get("agents", []) if isinstance(existing.get("agents", []), list) else []
    existing["agents"] = list(dict.fromkeys([*(str(value) for value in prior_agents), *agents]))
    current_scopes = {
        str(item.get("path")): item
        for item in existing.get("scopes", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    for scope in scope_paths:
        scope_text = scope.as_posix()
        current_scopes[scope_text] = {
            "path": scope_text,
            "docs_path": "docs" if scope == Path(".") else f"{scope_text}/docs",
            "plan_root": "docs/plans" if scope == Path(".") else f"{scope_text}/docs/plans",
        }
    existing["scopes"] = [current_scopes[key] for key in sorted(current_scopes, key=lambda value: (value != ".", value))]
    existing["workflow_document"] = "docs/agent/DEVELOPMENT_LEDGER_WORKFLOW.md"
    return json.dumps(existing, indent=4, ensure_ascii=False) + "\n"


def _plan_json_file(path: Path, content: str, *, force: bool) -> SetupOperation:
    if not path.exists():
        return SetupOperation(str(path), "create", "Create development-ledger repository configuration.", content)
    existing = path.read_text(encoding="utf-8")
    if existing == content:
        return SetupOperation(str(path), "unchanged", "Repository configuration is current.")
    if force or _is_development_ledger_config(existing):
        return SetupOperation(str(path), "update", "Merge development-ledger repository configuration.", content)
    return SetupOperation(str(path), "conflict", "Existing configuration is not recognized as development-ledger config.")


def _is_development_ledger_config(content: str) -> bool:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and data.get("schema_version") == 1 and "scopes" in data


def _scope_slug(scope: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", scope.as_posix().lower()).strip("-") or "root"


def _deduplicate_operations(root: Path, operations: list[SetupOperation]) -> list[SetupOperation]:
    deduplicated: dict[str, SetupOperation] = {}
    for operation in operations:
        absolute = Path(operation.path)
        relative = absolute.relative_to(root) if absolute.is_absolute() else absolute
        operation.path = relative.as_posix()
        deduplicated[operation.path] = operation
    return list(deduplicated.values())
