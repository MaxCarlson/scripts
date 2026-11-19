"""Installation ownership for independently distributed shared libraries."""
from __future__ import annotations

import json
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname


SHARED_DISTRIBUTION_REQUIREMENTS: dict[str, str] = {
    "resource-metrics": "resource-metrics>=0.3.0,<0.4",
    "script-logging": "script-logging>=0.1.1,<0.2",
    "web-ui-tools": "web-ui-tools>=0.2.0,<0.3",
    "termdash": "termdash>=0.10.0,<0.11",
    "cross-platform": "cross-platform>=0.9.0,<0.10",
}

SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION: dict[str, str] = {
    "resource_metrics": "resource-metrics",
    "script_logging": "script-logging",
    "web_ui_tools": "web-ui-tools",
    "termdash": "termdash",
    "cross_platform": "cross-platform",
}


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
    return normalized_source in {
        normalize_distribution_name(name) for name in SHARED_DISTRIBUTION_REQUIREMENTS
    }


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


def ensure_shared_distributions(
    *,
    python: str | Path | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> bool:
    """Install compatible shared wheels and replace obsolete source-directory installs."""
    interpreter = str(python or sys.executable)
    failures: list[str] = []

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
