"""Resource manager for AI agent abilities.

Manages agents, prompts, instructions, and skills across multiple AI CLIs.
Source of truth lives in dotfiles; central registry and CLI dirs are symlinked.

Paths:
    SOURCE_DIR:  ~/dotfiles/symlinked/llms/custom_agents/
    CENTRAL_DIR: ~/.local/share/agent-abilities/
    CLI targets:  ~/.claude/, ~/.codex/, ~/.cursor/
"""
import json
import logging
import platform
import shutil
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from .resource_types import RESOURCE_TYPES, ResourceType, detect_resource_type, to_kebab_case
from .templates import (
    generate_agent,
    generate_collection,
    generate_hook,
    generate_instruction,
    generate_prompt,
    generate_skill,
    write_hook_folder,
    write_skill_folder,
)

log = logging.getLogger(__name__)

# ── Link Strategy ────────────────────────────────────────────────────────────
# "symlink" (default on Unix): create symbolic links — lightweight, live updates
# "copy":    deep-copy files — works everywhere, but edits don't propagate
# "auto":    symlink on Unix, copy on Windows (safest default)

LinkStrategy = Literal["symlink", "copy", "auto"]
_DEFAULT_STRATEGY: LinkStrategy = "auto"


def _resolve_strategy(strategy: LinkStrategy = "auto") -> Literal["symlink", "copy"]:
    """Resolve 'auto' to a concrete strategy based on the current platform."""
    if strategy != "auto":
        return strategy
    if platform.system() == "Windows":
        return "copy"
    return "symlink"


def _link_or_copy(source: Path, dest: Path, strategy: LinkStrategy = "auto") -> None:
    """Create a symlink or copy from source to dest based on strategy.

    Removes existing dest (symlink or copy) before proceeding.
    For folder-based resources (skills), copies the entire tree.
    """
    resolved = _resolve_strategy(strategy)

    if dest.is_symlink():
        dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)
    elif dest.exists():
        dest.unlink()

    if resolved == "symlink":
        dest.symlink_to(source)
    else:
        if source.is_dir():
            shutil.copytree(source, dest)
        else:
            shutil.copy2(source, dest)

# ── Paths ────────────────────────────────────────────────────────────────────

CENTRAL_DIR = Path.home() / ".local/share/agent-abilities"
SOURCE_DIR = Path.home() / "dotfiles/symlinked/llms/custom_agents"
INDEX_FILE = CENTRAL_DIR / "abilities-index.json"

CLI_DIRS: Dict[str, Path] = {
    "claude": Path.home() / ".claude",
    "codex": Path.home() / ".codex",
    "cursor": Path.home() / ".cursor",
    "copilot": Path.home() / ".github" / "copilot",
}

# Legacy compat
SKILLS_DIR = CENTRAL_DIR / "skills"
CLI_SKILL_DIRS = {k: v / "skills" for k, v in CLI_DIRS.items()}


def ensure_dirs() -> None:
    """Ensure all required directories exist."""
    CENTRAL_DIR.mkdir(parents=True, exist_ok=True)
    for rtype in RESOURCE_TYPES.values():
        (CENTRAL_DIR / rtype.subdir).mkdir(parents=True, exist_ok=True)


def ensure_source_dirs() -> None:
    """Ensure source directories exist in dotfiles."""
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    for rtype in RESOURCE_TYPES.values():
        (SOURCE_DIR / rtype.subdir).mkdir(parents=True, exist_ok=True)


# ── Frontmatter Parsing ─────────────────────────────────────────────────────

def parse_frontmatter(file_path: Path) -> Optional[Dict[str, Any]]:
    """Parse YAML frontmatter from a markdown file.

    Returns dict with frontmatter fields plus 'body_preview', or None on failure.
    """
    if not file_path.exists():
        return None

    content = file_path.read_text(encoding="utf-8")

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                import yaml
                frontmatter = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()
                return {
                    **frontmatter,
                    "body_preview": body[:500] + "..." if len(body) > 500 else body,
                }
            except Exception as exc:
                log.warning("Failed to parse frontmatter in %s: %s", file_path, exc)
                return None

    return {"body_preview": content[:500]}


def parse_hooks_json(file_path: Path) -> Optional[Dict[str, Any]]:
    """Parse a hooks.json file."""
    if not file_path.exists():
        return None
    try:
        content = json.loads(file_path.read_text(encoding="utf-8"))
        events = list(content.get("hooks", {}).keys())
        return {
            "version": content.get("version", 1),
            "events": events,
            "description": f"Hook with events: {', '.join(events)}",
        }
    except Exception as exc:
        log.warning("Failed to parse hooks.json at %s: %s", file_path, exc)
        return None


def parse_collection_yaml(file_path: Path) -> Optional[Dict[str, Any]]:
    """Parse a .collection.yml file."""
    if not file_path.exists():
        return None
    try:
        import yaml
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "description": data.get("description"),
            "tags": data.get("tags", []),
            "items": data.get("items", []),
        }
    except Exception as exc:
        log.warning("Failed to parse collection YAML at %s: %s", file_path, exc)
        return None


def parse_resource(path: Path, resource_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parse a resource from disk, auto-detecting type if not specified.

    Returns a dict with keys: type, name, path, + frontmatter fields.
    """
    if resource_type is None:
        resource_type = detect_resource_type(str(path))
    if resource_type is None:
        return None

    rtype = RESOURCE_TYPES.get(resource_type)
    if rtype is None:
        return None

    if resource_type == "hook":
        entry = path / rtype.entry_file
        info = parse_hooks_json(entry)
    elif resource_type == "collection":
        info = parse_collection_yaml(path)
    elif rtype.is_folder:
        entry = path / rtype.entry_file
        info = parse_frontmatter(entry)
    else:
        info = parse_frontmatter(path)

    if info is None:
        return None

    # Derive name
    if rtype.is_folder:
        name = info.get("name", path.name)
    else:
        stem = path.stem
        for rt in RESOURCE_TYPES.values():
            if rt.extension and stem.endswith(rt.extension.replace(".md", "")):
                stem = stem[: -len(rt.extension.replace(".md", ""))]
                break
        name = info.get("name", stem)

    return {
        "type": resource_type,
        "name": name,
        "path": str(path),
        **info,
    }


# ── List / Info ──────────────────────────────────────────────────────────────

def list_resources(resource_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all registered resources, optionally filtered by type."""
    ensure_dirs()
    results: List[Dict[str, Any]] = []

    types_to_scan = (
        {resource_type: RESOURCE_TYPES[resource_type]}
        if resource_type and resource_type in RESOURCE_TYPES
        else RESOURCE_TYPES
    )

    for type_key, rtype in types_to_scan.items():
        type_dir = CENTRAL_DIR / rtype.subdir
        if not type_dir.exists():
            continue

        for item in sorted(type_dir.iterdir()):
            if item.name.startswith("."):
                continue

            target = item.resolve() if item.is_symlink() else item
            info = parse_resource(target, type_key)
            if info:
                info["registered_name"] = item.name
                info["is_symlink"] = item.is_symlink()
                results.append(info)

    return results


def get_resource_info(name: str, resource_type: str) -> Optional[Dict[str, Any]]:
    """Get detailed info about a specific registered resource."""
    rtype = RESOURCE_TYPES.get(resource_type)
    if rtype is None:
        return None

    type_dir = CENTRAL_DIR / rtype.subdir

    if rtype.is_folder:
        resource_path = type_dir / name
    else:
        resource_path = type_dir / rtype.filename_for(name)

    if not resource_path.exists() and not resource_path.is_symlink():
        # Try bare name
        resource_path = type_dir / name
        if not resource_path.exists() and not resource_path.is_symlink():
            return None

    target = resource_path.resolve() if resource_path.is_symlink() else resource_path
    return parse_resource(target, resource_type)


# ── Create ───────────────────────────────────────────────────────────────────

def create_resource(
    resource_type: str,
    name: str,
    description: str,
    **kwargs: Any,
) -> Tuple[bool, str, Optional[Path]]:
    """Create a new resource file in the source directory.

    Returns (success, message, path_created).
    """
    rtype = RESOURCE_TYPES.get(resource_type)
    if rtype is None:
        return False, f"Unknown resource type: {resource_type}", None

    slug = to_kebab_case(name)
    name_error = rtype.validate_name(slug)
    if name_error:
        return False, name_error, None

    ensure_source_dirs()
    type_dir = SOURCE_DIR / rtype.subdir

    if resource_type == "hook":
        dest = type_dir / slug
        if dest.exists():
            return False, f"Hook folder already exists: {dest}", None

        hook_files = generate_hook(
            name=slug,
            description=description,
            events=kwargs.get("events"),
        )
        created_path = write_hook_folder(type_dir, slug, hook_files)
        return True, f"Created hook: {created_path}", created_path

    elif resource_type == "collection":
        filename = rtype.filename_for(slug)
        dest = type_dir / filename
        if dest.exists():
            return False, f"Collection file already exists: {dest}", None

        content = generate_collection(
            name=slug,
            description=description,
            tags=kwargs.get("tags"),
            items=kwargs.get("items"),
        )
        dest.write_text(content, encoding="utf-8")
        return True, f"Created collection: {dest}", dest

    elif rtype.is_folder:
        dest = type_dir / slug
        if dest.exists():
            return False, f"Skill folder already exists: {dest}", None

        skill_files = generate_skill(
            name=slug,
            description=description,
            license_type=kwargs.get("license"),
            allowed_tools=kwargs.get("allowed_tools"),
            with_refs=kwargs.get("with_refs", False),
            with_scripts=kwargs.get("with_scripts", False),
            with_assets=kwargs.get("with_assets", False),
        )
        created_path = write_skill_folder(type_dir, slug, skill_files)
        return True, f"Created skill: {created_path}", created_path

    else:
        filename = rtype.filename_for(slug)
        dest = type_dir / filename
        if dest.exists():
            return False, f"File already exists: {dest}", None

        if resource_type == "agent":
            content = generate_agent(
                name=slug,
                description=description,
                model=kwargs.get("model"),
                tools=kwargs.get("tools"),
            )
        elif resource_type == "prompt":
            content = generate_prompt(
                name=slug,
                description=description,
                tools=kwargs.get("tools"),
                model=kwargs.get("model"),
            )
        elif resource_type == "instruction":
            apply_to = kwargs.get("apply_to", "**")
            content = generate_instruction(
                name=slug,
                description=description,
                apply_to=apply_to,
            )
        else:
            return False, f"No template for type: {resource_type}", None

        dest.write_text(content, encoding="utf-8")
        return True, f"Created {resource_type}: {dest}", dest


# ── Add / Remove ─────────────────────────────────────────────────────────────

def add_resource(
    source_path: str,
    resource_type: Optional[str] = None,
    name: Optional[str] = None,
    strategy: LinkStrategy = _DEFAULT_STRATEGY,
) -> Tuple[bool, str]:
    """Register an existing resource by linking/copying it into the central directory."""
    ensure_dirs()
    source = Path(source_path).expanduser().resolve()

    if not source.exists():
        return False, f"Source does not exist: {source}"

    if resource_type is None:
        resource_type = detect_resource_type(str(source))
    if resource_type is None:
        return False, f"Cannot detect resource type for: {source}"

    rtype = RESOURCE_TYPES[resource_type]

    # Parse to get name
    info = parse_resource(source, resource_type)
    if not info:
        return False, f"Could not parse resource at: {source}"

    resource_name = name or info.get("name", source.stem)

    # Link or copy into central dir
    type_dir = CENTRAL_DIR / rtype.subdir
    type_dir.mkdir(parents=True, exist_ok=True)

    if rtype.is_folder:
        dest = type_dir / to_kebab_case(resource_name)
    else:
        dest = type_dir / rtype.filename_for(resource_name)

    _link_or_copy(source, dest, strategy)
    update_index()

    method = _resolve_strategy(strategy)
    return True, f"Added {resource_type} '{resource_name}' -> {source} ({method})"


def remove_resource(name: str, resource_type: str) -> Tuple[bool, str]:
    """Remove a resource from the central directory."""
    ensure_dirs()
    rtype = RESOURCE_TYPES.get(resource_type)
    if rtype is None:
        return False, f"Unknown type: {resource_type}"

    type_dir = CENTRAL_DIR / rtype.subdir

    if rtype.is_folder:
        resource_path = type_dir / to_kebab_case(name)
    else:
        resource_path = type_dir / rtype.filename_for(name)

    if not resource_path.exists() and not resource_path.is_symlink():
        # Try bare name
        resource_path = type_dir / name
        if not resource_path.exists() and not resource_path.is_symlink():
            return False, f"Resource '{name}' not found in {resource_type}s"

    resource_path.unlink()
    update_index()
    return True, f"Removed {resource_type} '{name}'"


# ── Prune ────────────────────────────────────────────────────────────────────

def _prune_broken_symlinks(directory: Path) -> List[str]:
    """Remove broken symlinks from a directory. Returns list of removed names."""
    removed = []
    if not directory.exists():
        return removed
    for item in sorted(directory.iterdir()):
        if item.is_symlink() and not item.resolve().exists():
            item.unlink()
            removed.append(item.name)
    return removed


def _prune_orphaned_copies(directory: Path, known_sources: Dict[str, str]) -> List[str]:
    """Remove copied resources whose source no longer exists.

    Uses the index to map resource names back to their original source paths.
    Only removes items that are NOT symlinks (i.e. copies) and whose source is gone.
    """
    removed = []
    if not directory.exists():
        return removed
    for item in sorted(directory.iterdir()):
        if item.name.startswith(".") or item.is_symlink():
            continue
        source_path = known_sources.get(item.name)
        if source_path and not Path(source_path).exists():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            removed.append(item.name)
    return removed


def _load_index_sources() -> Dict[str, Dict[str, str]]:
    """Load the index and return a mapping of type/name -> source path."""
    if not INDEX_FILE.exists():
        return {}
    try:
        index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        result: Dict[str, Dict[str, str]] = {}
        for key, entry in index.get("resources", {}).items():
            rtype = entry.get("type", "")
            name = key.split("/", 1)[-1] if "/" in key else key
            result.setdefault(rtype, {})[name] = entry.get("path", "")
        return result
    except Exception:
        return {}


def prune(prune_clis: bool = True) -> List[str]:
    """Remove broken symlinks and orphaned copies from registry and CLI directories.

    Broken symlinks point to source files that were deleted (e.g. removed from
    git). Orphaned copies are files whose original source no longer exists
    (detected via the index).

    This operation is idempotent -- running it multiple times is safe and
    produces the same result.

    Returns a list of human-readable messages for each removal.
    """
    messages: List[str] = []
    index_sources = _load_index_sources()

    # 1. Prune central registry
    for rtype in RESOURCE_TYPES.values():
        type_dir = CENTRAL_DIR / rtype.subdir
        # Broken symlinks
        removed = _prune_broken_symlinks(type_dir)
        for name in removed:
            messages.append(f"Pruned {rtype.name}/{name} from central registry (broken symlink)")
        # Orphaned copies
        sources = index_sources.get(rtype.name, {})
        removed = _prune_orphaned_copies(type_dir, sources)
        for name in removed:
            messages.append(f"Pruned {rtype.name}/{name} from central registry (source deleted)")

    # 2. Prune CLI directories
    if prune_clis:
        for cli_name, cli_base in CLI_DIRS.items():
            for rtype in RESOURCE_TYPES.values():
                cli_type_dir = cli_base / rtype.subdir
                removed = _prune_broken_symlinks(cli_type_dir)
                for name in removed:
                    messages.append(f"Pruned {rtype.name}/{name} from {cli_name} (broken symlink)")

    if messages:
        update_index()

    return messages


# ── Sync ─────────────────────────────────────────────────────────────────────

def sync_to_cli(cli: str, strategy: LinkStrategy = _DEFAULT_STRATEGY) -> Tuple[bool, str]:
    """Sync all registered resources to a specific CLI's directory."""
    if cli not in CLI_DIRS:
        return False, f"Unknown CLI: {cli}. Known: {list(CLI_DIRS.keys())}"

    cli_base = CLI_DIRS[cli]
    synced = []

    for type_key, rtype in RESOURCE_TYPES.items():
        src_type_dir = CENTRAL_DIR / rtype.subdir
        if not src_type_dir.exists():
            continue

        # Determine CLI target dir
        cli_type_dir = cli_base / rtype.subdir
        cli_type_dir.mkdir(parents=True, exist_ok=True)

        for item in src_type_dir.iterdir():
            if item.name.startswith("."):
                continue

            dest = cli_type_dir / item.name
            # Don't overwrite user-created (non-symlink, non-copy-managed) files
            if dest.exists() and not dest.is_symlink():
                # In copy mode, we do want to update existing copies
                if _resolve_strategy(strategy) == "symlink":
                    continue

            _link_or_copy(item, dest, strategy)
            synced.append(f"{type_key}/{item.name}")

    method = _resolve_strategy(strategy)
    return True, f"Synced {len(synced)} resources to {cli} ({method}): {synced}"


def sync_all_clis() -> List[str]:
    """Sync resources to all known CLIs. Prunes broken symlinks first."""
    pruned = prune(prune_clis=True)
    results = list(pruned)
    for cli in CLI_DIRS:
        success, msg = sync_to_cli(cli)
        results.append(msg)
    return results


# ── Scan ─────────────────────────────────────────────────────────────────────

def scan_for_resources(search_path: str) -> List[Dict[str, Any]]:
    """Scan a directory tree for all recognizable resources."""
    search = Path(search_path).expanduser().resolve()
    found: List[Dict[str, Any]] = []

    # Scan for skills (folder-based with SKILL.md)
    for skill_md in search.rglob("SKILL.md"):
        skill_dir = skill_md.parent
        info = parse_resource(skill_dir, "skill")
        if info:
            slug = to_kebab_case(info.get("name", skill_dir.name))
            registered = (CENTRAL_DIR / "skills" / slug).exists()
            info["is_registered"] = registered
            found.append(info)

    # Scan for hooks (folder-based with hooks.json)
    for hooks_json in search.rglob("hooks.json"):
        hook_dir = hooks_json.parent
        # Skip if this is inside a skill or other nested structure
        if (hook_dir / "SKILL.md").exists():
            continue
        info = parse_resource(hook_dir, "hook")
        if info:
            slug = to_kebab_case(info.get("name", hook_dir.name))
            registered = (CENTRAL_DIR / "hooks" / slug).exists()
            info["is_registered"] = registered
            found.append(info)

    # Scan for file-based types (agents, prompts, instructions, collections)
    for type_key, rtype in RESOURCE_TYPES.items():
        if rtype.is_folder or rtype.extension is None:
            continue
        pattern = f"*{rtype.extension}"
        for match in search.rglob(pattern):
            info = parse_resource(match, type_key)
            if info:
                slug = to_kebab_case(info.get("name", match.stem))
                filename = rtype.filename_for(slug)
                registered = (CENTRAL_DIR / rtype.subdir / filename).exists()
                info["is_registered"] = registered
                found.append(info)

    return found


def auto_register_from_scan(search_path: str) -> List[str]:
    """Scan for resources and auto-register any not already registered.

    Prunes broken symlinks first so stale entries don't block re-registration.
    """
    pruned = prune(prune_clis=False)
    results = list(pruned)
    for resource in scan_for_resources(search_path):
        if not resource.get("is_registered"):
            rtype = resource.get("type", "")
            name = resource.get("name", "")
            path = resource.get("path", "")
            success, msg = add_resource(path, rtype, name)
            results.append(msg)
    return results


# ── Validate ─────────────────────────────────────────────────────────────────

def validate_resource(path: str) -> Tuple[bool, List[str]]:
    """Validate a resource's frontmatter and structure.

    Returns (is_valid, list_of_errors).
    """
    p = Path(path).expanduser().resolve()
    resource_type = detect_resource_type(str(p))
    if resource_type is None:
        return False, [f"Cannot detect resource type for: {p}"]

    rtype = RESOURCE_TYPES[resource_type]
    errors: List[str] = []

    if rtype.is_folder:
        entry = p / rtype.entry_file
        if not entry.exists():
            errors.append(f"Missing entry file: {rtype.entry_file}")
            return False, errors
        fm = parse_frontmatter(entry)
    else:
        fm = parse_frontmatter(p)

    if fm is None:
        errors.append("Could not parse frontmatter")
        return False, errors

    # Remove non-frontmatter keys
    fm_clean = {k: v for k, v in fm.items() if k != "body_preview"}
    errors.extend(rtype.validate_frontmatter(fm_clean))

    # Naming validation for skills
    if resource_type == "skill":
        name = fm_clean.get("name", "")
        if name:
            name_err = rtype.validate_name(name)
            if name_err:
                errors.append(name_err)
            if p.is_dir() and name != p.name:
                errors.append(f"Skill name '{name}' does not match folder name '{p.name}'")

    return len(errors) == 0, errors


# ── Index ────────────────────────────────────────────────────────────────────

def update_index() -> None:
    """Update the central index file."""
    ensure_dirs()
    resources = list_resources()

    index: Dict[str, Any] = {
        "version": "2.0",
        "central_dir": str(CENTRAL_DIR),
        "source_dir": str(SOURCE_DIR),
        "resource_count": len(resources),
        "resources": {},
    }

    for r in resources:
        rtype = r.get("type", "unknown")
        name = r.get("registered_name", r.get("name", "unknown"))
        key = f"{rtype}/{name}"
        index["resources"][key] = {
            "type": rtype,
            "name": r.get("name"),
            "description": str(r.get("description", ""))[:200],
            "path": r.get("path"),
        }

    INDEX_FILE.write_text(json.dumps(index, indent=2), encoding="utf-8")
