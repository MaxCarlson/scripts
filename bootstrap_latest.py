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
import time
from contextlib import nullcontext
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - supported by the shell bootstraps
    import tomli as tomllib


ROOT = Path(__file__).resolve().parent
CORE = ("standard_ui", "python_setup")
_LOCAL_REPO_BOOTSTRAP = ROOT.parent / "shared-python-modules" / "packages" / "repo-bootstrap" / "src"
if _LOCAL_REPO_BOOTSTRAP.is_dir() and str(_LOCAL_REPO_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_LOCAL_REPO_BOOTSTRAP))


def _make_ui(verbose: bool):
    try:
        from repo_bootstrap.console_ui import ConsoleUI, format_duration
        return ConsoleUI(verbose=verbose), format_duration
    except ImportError:
        class _FallbackUI:
            class _Glyphs:
                ok = "+"
                info = "i"
                warn = "!"
                fail = "x"
                bullet = "*"
                rule = "-"

            glyphs = _Glyphs()

            def style(self, text: str, _role: str | None = None) -> str:
                return text

            def write(self, text: str = "") -> None:
                print(text)

            def rule(self, _role: str = "muted") -> None:
                print("-" * 76)

            def header(self, title: str, subtitle: str) -> None:
                print(f"{title}  {subtitle}")
                self.rule()

            def kv(self, key: str, value: str, **_kw) -> None:
                print(f"{key:<19}{value}")

            def status_row(self, state: str, label: str, detail: str, *, elapsed: float | None = None) -> None:
                icon = {"ok": "+", "info": "i", "warn": "!", "fail": "x"}.get(state, "*")
                suffix = f" ({elapsed:.1f}s)" if elapsed is not None and elapsed >= 0.25 else ""
                print(f"{icon} {label:<17}{detail}{suffix}")

            def verbose_note(self, message: str, **_kw) -> None:
                if verbose:
                    print(f"  {message}")

            def spinner_step(self, _label: str):
                return nullcontext(type("Step", (), {"elapsed": 0.0})())

        def _fmt(seconds: float) -> str:
            return f"{seconds:.1f}s"

        return _FallbackUI(), _fmt


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


def source_version(directory: Path) -> str | None:
    """Return the source distribution version when its metadata declares one."""
    project_file = directory / "pyproject.toml"
    if project_file.is_file():
        with project_file.open("rb") as handle:
            version = tomllib.load(handle).get("project", {}).get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    setup_file = directory / "setup.py"
    if setup_file.is_file():
        match = re.search(r"\bversion\s*=\s*['\"]([^'\"]+)['\"]", setup_file.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    return None


def package_sources(root: Path) -> tuple[list[tuple[str, Path]], list[Path]]:
    """Return unique package sources in core/dependency order and unknown metadata."""
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from scripts_setup.transferred_modules import (
            is_transferred_distribution,
            is_transferred_module_dir,
        )
        from scripts_setup.shared_packages import is_shared_distribution, is_shared_module_dir
    except ImportError:
        is_transferred_module_dir = lambda _p: False  # noqa: E731
        is_transferred_distribution = lambda _d: False  # noqa: E731
        is_shared_module_dir = lambda _p: False  # noqa: E731
        is_shared_distribution = lambda _d: False  # noqa: E731

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
        candidates.extend(
            module_dir / name for name in order
            if name not in CORE and not is_transferred_module_dir(name) and not is_shared_module_dir(name)
        )
    elif module_dir.is_dir():
        candidates.extend(
            sorted(
                path for path in module_dir.iterdir()
                if path.is_dir()
                and path.name not in CORE
                and not path.name.startswith(".")
                and not is_transferred_module_dir(path)
                and not is_shared_module_dir(path)
            )
        )
    pscripts_modules = root / "pscripts" / "modules"
    if pscripts_modules.is_dir():
        candidates.extend(sorted(path for path in pscripts_modules.iterdir() if path.is_dir() and not path.name.startswith(".")))

    canonical_aebndl = [root / "modules" / "aebndl_module", pscripts_modules / "aebndl_module"]
    has_canonical_aebndl = any(source_name(path) == "aebndl" for path in canonical_aebndl if path.is_dir())

    seen: set[str] = set()
    sources: list[tuple[str, Path]] = []
    unknown: list[Path] = []
    for path in candidates:
        if path.parent == module_dir and (is_transferred_module_dir(path) or is_shared_module_dir(path)):
            continue
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
        if normalized(name) == "aebndl" and has_canonical_aebndl and path.name != "aebndl_module":
            continue
        if path.parent == module_dir and (is_transferred_distribution(name) or is_shared_distribution(name)):
            continue
        key = normalized(name)
        if key not in seen:
            seen.add(key)
            sources.append((name, path))
    return sources, unknown


def installed_names() -> set[str]:
    return {normalized(dist.metadata["Name"]) for dist in metadata.distributions() if dist.metadata.get("Name")}


def installed_versions() -> dict[str, str]:
    """Return normalized distribution names and their installed versions."""
    versions: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        version = dist.version
        if name and version:
            versions[normalized(name)] = version
    return versions


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
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from scripts_setup.transferred_modules import (
            is_transferred_cli_command,
            is_transferred_distribution,
        )
    except ImportError:
        is_transferred_distribution = lambda _d: False  # noqa: E731
        is_transferred_cli_command = lambda _c: False  # noqa: E731

    names: dict[str, tuple[str, str]] = {}
    for package_name in package_names:
        if is_transferred_distribution(package_name):
            continue
        try:
            dist = metadata.distribution(package_name)
        except metadata.PackageNotFoundError:
            continue
        owner = dist.metadata.get("Name") or package_name
        if is_transferred_distribution(owner):
            continue
        for entry_point in dist.entry_points:
            if (
                entry_point.group == "console_scripts"
                and entry_point.name
                and not is_transferred_cli_command(entry_point.name)
            ):
                key = entry_point.name.casefold()
                previous = names.get(key)
                if previous and normalized(previous[1]) != normalized(owner):
                    raise ValueError(
                        f"Console command '{entry_point.name}' is declared by both "
                        f"'{previous[1]}' and '{owner}'"
                    )
                names[key] = (entry_point.name, owner)
    return sorted(names.values())


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


def write_console_proxy(
    destination: Path,
    name: str,
    windows: bool,
    venv_dir: Path,
    *,
    overwrite_legacy: bool = False,
) -> None:
    if destination.exists() or destination.is_symlink():
        if not overwrite_legacy:
            if str(destination.parent.parent) not in sys.path:
                sys.path.insert(0, str(destination.parent.parent))
            try:
                from scripts_setup.launcher_generator import is_managed_wrapper
            except ImportError:
                is_managed_wrapper = lambda _path: False  # noqa: E731
            if not is_managed_wrapper(destination):
                raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    target = venv_dir / ("Scripts" if windows else "bin") / (name + ".exe" if windows else name)
    if not target.is_file():
        raise FileNotFoundError(f"console entry point missing: {target}")

    repo_root = destination.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from scripts_setup.launcher_generator import generate_windows_wrapper, generate_posix_wrapper
        if windows:
            content = generate_windows_wrapper(name).replace("\r\n", "\n")
            destination.write_text(content, encoding="utf-8", newline="\r\n")
        else:
            content = generate_posix_wrapper(name).replace("\r\n", "\n")
            destination.write_text(content, encoding="utf-8", newline="\n")
            try:
                destination.chmod(0o755)
            except Exception:
                pass
    except ImportError:
        if windows:
            destination.write_text(f'@echo off\n"{target}" %*\nexit /b %ERRORLEVEL%\n', encoding="utf-8")
        else:
            import shlex

            destination.write_text(f'#!/usr/bin/env bash\nexec {shlex.quote(str(target))} "$@"\n', encoding="utf-8")
            try:
                destination.chmod(0o755)
            except Exception:
                pass


def run(root: Path, *, dry_run: bool = False, verbose: bool = False) -> int:
    total_start = time.monotonic()
    ui, fmt_duration = _make_ui(verbose)
    g = ui.glyphs

    ui.header("Scripts", "Bootstrap")
    ui.kv("Mode", "dry-run" if dry_run else f"editable {g.bullet} missing-only")
    ver_info = getattr(sys, "version_info", None)
    py_ver = f"{ver_info.major}.{ver_info.minor}.{ver_info.micro}" if ver_info else str(sys.executable)
    ui.kv("Python", py_ver)
    ui.kv("Environment", str(root / ".venv") if verbose else ".venv")
    ui.write("")

    if not ensure_pscripts(root, dry_run):
        print("[ERROR] pscripts submodule is missing and could not be initialized", file=sys.stderr)
        ui.status_row("fail", "Submodules", "pscripts submodule is missing and could not be initialized")
        return 1
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from scripts_setup.shared_packages import (
            SHARED_DISTRIBUTION_REQUIREMENTS,
            ensure_shared_distributions,
        )
    except ImportError as exc:
        ui.status_row("fail", "Shared packages", f"installer unavailable: {exc}")
        return 1
    with ui.spinner_step("Checking shared distributions") as shared_step:
        shared_ok = ensure_shared_distributions(dry_run=dry_run, verbose=verbose)
    if not shared_ok:
        ui.status_row("fail", "Shared packages", "installation or validation failed", elapsed=shared_step.elapsed)
        return 1
    ui.status_row(
        "ok",
        "Shared packages",
        f"{len(SHARED_DISTRIBUTION_REQUIREMENTS)}/{len(SHARED_DISTRIBUTION_REQUIREMENTS)} verified",
        elapsed=shared_step.elapsed,
    )

    sources, unknown = package_sources(root)
    present = installed_versions()
    missing = [
        (name, path)
        for name, path in sources
        if normalized(name) not in present
        or (source_version(path) is not None and present[normalized(name)] != source_version(path))
    ]
    if verbose:
        for name, path in sources:
            installed = present.get(normalized(name))
            source = source_version(path)
            state = "missing; will install" if installed is None else (
                f"version {installed} installed; source {source}; will upgrade" if source and installed != source else "already installed"
            )
            ui.verbose_note(f"[{state}] {package_kind(path, root)}: {name} ({path.relative_to(root)})")
    for path in unknown:
        ui.status_row("warn", "Unknown package", str(path))

    failures = 0
    installed_count = 0
    pkg_start = time.monotonic()
    for name, path in missing:
        if dry_run:
            ui.verbose_note(f"Would install {package_kind(path, root)}: {name} ({path.relative_to(root)})")
            continue
        with ui.spinner_step(f"Installing {name}"):
            requirements = path / "requirements.txt"
            if requirements.is_file() and (path.parent == root / "pscripts" / "modules" or not (path / "pyproject.toml").is_file()):
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", "-r", str(requirements)],
                    check=False,
                    capture_output=not verbose,
                    text=True,
                )
                if result.returncode:
                    failures += 1
                    ui.status_row("fail", name, f"requirements install exited {result.returncode}")
                    continue
            command = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", "-e", str(path)]
            if verbose:
                ui.verbose_note(subprocess.list2cmdline(command))
            result = subprocess.run(command, check=False, capture_output=not verbose, text=True)
            if result.returncode:
                failures += 1
                ui.status_row("fail", name, f"pip exited {result.returncode}")
            else:
                installed_count += 1
    pkg_elapsed = time.monotonic() - pkg_start
    unchanged_count = len(sources) - len(missing)
    if dry_run:
        ui.status_row(
            "ok" if not missing else "info",
            "Local packages",
            f"{unchanged_count}/{len(sources)} ready {g.bullet} {len(missing)} to install",
        )
    elif failures == 0:
        detail = f"{len(sources)}/{len(sources)} ready {g.bullet} {installed_count} installed, {unchanged_count} unchanged"
        ui.status_row("ok", "Local packages", detail, elapsed=pkg_elapsed)
    else:
        ui.status_row("fail", "Local packages", f"{installed_count} installed, {failures} failed", elapsed=pkg_elapsed)

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
    ui.verbose_note(f"Script launchers: {len(script_sources)} found, {missing_script_count} missing")
    for label, count in sorted(source_counts.items()):
        ui.verbose_note(f"  {label}: {count}")
    for source, kind in script_sources:
        destination = launcher_path(bin_dir, source.stem, windows)
        label = source_kind(source, root)
        if destination.exists() or destination.is_symlink():
            existing += 1
            continue
        verb = "Would create" if dry_run else "Creating"
        ui.verbose_note(f"{verb} {label} launcher: {source.stem} ({source.relative_to(root)}) -> {destination}")
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
    missing_console: list[tuple[str, str, Path | None, Path, bool]] = []
    console_count = 0
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from scripts_setup.launcher_generator import classify_vm_launcher
    except ImportError:
        classify_vm_launcher = None  # type: ignore[assignment]

    shared_names = list(SHARED_DISTRIBUTION_REQUIREMENTS)
    try:
        discovered_console_scripts = console_scripts([name for name, _ in sources] + shared_names)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        failures += 1
        discovered_console_scripts = []

    for name, owner in discovered_console_scripts:
        console_count += 1
        owner_key = normalized(owner)
        owner_path = local_sources.get(owner_key)
        owner_description = (
            f"{package_kind(owner_path, root)} {owner} ({owner_path.relative_to(root)})"
            if owner_path is not None
            else f"package {owner}"
        )
        destination = launcher_path(bin_dir, name, windows)
        exists = destination.exists() or destination.is_symlink()
        migrate_legacy = False
        managed_stale = False
        unmanaged_existing = False
        if exists and classify_vm_launcher is not None:
            try:
                from scripts_setup.launcher_generator import classify_wrapper, generate_windows_wrapper, generate_posix_wrapper
                classification = classify_wrapper(destination)
                if classification.status == "unmanaged":
                    unmanaged_existing = True
                    print(f"[WARN] Preserving unmanaged launcher at {destination}; not overwriting.")
                else:
                    expected = generate_windows_wrapper(name) if windows else generate_posix_wrapper(name)
                    current = destination.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
                    managed_stale = current != expected.replace("\r\n", "\n")
            except (OSError, ImportError):
                pass
        if exists and name in {"vm", "vm-lab"} and classify_vm_launcher is not None:
            cls = classify_vm_launcher(destination)
            if cls == "legacy_vm_lab_powershell":
                migrate_legacy = True
            elif cls in {"unmanaged", "ambiguous"}:
                print(f"[WARN] Preserving {cls} launcher at {destination}; not overwriting.")
        missing_proxy = (not exists) or migrate_legacy or managed_stale
        group = console_inventory.setdefault(owner_key, (owner_description, []))[1]
        tag = " [migrate legacy]" if migrate_legacy else (" [missing proxy]" if not exists else (" [repair stale]" if managed_stale else ""))
        group.append(name + tag)
        if missing_proxy and not unmanaged_existing:
            missing_console.append((name, owner, owner_path, destination, migrate_legacy))
        elif not missing_proxy or unmanaged_existing:
            existing += 1
    ui.verbose_note(f"Console commands: {console_count} found, {len(missing_console)} missing proxies")
    for owner_description, commands in sorted(console_inventory.values(), key=lambda item: item[0].lower()):
        ui.verbose_note(f"  {owner_description}: {', '.join(sorted(commands))}")

    for name, owner, owner_path, destination, migrate_legacy in missing_console:
        owner_description = (
            f"{package_kind(owner_path, root)} {owner} ({owner_path.relative_to(root)})"
            if owner_path is not None
            else f"package {owner}"
        )
        if migrate_legacy:
            verb = "Would migrate legacy launcher" if dry_run else "Migrating legacy launcher"
        else:
            verb = "Would create" if dry_run else "Creating"
        ui.verbose_note(f"{verb} console command '{name}' from {owner_description}: {destination}")
        if not dry_run:
            try:
                write_console_proxy(destination, name, windows, venv_dir, overwrite_legacy=migrate_legacy)
            except OSError as exc:
                failures += 1
                print(f"[ERROR] {destination}: {exc}", file=sys.stderr)
                continue
        created += 1

    if not dry_run and created > 0:
        try:
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from scripts_setup.launcher_generator import generate_manifest
            generate_manifest(root)
        except Exception as exc:
            if verbose:
                print(f"[WARN] Failed to regenerate manifest: {exc}", file=sys.stderr)

    total_elapsed = time.monotonic() - total_start
    total_launchers = len(script_sources) + console_count
    ui.status_row(
        "ok" if failures == 0 else "fail",
        "CLI launchers",
        f"{total_launchers}/{total_launchers} ready {g.bullet} {created} created, {existing} unchanged",
    )
    ui.write("")
    ui.rule("muted")
    if failures or unknown:
        ui.write(ui.style(f"{g.fail} Bootstrap finished with {failures} failure(s)", "bold_red"))
    elif dry_run:
        ui.write(ui.style("Dry run: no changes made.", "muted"))
    else:
        ui.write(ui.style(f"{g.ok} Bootstrap completed successfully", "bold_green"))
    ui.write("")
    ui.write(
        ui.style(
            f"{unchanged_count} packages unchanged {g.bullet} "
            f"{total_launchers} launchers ready {g.bullet} "
            f"{len(missing)} package update(s) {g.bullet} {fmt_duration(total_elapsed)}",
            "muted",
        )
    )
    return 1 if failures or unknown else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show missing installations without changing files")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    return run(ROOT, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
