#!/usr/bin/env python3
"""Install only absent local packages and command launchers.

This deliberately does not call setup.py: the normal setup also refreshes
profiles, aliases, package versions, and launchers on a repeat run.
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - supported by the shell bootstraps
    import tomli as tomllib


ROOT = Path(__file__).resolve().parent
CORE = ("standard_ui", "cross_platform", "python_setup")


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def source_name(directory: Path) -> str | None:
    project_file = directory / "pyproject.toml"
    if project_file.is_file():
        with project_file.open("rb") as handle:
            data = tomllib.load(handle)
        name = data.get("project", {}).get("name") or data.get("tool", {}).get("poetry", {}).get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    setup_file = directory / "setup.py"
    if setup_file.is_file():
        match = re.search(r"\bname\s*=\s*['\"]([^'\"]+)['\"]", setup_file.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    return None


def package_sources(root: Path) -> tuple[list[tuple[str, Path]], list[Path]]:
    """Return unique package sources in core/dependency order and unknown metadata."""
    module_dir = root / "modules"
    candidates = [module_dir / name for name in CORE] + [root / "scripts_setup"]
    if module_dir.is_dir() and (module_dir / "setup_utils" / "dependency_resolver.py").is_file():
        resolver_path = module_dir / "setup_utils"
        sys.path.insert(0, str(resolver_path))
        try:
            from dependency_resolver import resolve_module_order

            order = resolve_module_order(module_dir)
        except (ImportError, ValueError) as exc:
            print(f"[WARN] Module dependency ordering failed ({exc}); using alphabetical order", file=sys.stderr)
            order = sorted(path.name for path in module_dir.iterdir() if path.is_dir() and not path.name.startswith("."))
        finally:
            sys.path.remove(str(resolver_path))
        candidates.extend(module_dir / name for name in order if name not in CORE)
    elif module_dir.is_dir():
        candidates.extend(sorted(path for path in module_dir.iterdir() if path.is_dir() and path.name not in CORE and not path.name.startswith(".")))
    pscripts_modules = root / "pscripts" / "modules"
    if pscripts_modules.is_dir():
        candidates.extend(sorted(path for path in pscripts_modules.iterdir() if path.is_dir() and not path.name.startswith(".")))

    seen: set[str] = set()
    sources: list[tuple[str, Path]] = []
    unknown: list[Path] = []
    for path in candidates:
        if not ((path / "pyproject.toml").is_file() or (path / "setup.py").is_file()):
            continue
        try:
            name = source_name(path)
        except (OSError, ValueError) as exc:
            print(f"[WARN] Cannot read package metadata for {path}: {exc}", file=sys.stderr)
            unknown.append(path)
            continue
        if not name:
            unknown.append(path)
            continue
        key = normalized(name)
        if key not in seen:
            seen.add(key)
            sources.append((name, path))
    return sources, unknown


def installed_names() -> set[str]:
    return {normalized(dist.metadata["Name"]) for dist in metadata.distributions() if dist.metadata.get("Name")}


def ensure_pscripts(root: Path, dry_run: bool) -> bool:
    """Initialize only an absent pscripts submodule; never update an existing one."""
    gitmodules = root / ".gitmodules"
    if not gitmodules.is_file() or 'path = pscripts' not in gitmodules.read_text(encoding="utf-8"):
        return True
    if (root / "pscripts" / "setup.py").is_file():
        return True
    if dry_run:
        print("[DRY RUN] Would initialize missing pscripts submodule")
        return True
    print("Initializing missing pscripts submodule")
    result = subprocess.run(["git", "-C", str(root), "submodule", "update", "--init", "--recursive", "--", "pscripts"], check=False)
    return result.returncode == 0 and (root / "pscripts" / "setup.py").is_file()


def launcher_sources(root: Path) -> list[tuple[Path, str]]:
    sources: list[tuple[Path, str]] = []
    for directory, suffix, kind in (
        (root / "pyscripts", "*.py", "python"),
        (root / "pscripts" / "pyscripts", "*.py", "python"),
        (root / "shell-scripts", "*.sh", "shell"),
    ):
        if directory.is_dir():
            sources.extend((path, kind) for path in sorted(directory.glob(suffix)) if path.name != "setup.py")
    return sources


def launcher_path(bin_dir: Path, name: str, windows: bool) -> Path:
    return bin_dir / (name + ".cmd" if windows else name)


def write_launcher(destination: Path, source: Path, kind: str, windows: bool, python: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not windows and kind == "shell":
        destination.symlink_to(source.resolve())
        return
    if windows:
        command = f'"{python}" "{source}" %*' if kind == "python" else f'bash "{source}" %*'
        destination.write_text(f"@echo off\n{command}\nexit /b %ERRORLEVEL%\n", encoding="utf-8")
    else:
        import shlex

        command = f"exec {shlex.quote(str(python))} {shlex.quote(str(source))} \"$@\""
        destination.write_text(f"#!/usr/bin/env bash\n{command}\n", encoding="utf-8")
        destination.chmod(0o755)


def console_scripts(package_names: list[str]) -> list[tuple[str, str]]:
    names: dict[str, str] = {}
    for package_name in package_names:
        try:
            dist = metadata.distribution(package_name)
        except metadata.PackageNotFoundError:
            continue
        owner = dist.metadata.get("Name") or package_name
        for entry_point in dist.entry_points:
            if entry_point.group == "console_scripts" and entry_point.name:
                names[entry_point.name] = owner
    return sorted(names.items())


def package_kind(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return "Python package"
    if relative.parts and relative.parts[0] == "modules":
        return "module"
    if relative.parts[:2] == ("pscripts", "modules"):
        return "pscripts module"
    if relative.parts and relative.parts[0] == "scripts_setup":
        return "setup utility"
    return "Python package"


def source_kind(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    if path.suffix.lower() == ".sh":
        return "shell script"
    if relative.parts[:2] == ("pscripts", "pyscripts"):
        return "pscripts Python script"
    return "Python script"


def write_console_proxy(destination: Path, name: str, windows: bool, venv_dir: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    target = venv_dir / ("Scripts" if windows else "bin") / (name + ".exe" if windows else name)
    if not target.is_file():
        raise FileNotFoundError(f"console entry point missing: {target}")
    if windows:
        destination.write_text(f'@echo off\n"{target}" %*\nexit /b %ERRORLEVEL%\n', encoding="utf-8")
    else:
        import shlex

        destination.write_text(f'#!/usr/bin/env bash\nexec {shlex.quote(str(target))} "$@"\n', encoding="utf-8")
        destination.chmod(0o755)


def run(root: Path, *, dry_run: bool = False, verbose: bool = False) -> int:
    if not ensure_pscripts(root, dry_run):
        print("[ERROR] pscripts submodule is missing and could not be initialized", file=sys.stderr)
        return 1
    sources, unknown = package_sources(root)
    present = installed_names()
    missing = [(name, path) for name, path in sources if normalized(name) not in present]
    print(f"Mode: {'dry run' if dry_run else 'install missing only'}")
    print(f"Python: {sys.executable}")
    print(f"Packages: {len(sources)} found, {len(missing)} missing, {len(unknown)} with unreadable/unknown names")
    print("Package inventory:")
    for name, path in sources:
        state = "missing; will install" if normalized(name) not in present else "already installed"
        print(f"  [{state}] {package_kind(path, root)}: {name} ({path.relative_to(root)})")
    for path in unknown:
        print(f"[WARN] Skipped unknown package name: {path}")

    failures = 0
    for name, path in missing:
        verb = "Would install" if dry_run else "Installing"
        print(f"{verb} {package_kind(path, root)}: {name} ({path.relative_to(root)})")
        if dry_run:
            continue
        requirements = path / "requirements.txt"
        if requirements.is_file() and (path.parent == root / "pscripts" / "modules" or not (path / "pyproject.toml").is_file()):
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", "-r", str(requirements)],
                check=False,
            )
            if result.returncode:
                failures += 1
                print(f"[ERROR] {name}: requirements install exited {result.returncode}", file=sys.stderr)
                continue
        command = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", "-e", str(path)]
        if verbose:
            print("  " + subprocess.list2cmdline(command))
        result = subprocess.run(command, check=False)
        if result.returncode:
            failures += 1
            print(f"[ERROR] {name}: pip exited {result.returncode}", file=sys.stderr)

    windows = os.name == "nt"
    bin_dir = root / "bin"
    venv_dir = root / ".venv"
    created = 0
    existing = 0
    script_sources = launcher_sources(root)
    source_counts: dict[str, int] = {}
    missing_script_count = 0
    for source, _kind in script_sources:
        label = source_kind(source, root)
        source_counts[label] = source_counts.get(label, 0) + 1
        destination = launcher_path(bin_dir, source.stem, windows)
        if not destination.exists() and not destination.is_symlink():
            missing_script_count += 1
    print(f"Script launchers: {len(script_sources)} found, {missing_script_count} missing")
    for label, count in sorted(source_counts.items()):
        print(f"  {label}: {count}")
    for source, kind in script_sources:
        destination = launcher_path(bin_dir, source.stem, windows)
        label = source_kind(source, root)
        if destination.exists() or destination.is_symlink():
            existing += 1
            continue
        verb = "Would create" if dry_run else "Creating"
        print(f"{verb} {label} launcher: {source.stem} ({source.relative_to(root)}) -> {destination}")
        if not dry_run:
            try:
                write_launcher(destination, source, kind, windows, Path(sys.executable))
            except OSError as exc:
                failures += 1
                print(f"[ERROR] {destination}: {exc}", file=sys.stderr)
                continue
        created += 1

    # New pip installations provide entry points before this call. In dry run,
    # absent distributions cannot be inspected, so their future proxies are unknown.
    local_sources = {normalized(name): path for name, path in sources}
    console_inventory: dict[str, tuple[str, list[str]]] = {}
    missing_console: list[tuple[str, str, Path | None, Path]] = []
    console_count = 0
    for name, owner in console_scripts([name for name, _ in sources]):
        console_count += 1
        owner_key = normalized(owner)
        owner_path = local_sources.get(owner_key)
        owner_description = (
            f"{package_kind(owner_path, root)} {owner} ({owner_path.relative_to(root)})"
            if owner_path is not None
            else f"package {owner}"
        )
        destination = launcher_path(bin_dir, name, windows)
        missing_proxy = not destination.exists() and not destination.is_symlink()
        group = console_inventory.setdefault(owner_key, (owner_description, []))[1]
        group.append(name + (" [missing proxy]" if missing_proxy else ""))
        if missing_proxy:
            missing_console.append((name, owner, owner_path, destination))
        else:
            existing += 1
    print(f"Console commands: {console_count} found, {len(missing_console)} missing proxies")
    for owner_description, commands in sorted(console_inventory.values(), key=lambda item: item[0].lower()):
        print(f"  {owner_description}: {', '.join(sorted(commands))}")

    for name, owner, owner_path, destination in missing_console:
        owner_description = (
            f"{package_kind(owner_path, root)} {owner} ({owner_path.relative_to(root)})"
            if owner_path is not None
            else f"package {owner}"
        )
        verb = "Would create" if dry_run else "Creating"
        print(f"{verb} console command '{name}' from {owner_description}: {destination}")
        if not dry_run:
            try:
                write_console_proxy(destination, name, windows, venv_dir)
            except OSError as exc:
                failures += 1
                print(f"[ERROR] {destination}: {exc}", file=sys.stderr)
                continue
        created += 1

    print(f"Summary: {len(missing)} missing package(s), {created} missing launcher(s), {existing} existing launcher(s), {failures} failure(s)")
    return 1 if failures or unknown else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show missing installations without changing files")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    return run(ROOT, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
