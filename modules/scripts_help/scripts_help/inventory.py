"""Runtime inventory for the structure-first scripts-help browser."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from scripts_help._repo_root import find_repo_root
from scripts_help.catalog import CATEGORY_SPECS, LONG_DESCRIPTIONS
from scripts_help.registry import EXCLUDED_SCRIPTS, REGISTRY


@dataclass(frozen=True)
class HelpItem:
    """One browsable repository item."""

    name: str
    path: str
    description: str
    long_description: str
    help_cmd: tuple[str, ...] | None = None
    version: str | None = None


@dataclass(frozen=True)
class HelpCategory:
    """Top-level structure category."""

    key: str
    title: str
    description: str
    items: tuple[HelpItem, ...]


_VERSION_RE = re.compile(r"""(?m)^\s*__version__\s*=\s*["']([^"']+)["']""")
_PROJECT_FIELD_RE = {
    "version": re.compile(r"""(?m)^\s*version\s*=\s*["']([^"']+)["']"""),
    "description": re.compile(r"""(?m)^\s*description\s*=\s*["']([^"']+)["']"""),
}


def _walk_registry() -> Iterable[dict]:
    def walk(node: dict) -> Iterable[dict]:
        yield from node.get("items", ())
        for sub in node.get("subcategories", {}).values():
            yield from walk(sub)

    for category in REGISTRY.values():
        yield from walk(category)


def registry_by_path() -> dict[str, dict]:
    """Return the existing semantic registry indexed by repo-relative path."""

    return {item["path"].replace("\\", "/"): item for item in _walk_registry()}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return ""


def _project_metadata(directory: Path) -> dict[str, str]:
    pyproject = directory / "pyproject.toml"
    text = _read_text(pyproject)
    if not text:
        return {}

    match = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", text)
    section = match.group(1) if match else ""
    result: dict[str, str] = {}
    for key, pattern in _PROJECT_FIELD_RE.items():
        found = pattern.search(section)
        if found:
            result[key] = found.group(1).strip()
    return result


def _project_scripts(directory: Path) -> tuple[str, ...]:
    """Return console-script names declared by a module's pyproject."""

    text = _read_text(directory / "pyproject.toml")
    if not text:
        return ()
    match = re.search(r"(?ms)^\[project\.scripts\]\s*(.*?)(?=^\[|\Z)", text)
    if not match:
        return ()

    names: list[str] = []
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip().strip('"').strip("'")
        if key:
            names.append(key)
    return tuple(names)


def _source_docstring(path: Path) -> str | None:
    text = _read_text(path)
    if not text:
        return None
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(text)
            value = ast.get_docstring(tree, clean=True)
            return " ".join(value.split()) if value else None
        except SyntaxError:
            return None

    lines = text.splitlines()
    collected: list[str] = []
    started = False
    for raw in lines[:60]:
        line = raw.strip()
        if line.startswith("#!"):
            continue
        if line.startswith("#"):
            body = line[1:].strip()
            if body:
                collected.append(body)
                started = True
            elif started:
                break
        elif started:
            break
        elif line:
            break
    return " ".join(collected) if collected else None


def _first_markdown_paragraph(path: Path) -> str | None:
    text = _read_text(path)
    if not text:
        return None

    paragraphs: list[str] = []
    current: list[str] = []
    in_fence = False
    fence = chr(96) * 3

    def flush() -> bool:
        if not current:
            return False
        paragraph = " ".join(part.strip() for part in current if part.strip()).strip()
        current.clear()
        if paragraph:
            paragraphs.append(paragraph)
            return True
        return False

    for raw in text.splitlines()[:160]:
        stripped = raw.strip()
        if stripped.startswith(fence) or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped:
            flush()
            if paragraphs:
                break
            continue
        if stripped.startswith("<!--"):
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith(("- ", "* ", "+ ", "|", ">")):
            if paragraphs or current:
                flush()
                break
            continue
        current.append(stripped)

    if not paragraphs:
        flush()
    if not paragraphs:
        return None

    paragraph = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", paragraphs[0])
    paragraph = paragraph.replace("**", "").replace("__", "").replace(chr(96), "")
    return " ".join(paragraph.split())


def _readme_for(relative: str, absolute: Path, repo: Path) -> Path | None:
    if absolute.is_dir():
        for name in ("README.md", "readme.md", "README.MD"):
            candidate = absolute / name
            if candidate.is_file():
                return candidate

    rel = Path(relative)
    if relative.startswith("pyscripts/") and rel.suffix.lower() == ".py":
        candidate = repo / "pyscripts" / "readme" / f"{rel.stem}.md"
        if candidate.is_file():
            return candidate
    return None


def _first_sentence(text: str, limit: int = 118) -> str:
    compact = " ".join(text.split())
    sentence = re.split(r"(?<=[.!?])\s+", compact, maxsplit=1)[0]
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 1].rstrip() + "…"


def _version_for(absolute: Path, registry_item: dict | None) -> str | None:
    # Prefer live metadata. The registry version intentionally lags when drift
    # is detected, so showing it first would make the detail page stale.
    if absolute.is_dir():
        project = _project_metadata(absolute)
        if project.get("version"):
            return project["version"]
        candidates = list(absolute.glob("*/__init__.py")) + [absolute / "__init__.py"]
    else:
        candidates = [absolute]

    for candidate in candidates:
        text = _read_text(candidate)
        match = _VERSION_RE.search(text)
        if match:
            return match.group(1)

    if registry_item and registry_item.get("version"):
        return str(registry_item["version"])
    return None


def _build_item(relative: str, repo: Path, index: dict[str, dict]) -> HelpItem:
    relative = relative.replace("\\", "/")
    absolute = repo / relative
    registered = index.get(relative)
    readme = _readme_for(relative, absolute, repo)
    readme_text = _first_markdown_paragraph(readme) if readme else None
    source_text = _source_docstring(absolute) if absolute.is_file() else None
    project = _project_metadata(absolute) if absolute.is_dir() else {}

    description = (
        str(registered.get("desc"))
        if registered and registered.get("desc")
        else project.get("description")
        or (readme_text and _first_sentence(readme_text))
        or (source_text and _first_sentence(source_text))
        or "No short description is currently available."
    )

    long_description = (
        LONG_DESCRIPTIONS.get(relative)
        or readme_text
        or source_text
        or description
    )

    help_cmd: tuple[str, ...] | None = None
    if registered and registered.get("help_cmd"):
        help_cmd = tuple(str(part) for part in registered["help_cmd"])
    elif relative == "help.py":
        help_cmd = ("python", "help.py", "--help")
    elif absolute.is_dir():
        scripts = _project_scripts(absolute)
        if scripts:
            help_cmd = (scripts[0], "--help")
    elif absolute.suffix.lower() == ".py":
        source = _read_text(absolute)
        cli_markers = ("argparse", "ArgumentParser(", "click.", "typer.")
        if "__main__" in source and any(marker in source for marker in cli_markers):
            help_cmd = ("python", relative, "--help")

    name = absolute.name
    if registered and registered.get("name"):
        registered_name = str(registered["name"])
        if registered_name.endswith(" (module)"):
            registered_name = registered_name[: -len(" (module)")]
        name = registered_name

    return HelpItem(
        name=name,
        path=relative,
        description=description,
        long_description=long_description,
        help_cmd=help_cmd,
        version=_version_for(absolute, registered),
    )


def _relative_paths(repo: Path, key: str) -> list[str]:
    if key == "modules":
        base = repo / "modules"
        if not base.is_dir():
            return []
        return [
            p.relative_to(repo).as_posix()
            for p in base.iterdir()
            if p.is_dir() and not p.name.startswith((".", "_")) and p.name != "__pycache__"
        ]

    if key == "pyscripts":
        base = repo / "pyscripts"
        if not base.is_dir():
            return []
        return [
            p.relative_to(repo).as_posix()
            for p in base.glob("*.py")
            if not p.name.startswith("_")
            and p.name != "__init__.py"
            and p.relative_to(repo).as_posix() not in EXCLUDED_SCRIPTS
        ]

    if key == "python":
        base = repo / "python"
        if not base.is_dir():
            return []
        return [
            p.relative_to(repo).as_posix()
            for p in base.glob("*.py")
            if not p.name.startswith("_")
        ]

    if key == "shell":
        paths = list(repo.glob("*.sh"))
        shell_dir = repo / "shell-scripts"
        if shell_dir.is_dir():
            paths.extend(shell_dir.rglob("*.sh"))
        return [p.relative_to(repo).as_posix() for p in paths if p.is_file()]

    if key == "powershell":
        paths = list(repo.glob("*.ps1"))
        for dirname in ("pwsh", "shell-scripts"):
            directory = repo / dirname
            if directory.is_dir():
                paths.extend(directory.rglob("*.ps1"))
        return [p.relative_to(repo).as_posix() for p in paths if p.is_file()]

    if key == "repo":
        return [
            p.relative_to(repo).as_posix()
            for p in repo.glob("*.py")
            if p.is_file() and p.name not in {"conftest.py"}
        ]

    if key == "pyprjs":
        base = repo / "pyprjs"
        if not base.is_dir():
            return []
        return [
            p.relative_to(repo).as_posix()
            for p in base.iterdir()
            if p.is_dir() and not p.name.startswith((".", "_"))
        ]

    return []


def build_categories(repo: Path | None = None) -> tuple[HelpCategory, ...]:
    """Discover the current repository and return top-level browser categories."""

    repo = repo or find_repo_root()
    index = registry_by_path()
    categories: list[HelpCategory] = []

    for key, title, description in CATEGORY_SPECS:
        paths = sorted(set(_relative_paths(repo, key)), key=str.casefold)
        items = tuple(_build_item(path, repo, index) for path in paths)
        if items:
            categories.append(
                HelpCategory(
                    key=key,
                    title=title,
                    description=description,
                    items=items,
                )
            )

    return tuple(categories)
