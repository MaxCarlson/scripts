"""Installation ownership for independently distributed shared libraries."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname


SHARED_DISTRIBUTION_REQUIREMENTS: dict[str, str] = {
    "mxc-resource-metrics": "mxc-resource-metrics>=0.3.0,<0.4",
    "mxc-script-logging": "mxc-script-logging>=0.1.1,<0.2",
    "mxc-web-ui-tools": "mxc-web-ui-tools>=0.2.0,<0.3",
    "mxc-termdash": "mxc-termdash>=0.10.0,<0.11",
    "mxc-platform-utils": "mxc-platform-utils>=0.9.0,<0.10",
}

SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION: dict[str, str] = {
    "resource_metrics": "mxc-resource-metrics",
    "script_logging": "mxc-script-logging",
    "web_ui_tools": "mxc-web-ui-tools",
    "termdash": "mxc-termdash",
    "cross_platform": "mxc-platform-utils",
}

LEGACY_SHARED_DISTRIBUTIONS: tuple[str, ...] = (
    "resource-metrics",
    "script-logging",
    "web-ui-tools",
    "termdash",
    "cross-platform",
)


def normalize_distribution_name(name: str) -> str:
    """Normalize a package name per PEP 503."""
    return "-".join(part for part in name.lower().replace("_", "-").replace(".", "-").split("-") if part)


def is_shared_module_dir(path_or_name: str | Path) -> bool:
    """Return whether a module path is one of the five shared library source copies."""
    name = Path(path_or_name).name
    return name in SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION


def is_shared_distribution(name: str | None) -> bool:
    """Return whether a normalized distribution name belongs to shared libraries."""
    if not name:
        return False
    expected = {normalize_distribution_name(value) for value in SHARED_DISTRIBUTION_REQUIREMENTS}
    return normalize_distribution_name(name) in expected


def is_shared_source_install(direct_url: Mapping[str, object] | None) -> bool:
    """Identify an installed shared package that points at a source directory."""
    if not direct_url or not isinstance(direct_url.get("dir_info"), Mapping):
        return False
    url = direct_url.get("url")
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    if parsed.scheme != "file":
        return False
    raw_path = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        raw_path = f"//{parsed.netloc}{raw_path}"
    source = Path(raw_path)
    if source.parent.name.lower() not in {"modules", "packages"}:
        return False
    normalized_source = normalize_distribution_name(source.name)
    shared_sources = {
        normalize_distribution_name(name) for name in SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION
    }
    shared_distributions = {
        normalize_distribution_name(name) for name in SHARED_DISTRIBUTION_REQUIREMENTS
    }
    return normalized_source in shared_sources | shared_distributions


def is_checkout_artifact_install(direct_url: Mapping[str, object] | None) -> bool:
    """Identify a shared distribution installed directly from either application checkout."""
    if not direct_url:
        return False
    url = direct_url.get("url")
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    if parsed.scheme != "file":
        return False
    raw_path = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        raw_path = f"//{parsed.netloc}{raw_path}"
    checkout_parts = {part.casefold() for part in Path(raw_path).parts}
    return bool(checkout_parts & {"llm-agent-toolkit", "shared-python-modules"})


def needs_shared_distribution_replacement(direct_url: Mapping[str, object] | None) -> bool:
    """Whether provenance points to a source copy or an application-owned compatibility artifact."""
    return is_shared_source_install(direct_url) or is_checkout_artifact_install(direct_url)


def _legacy_editable_consumer_paths(
    repository_root: Path,
    distributions: object | None = None,
) -> list[Path]:
    """Find installed scripts-owned editable packages whose metadata requires legacy names."""
    from scripts_setup.transferred_modules import is_transferred_module_dir

    source_distributions = distributions if distributions is not None else metadata.distributions()
    legacy_names = {normalize_distribution_name(name) for name in LEGACY_SHARED_DISTRIBUTIONS}
    candidates: set[Path] = set()
    for installed in source_distributions:
        requirements = installed.requires or ()
        has_legacy_requirement = any(
            match and normalize_distribution_name(match.group(1)) in legacy_names
            for requirement in requirements
            if (match := re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement))
        )
        if not has_legacy_requirement:
            continue

        raw_direct_url = installed.read_text("direct_url.json")
        if not raw_direct_url:
            continue
        try:
            direct_url = json.loads(raw_direct_url)
        except json.JSONDecodeError:
            continue
        if not isinstance(direct_url, Mapping) or not isinstance(direct_url.get("dir_info"), Mapping):
            continue
        if direct_url["dir_info"].get("editable") is not True:
            continue
        url = direct_url.get("url")
        if not isinstance(url, str) or urlsplit(url).scheme != "file":
            continue

        parsed = urlsplit(url)
        raw_path = url2pathname(unquote(parsed.path))
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            raw_path = f"//{parsed.netloc}{raw_path}"
        installed_source = Path(raw_path)
        if installed_source.parent.name.casefold() != "modules":
            continue

        module_name = installed_source.name
        if is_transferred_module_dir(module_name) or is_shared_module_dir(module_name):
            continue
        source_path = repository_root / "modules" / module_name
        project_file = source_path / "pyproject.toml"
        if not project_file.is_file():
            continue
        project_section = re.search(
            r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)",
            project_file.read_text(encoding="utf-8"),
        )
        if not project_section:
            continue
        project_name = re.search(r"(?m)^\s*name\s*=\s*['\"]([^'\"]+)['\"]", project_section.group(1))
        installed_name = installed.metadata.get("Name")
        if project_name and installed_name and normalize_distribution_name(project_name.group(1)) == normalize_distribution_name(installed_name):
            candidates.add(source_path)

    return sorted(candidates)


def _orphaned_worktree_legacy_consumers(
    repository_root: Path,
    distributions: object | None = None,
) -> list[str]:
    """Find editable packages installed from .worktrees that still require legacy shared names."""
    source_distributions = distributions if distributions is not None else metadata.distributions()
    legacy_names = {normalize_distribution_name(name) for name in LEGACY_SHARED_DISTRIBUTIONS}
    worktrees_root = (repository_root / ".worktrees").resolve()
    orphans: set[str] = set()
    for installed in source_distributions:
        requirements = installed.requires or ()
        has_legacy_requirement = any(
            match and normalize_distribution_name(match.group(1)) in legacy_names
            for requirement in requirements
            if (match := re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement))
        )
        if not has_legacy_requirement:
            continue
        raw_direct_url = installed.read_text("direct_url.json")
        if not raw_direct_url:
            continue
        try:
            direct_url = json.loads(raw_direct_url)
        except json.JSONDecodeError:
            continue
        if not isinstance(direct_url, Mapping) or not isinstance(direct_url.get("dir_info"), Mapping):
            continue
        if direct_url["dir_info"].get("editable") is not True:
            continue
        url = direct_url.get("url")
        if not isinstance(url, str) or urlsplit(url).scheme != "file":
            continue
        parsed = urlsplit(url)
        raw_path = url2pathname(unquote(parsed.path))
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            raw_path = f"//{parsed.netloc}{raw_path}"
        installed_source = Path(raw_path).resolve()
        if installed_source.is_relative_to(worktrees_root):
            name = installed.metadata.get("Name")
            if name:
                orphans.add(name)
    return sorted(orphans)


def ensure_shared_distributions(
    *,
    python: str | Path | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> bool:
    """Install compatible shared wheels and replace obsolete source-directory installs."""
    interpreter = str(python or sys.executable)
    failures: list[str] = []
    for legacy_distribution in LEGACY_SHARED_DISTRIBUTIONS:
        try:
            metadata.distribution(legacy_distribution)
        except metadata.PackageNotFoundError:
            continue
        if dry_run:
            print(f"[DRY RUN] Would replace legacy shared distribution: {legacy_distribution}")
            continue

        uninstall = subprocess.run(
            [interpreter, "-I", "-m", "pip", "uninstall", "-y", legacy_distribution],
            check=False,
            capture_output=not verbose,
            text=True,
        )
        if uninstall.returncode:
            print(f"[ERROR] Could not remove legacy shared distribution {legacy_distribution}", file=sys.stderr)
            if uninstall.stderr:
                print(uninstall.stderr, file=sys.stderr)
            failures.append(legacy_distribution)
        elif verbose:
            print(f"[INFO] Removed legacy shared distribution {legacy_distribution}")

    if failures:
        return False

    repository_root = Path(__file__).resolve().parents[1]
    legacy_consumers = [] if dry_run else _legacy_editable_consumer_paths(repository_root)
    orphaned_worktree_consumers = [] if dry_run else _orphaned_worktree_legacy_consumers(repository_root)

    for orphan_name in orphaned_worktree_consumers:
        uninstall = subprocess.run(
            [interpreter, "-I", "-m", "pip", "uninstall", "-y", orphan_name],
            check=False,
            capture_output=not verbose,
            text=True,
        )
        if uninstall.returncode:
            print(f"[ERROR] Could not remove orphaned worktree package {orphan_name}", file=sys.stderr)
            failures.append(orphan_name)
        else:
            print(f"[INFO] Removed orphaned worktree package {orphan_name} (requires legacy shared names)")

    for distribution, requirement in SHARED_DISTRIBUTION_REQUIREMENTS.items():
        try:
            installed = metadata.distribution(distribution)
        except metadata.PackageNotFoundError:
            installed = None

        if installed is not None:
            try:
                raw_direct_url = installed.read_text("direct_url.json")
                direct_url = json.loads(raw_direct_url) if raw_direct_url else None
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[ERROR] Cannot validate installed {distribution} provenance: {exc}", file=sys.stderr)
                failures.append(distribution)
                continue
            if needs_shared_distribution_replacement(direct_url):
                print(f"[INFO] Replacing checkout-local installation of {distribution} with its shared distribution wheel")
                if dry_run:
                    continue
                uninstall = subprocess.run(
                    [interpreter, "-I", "-m", "pip", "uninstall", "-y", distribution],
                    check=False,
                    capture_output=not verbose,
                    text=True,
                )
                if uninstall.returncode:
                    print(f"[ERROR] Could not remove the source-directory installation of {distribution}", file=sys.stderr)
                    if uninstall.stderr:
                        print(uninstall.stderr, file=sys.stderr)
                    failures.append(distribution)
                    continue

        if dry_run:
            if installed is None:
                print(f"[DRY RUN] Would install shared distribution: {requirement}")
            continue

        command = [interpreter, "-I", "-m", "pip", "install", "--no-input", "--disable-pip-version-check"]
        if not verbose:
            command.append("-q")
        command.append(requirement)
        result = subprocess.run(command, check=False, capture_output=not verbose, text=True)
        if result.returncode:
            print(f"[ERROR] Could not install shared distribution {requirement}", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            failures.append(distribution)
            continue

        try:
            installed = metadata.distribution(distribution)
            raw_direct_url = installed.read_text("direct_url.json")
            direct_url = json.loads(raw_direct_url) if raw_direct_url else None
            if needs_shared_distribution_replacement(direct_url):
                print(f"[ERROR] {distribution} still resolves to an application checkout after installation", file=sys.stderr)
                failures.append(distribution)
        except (metadata.PackageNotFoundError, OSError, json.JSONDecodeError) as exc:
            print(f"[ERROR] Could not validate installed {distribution}: {exc}", file=sys.stderr)
            failures.append(distribution)

    for consumer_path in legacy_consumers:
        refresh = subprocess.run(
            [
                interpreter,
                "-I",
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--editable",
                str(consumer_path),
            ],
            check=False,
            capture_output=not verbose,
            text=True,
        )
        if refresh.returncode:
            print(f"[ERROR] Could not refresh migrated dependency metadata for {consumer_path}", file=sys.stderr)
            if refresh.stderr:
                print(refresh.stderr, file=sys.stderr)
            failures.append(str(consumer_path))
        elif verbose:
            print(f"[INFO] Refreshed shared dependency metadata for {consumer_path}")

    if not dry_run and not failures:
        check = subprocess.run(
            [interpreter, "-I", "-m", "pip", "check"],
            check=False,
            capture_output=not verbose,
            text=True,
        )
        if check.returncode:
            print("[ERROR] Shared distribution dependency validation failed (pip check)", file=sys.stderr)
            if check.stdout:
                print(check.stdout, file=sys.stderr)
            if check.stderr:
                print(check.stderr, file=sys.stderr)
            failures.append("pip check")

    return not failures
