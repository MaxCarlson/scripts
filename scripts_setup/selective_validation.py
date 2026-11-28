"""Focused pytest execution using existing environments and immutable run evidence."""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any, Callable, Iterable, Sequence


class SelectiveValidationError(RuntimeError):
    """A selection or environment failed closed before pytest execution."""


MAX_SELECTIVE_WORKERS = 16

_XDIST_VALUE_OPTIONS = {
    "-n", "--numprocesses", "--maxprocesses", "--dist",
    "--max-worker-restart", "--max-slave-restart", "--basetemp", "--rsyncdir",
}
_XDIST_FLAG_OPTIONS = {"-d", "--no-rsync"}
_REMOTE_XDIST_OPTIONS = {"--tx", "--looponfail", "-f", "--rsyncdir", "--no-rsync"}


def _worker_id_sort_key(worker_id: str) -> tuple[int, int | str]:
    if worker_id == "main":
        return (-1, 0)
    match = re.fullmatch(r"gw(\d+)", worker_id)
    if match:
        return (0, int(match.group(1)))
    return (1, worker_id)


def _native_pytest_addopts(interpreter: str, target_root: Path, selection: list[str], inherited: str | None) -> list[str]:
    """Read the selected pytest config's addopts using pytest's own discovery."""
    inherited_options = shlex.split(inherited or "")
    probe = "\n".join([
        "import json, pathlib",
        "from _pytest.config import get_config",
        "from _pytest.config.findpaths import determine_setup",
        f"options = json.loads({json.dumps(json.dumps(inherited_options))})",
        f"selection = json.loads({json.dumps(json.dumps(selection))})",
        "config = get_config()",
        "namespace = config._parser.parse_known_args(options)",
        "rootpath, inipath, inicfg, _ = determine_setup(",
        "    inifile=namespace.inifilename, override_ini=namespace.override_ini,",
        "    args=selection, rootdir_cmd_arg=namespace.rootdir or None,",
        "    invocation_dir=pathlib.Path.cwd(),",
        ")",
        "config._rootpath, config._inipath, config._inicfg = rootpath, inipath, inicfg",
        "config._parser.addini('addopts', 'Extra command line options', 'args')",
        "print('SCRIPTS_PYTEST_ADDOPTS=' + json.dumps(config.getini('addopts'))) ",
        "config._ensure_unconfigure()",
    ])
    environment = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "PYTEST_ADDOPTS"):
        environment.pop(key, None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [interpreter, "-c", probe], cwd=target_root, env=environment,
        capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(f"pytest configuration discovery failed ({result.returncode}): {detail}")
    marker = "SCRIPTS_PYTEST_ADDOPTS="
    lines = [line[len(marker):] for line in result.stdout.splitlines() if line.startswith(marker)]
    if len(lines) != 1:
        raise ValueError("selected pytest did not return one native addopts configuration result")
    configured = json.loads(lines[0])
    if not isinstance(configured, list) or any(not isinstance(value, str) for value in configured):
        raise ValueError("selected pytest returned an invalid addopts list")
    return [*configured, *inherited_options]


def _pytest_addopts(values: Sequence[str]) -> list[str]:
    """Remove runner-owned xdist/temp options and reject remote execution modes."""
    result: list[str] = []
    index = 0
    while index < len(values):
        value = values[index]
        option = value.split("=", 1)[0]
        if option in _REMOTE_XDIST_OPTIONS:
            raise ValueError(f"prohibited remote or repeated xdist execution option: {option}")
        if value in {"-o", "--override-ini"}:
            override = values[index + 1] if index + 1 < len(values) else ""
            if override.split("=", 1)[0].casefold() == "addopts":
                index += 2
                continue
            result.extend((value, override))
            index += 2
            continue
        if value.startswith(("-o", "--override-ini=")):
            override = value[2:] if value.startswith("-o") else value.split("=", 1)[1]
            if override.split("=", 1)[0].casefold() == "addopts":
                index += 1
                continue
        if value in _XDIST_FLAG_OPTIONS:
            index += 1
            continue
        if value in _XDIST_VALUE_OPTIONS:
            index += 2
            continue
        if value.startswith(("--numprocesses=", "--maxprocesses=", "--dist=", "--max-worker-restart=", "--max-slave-restart=", "--basetemp=", "--rsyncdir=")) or (value.startswith("-n") and len(value) > 2):
            index += 1
            continue
        result.append(value)
        index += 1
    return result


def _contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _selection_path(raw_path: str, target_root: Path) -> Path:
    supplied = Path(raw_path)
    path = supplied if supplied.is_absolute() else target_root / supplied
    resolved = path.resolve()
    if not _contained(resolved, target_root):
        raise ValueError(f"pytest selector must remain inside the target: {raw_path}")
    return resolved


def resolve_pytest_selectors(
    target_root: Path,
    test_roots: Sequence[str],
    node_ids: Sequence[str] = (),
    files: Sequence[str] = (),
    modules: Sequence[str] = (),
) -> list[str]:
    """Resolve repeatable node IDs, files/directories, and dotted test modules."""
    root = target_root.resolve()
    if not root.is_dir():
        raise ValueError(f"pytest target root does not exist: {root}")
    resolved_test_roots = []
    for item in test_roots:
        test_root = _selection_path(item, root)
        if not test_root.is_dir():
            raise ValueError(f"configured pytest test root is missing: {item}")
        resolved_test_roots.append(test_root)
    if not resolved_test_roots:
        raise ValueError("selective target has no configured test_roots")

    selected: list[str] = []

    def add_file(path: Path, *, allow_directory: bool, suffix: str = "") -> None:
        if not path.exists():
            raise ValueError(f"pytest selector does not exist: {path}")
        if not any(_contained(path, test_root) for test_root in resolved_test_roots):
            raise ValueError(f"pytest selector must be inside a configured test root: {path}")
        if path.is_dir():
            if not allow_directory:
                raise ValueError(f"pytest node ID must name a test file: {path}")
        elif path.suffix != ".py":
            raise ValueError(f"pytest selector must be a Python test file: {path}")
        selected.append(_relative_posix(path, root) + suffix)

    for node_id in node_ids:
        if not node_id or "\x00" in node_id:
            raise ValueError("pytest node IDs must be non-empty")
        path_text, separator, test_parts = node_id.partition("::")
        if not path_text or (separator and any(not part for part in test_parts.split("::"))):
            raise ValueError(f"invalid pytest node ID: {node_id}")
        node_path = _selection_path(path_text, root)
        add_file(node_path, allow_directory=False, suffix=("::" + test_parts if separator else ""))

    for file_name in files:
        if not file_name:
            raise ValueError("pytest files must be non-empty")
        add_file(_selection_path(file_name, root), allow_directory=True)

    for module_name in modules:
        parts = module_name.split(".")
        if not module_name or any(not part.isidentifier() for part in parts):
            raise ValueError(f"invalid dotted pytest module name: {module_name}")
        candidates: list[Path] = []
        dotted_path = Path(*parts)
        for test_root in resolved_test_roots:
            if parts[0] == test_root.name:
                relative_parts = parts[1:]
                if relative_parts:
                    candidates.append(test_root.joinpath(*relative_parts).with_suffix(".py"))
                    candidates.append(test_root.joinpath(*relative_parts, "__init__.py"))
            else:
                candidates.append(test_root.joinpath(*parts).with_suffix(".py"))
                candidates.append(test_root.joinpath(*parts, "__init__.py"))
        candidates.extend((root / dotted_path.with_suffix(".py"), root / dotted_path / "__init__.py"))
        resolved = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
        if resolved is None:
            raise ValueError(f"pytest module was not found under configured test roots: {module_name}")
        add_file(resolved, allow_directory=False)

    if not selected:
        raise ValueError("select at least one pytest node ID, file, or module")
    return list(dict.fromkeys(selected))


def assess_import_provenance(
    repo_root: Path,
    target_root: Path,
    import_specs: Sequence[dict[str, Any]],
    observed_imports: Sequence[dict[str, Any]],
    forbidden_roots: Sequence[str] = (),
    site_packages: Sequence[str] = (),
) -> dict[str, Any]:
    """Ensure selected imports resolve to this target or its declared distribution."""
    repository = repo_root.resolve()
    target = target_root.resolve()
    observed_by_name = {str(item.get("module")): item for item in observed_imports}
    forbidden = [(item, (repository / item).resolve()) for item in forbidden_roots]
    errors: list[str] = []
    warnings: list[str] = []
    identities: list[dict[str, Any]] = []

    for name, path in forbidden:
        if path.exists():
            errors.append(f"retired source copy is present: {name} ({path})")

    for spec in import_specs:
        module_name = str(spec.get("module", ""))
        observed = observed_by_name.get(module_name)
        if not observed or observed.get("error"):
            detail = observed.get("error") if observed else "module was not probed"
            errors.append(f"import {module_name}: {detail}")
            continue

        raw_paths = []
        if observed.get("origin") and observed["origin"] not in {"built-in", "frozen"}:
            raw_paths.append(observed["origin"])
        raw_paths.extend(observed.get("search_locations", []))
        paths = [Path(item).resolve() for item in raw_paths]
        if not paths:
            errors.append(f"import {module_name}: no filesystem origin was reported")
            continue

        expected_root = str(spec.get("expected_root", "."))
        if expected_root == "site-packages":
            allowed_roots = [Path(path).resolve() for path in site_packages]
        else:
            allowed_roots = [(target / expected_root).resolve()]
        outside = [
            path for path in paths
            if not any(_contained(path, allowed_root) for allowed_root in allowed_roots)
        ]
        if outside:
            errors.append(
                f"import {module_name} resolves outside expected root {expected_root}: "
                + ", ".join(str(path) for path in outside)
            )

        for forbidden_name, forbidden_path in forbidden:
            if any(_contained(path, forbidden_path) for path in paths):
                errors.append(
                    f"import {module_name} resolves to retired source root "
                    f"{forbidden_name}: {forbidden_path}"
                )

        editable_source = observed.get("editable_source")
        if editable_source and expected_root != "site-packages":
            source_path = Path(editable_source).resolve()
            if source_path != target:
                warnings.append(
                    f"editable distribution metadata for {module_name} points to {source_path}; "
                    f"runtime import origin is checked against this checkout at {target}"
                )

        expected_distribution = spec.get("distribution")
        expected_version = spec.get("version")
        if expected_distribution and observed.get("distribution") != expected_distribution:
            errors.append(
                f"import {module_name} distribution mismatch: expected "
                f"{expected_distribution}, got {observed.get('distribution')}"
            )
        if expected_version and observed.get("version") != expected_version:
            errors.append(
                f"import {module_name} version mismatch: expected {expected_version}, "
                f"got {observed.get('version')}"
            )

        identities.append(
            {
                "module": module_name,
                "origin": observed.get("origin"),
                "search_locations": observed.get("search_locations", []),
                "distribution": observed.get("distribution"),
                "version": observed.get("version"),
                "editable_source": editable_source,
            }
        )

    return {"ok": not errors, "imports": identities, "errors": errors, "warnings": warnings}


def _probe_script() -> str:
    return r"""
import importlib.metadata as metadata
import importlib.util
import json
import re
import site
import sys
import sysconfig
from pathlib import Path
from urllib.parse import unquote, urlparse

request = json.loads(sys.argv[1])
result = {
    "python": str(Path(sys.executable).resolve()),
    "python_version": sys.version.split()[0],
    "prefix": str(Path(sys.prefix).resolve()),
    "site_packages": sorted({str(Path(p).resolve()) for p in site.getsitepackages()} |
                             {str(Path(sysconfig.get_path(k)).resolve()) for k in ("purelib", "platlib")
                              if sysconfig.get_path(k)}),
    "distributions": [],
    "imports": [],
}
for distribution in metadata.distributions():
    identity = {
        "name": str(distribution.metadata.get("Name") or ""),
        "version": str(distribution.version or ""),
    }
    try:
        direct_url = distribution.read_text("direct_url.json")
    except OSError:
        direct_url = None
        identity["editable_source_error"] = "direct_url metadata could not be read"
    if direct_url:
        try:
            parsed = json.loads(direct_url)
            if parsed.get("dir_info", {}).get("editable"):
                url = urlparse(parsed.get("url", ""))
                if url.scheme == "file":
                    source = unquote(url.path)
                    if sys.platform == "win32" and re.match(r"^/[A-Za-z]:/", source):
                        source = source[1:]
                    identity["editable_source"] = str(Path(source).resolve())
                else:
                    identity["editable_source_error"] = "editable source is not a local file URL"
        except (json.JSONDecodeError, OSError, ValueError):
            identity["editable_source_error"] = "unreadable editable direct_url metadata"
    result["distributions"].append(identity)
result["distributions"].sort(key=lambda item: (str(item["name"]).casefold(), str(item["version"])))
for spec in request:
    module = spec["module"]
    item = {"module": module, "origin": None, "search_locations": []}
    try:
        found = importlib.util.find_spec(module)
        if found is None:
            item["error"] = "module was not found"
        else:
            item["origin"] = found.origin
            item["search_locations"] = list(found.submodule_search_locations or ())
    except (ImportError, ValueError, AttributeError) as exc:
        item["error"] = f"cannot locate module ({type(exc).__name__}: {exc})"
    distribution_name = spec.get("distribution")
    if distribution_name:
        try:
            distribution = metadata.distribution(distribution_name)
            item["distribution"] = distribution.metadata.get("Name", distribution_name)
            item["version"] = distribution.version
            direct_url = distribution.read_text("direct_url.json")
            if direct_url:
                parsed = json.loads(direct_url)
                if parsed.get("dir_info", {}).get("editable"):
                    url = urlparse(parsed.get("url", ""))
                    if url.scheme == "file":
                        source = unquote(url.path)
                        if sys.platform == "win32" and re.match(r"^/[A-Za-z]:/", source):
                            source = source[1:]
                        item["editable_source"] = str(Path(source).resolve())
        except metadata.PackageNotFoundError:
            item["distribution"] = None
            item["version"] = None
    result["imports"].append(item)
print(json.dumps(result, sort_keys=True))
"""


def probe_imports(
    import_specs: Sequence[dict[str, Any]],
    target_root: Path,
    python_executable: str,
    environment: dict[str, str],
) -> dict[str, Any]:
    completed = subprocess.run(
        [python_executable, "-c", _probe_script(), json.dumps(list(import_specs))],
        cwd=target_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SelectiveValidationError(
            f"import provenance probe exited {completed.returncode}: "
            f"{_failure_evidence(completed.stdout + completed.stderr)}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise SelectiveValidationError("import provenance probe returned invalid JSON") from error


def _safe_environment(environment: dict[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in environment.items():
        lowered = key.lower()
        if any(term in lowered for term in ("token", "secret", "password", "auth", "credential", "api_key")):
            continue
        if key in {"PYTHONPATH", "PYTHONUTF8", "PYTHONUNBUFFERED", "PY_COLORS", "NO_COLOR"}:
            safe[key] = value
    return safe


def _environment_fingerprint(environment: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for key, value in sorted(environment.items()):
        digest.update(key.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(value.encode("utf-8", errors="replace"))
        digest.update(b"\0")
    return digest.hexdigest()


def _resolve_environment(
    target_spec: dict[str, Any], repo_root: Path, target_root: Path, python_executable: str
) -> dict[str, str]:
    environment = os.environ.copy()
    replacements = {
        "{repo_root}": str(repo_root),
        "{target_root}": str(target_root),
        "{python}": python_executable,
        "{include_production_read_only}": "0",
        "{include_production_read_only_bool}": "False",
    }
    for key, raw_value in target_spec.get("environment", {}).items():
        value = str(raw_value)
        for token, resolved in replacements.items():
            value = value.replace(token, resolved)
        if str(key).upper() == "PYTHONPATH":
            components = value.split(";") if ";" in value else value.split(os.pathsep)
            value = os.pathsep.join(component for component in components if component)
        environment[str(key)] = value
    return environment


def _safe_relative(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not _contained(path, root):
        raise ValueError(f"configured validation path escapes its root: {value}")
    return path


def _source_files(root: Path, relative_roots: Iterable[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    ignored_parts = {
        ".git", ".pytest_cache", "__pycache__", ".pytest_tmp_root", ".venv", "venv", ".tox",
        ".ruff_cache", "build", "dist",
    }
    for relative in relative_roots:
        path = _safe_relative(root, relative)
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(path.rglob("*"))
        else:
            hashes[relative] = "<missing>"
            continue
        for candidate in candidates:
            if not candidate.is_file() or ignored_parts.intersection(candidate.parts):
                continue
            resolved = candidate.resolve()
            if not _contained(resolved, root):
                hashes[str(candidate)] = "<external-symlink-omitted>"
                continue
            relative_path = resolved.relative_to(root.resolve()).as_posix()
            before = resolved.stat()
            content = resolved.read_bytes()
            after = resolved.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ino,
            ):
                raise SelectiveValidationError(f"input changed while being fingerprinted: {resolved}")
            identity = f"{hashlib.sha256(content).hexdigest()}:{after.st_size}:{after.st_mtime_ns}:{after.st_ino}"
            hashes[relative_path] = hashlib.sha256(identity.encode("ascii")).hexdigest()
    return dict(sorted(hashes.items()))


def _editable_dependency_identities(
    distributions: Sequence[dict[str, Any]], repo_root: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    identities: list[dict[str, Any]] = []
    unverified: list[str] = []
    repository = repo_root.resolve()
    if not distributions:
        unverified.append("installed distribution inventory is unavailable")
    for distribution in distributions:
        identity = {key: distribution.get(key) for key in ("name", "version")}
        if not identity["name"] or not identity["version"]:
            unverified.append("an installed distribution has incomplete name/version identity")
        source_text = distribution.get("editable_source")
        if distribution.get("editable_source_error"):
            unverified.append(f"{identity['name']}: editable source metadata is unreadable")
        elif source_text:
            source = Path(str(source_text)).resolve()
            identity["editable_source"] = str(source)
            if source == repository or not _contained(source, repository) or not source.exists():
                unverified.append(f"{identity['name']}: editable source cannot be content-identified: {source}")
            else:
                relative = source.relative_to(repository).as_posix()
                hashes = _source_files(repository, [relative])
                if not hashes or any(value.startswith("<") for value in hashes.values()):
                    unverified.append(f"{identity['name']}: editable source could not be fully hashed: {source}")
                else:
                    serialized = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    identity["editable_source_sha256"] = hashlib.sha256(serialized).hexdigest()
        identities.append(identity)
    identities.sort(key=lambda item: (str(item.get("name", "")).casefold(), str(item.get("version", ""))))
    return identities, unverified


def _revision(repo_root: Path) -> dict[str, str | None]:
    def git_value(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), *args], capture_output=True, text=True, check=False
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    return {"branch": git_value("branch", "--show-current"), "commit": git_value("rev-parse", "HEAD")}


def compute_input_fingerprint(
    repo_root: Path,
    target_root: Path,
    selective_spec: dict[str, Any],
    selected: Sequence[str],
    command_template: Sequence[str],
    interpreter: dict[str, Any],
    import_identities: Sequence[dict[str, Any]],
    environment_fingerprint: str,
    revision: dict[str, str | None],
    temporary_root_base: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    relevant_roots = [*selective_spec.get("source_roots", []), *selective_spec.get("test_roots", [])]
    relevant_roots.extend(selective_spec.get("dependency_inputs", []))
    file_hashes = _source_files(target_root, relevant_roots)
    inputs = {
        "repo_root": str(repo_root.resolve()),
        "target_root": str(target_root.resolve()),
        "revision": revision,
        "selection": list(selected),
        "command_template": list(command_template),
        "interpreter": interpreter,
        "environment_sha256": environment_fingerprint,
        "import_identities": list(import_identities),
        "selective_contract": selective_spec,
        "file_sha256": file_hashes,
        "temporary_root_base": str(temporary_root_base.resolve()) if temporary_root_base else None,
    }
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest(), inputs


def find_matching_evidence(runs_root: Path, fingerprint: str) -> dict[str, Any] | None:
    if not runs_root.is_dir():
        return None
    for report_path in sorted(runs_root.glob("*.json"), reverse=True):
        try:
            record = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            record.get("status") == "passed"
            and record.get("evidence_reusable") is True
            and record.get("input_fingerprint") == fingerprint
        ):
            record["report_path"] = str(report_path)
            return record
    return None


def write_run_report(runs_root: Path, report: dict[str, Any]) -> Path:
    execution_id = str(report.get("execution_id", ""))
    if not re.fullmatch(r"[0-9a-f]{32}", execution_id):
        raise ValueError("execution_id must be a 32-character lowercase UUID hex string")
    runs_root.mkdir(parents=True, exist_ok=True)
    destination = runs_root / f"{execution_id}.json"
    if destination.exists():
        raise FileExistsError(f"selective validation report already exists: {destination}")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", prefix=f".{execution_id}.", suffix=".tmp",
        dir=runs_root, delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
        json.dump(report, temporary, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        temporary.write("\n")
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


def create_temporary_root(
    target_root: Path,
    execution_id: str | None = None,
    base_root: Path | None = None,
) -> Path:
    identifier = execution_id or uuid.uuid4().hex
    base = (base_root or target_root.resolve() / ".pytest_tmp_root").resolve()
    base.mkdir(parents=True, exist_ok=True)
    destination = base / f"selective-{identifier}"
    destination.mkdir(parents=False, exist_ok=False)
    return destination


def _provenance_plugin_source(
    repo_root: Path,
    target_root: Path,
    import_specs: Sequence[dict[str, Any]],
    forbidden_roots: Sequence[str],
    site_packages: Sequence[str],
    evidence_path: Path,
    workers: int = 0,
) -> str:
    runtime_specs = []
    for spec in import_specs:
        expected_root = str(spec.get("expected_root", "."))
        roots = site_packages if expected_root == "site-packages" else [str((target_root / expected_root).resolve())]
        runtime_specs.append({**spec, "runtime_expected_roots": list(roots)})
    config = {
        "imports": runtime_specs,
        "forbidden_roots": [str((repo_root / item).resolve()) for item in forbidden_roots],
        "evidence_path": str(evidence_path.resolve()),
        "workers": workers,
        "expected_workers_path": str((evidence_path.parent / "expected-workers").resolve()),
        "pytest_basetemp": str((evidence_path.parent / "pytest").resolve()),
    }
    encoded_config = json.dumps(json.dumps(config))
    return f'''\
import importlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import pytest

_CONFIG = json.loads({encoded_config})

@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if not hasattr(config, "workerinput"):
        configured_workers = getattr(config.option, "numprocesses", None)
        if _CONFIG["workers"] and configured_workers != _CONFIG["workers"]:
            raise pytest.UsageError(
                "pytest-xdist worker count differs from the explicit selective request: "
                f"{{configured_workers!r}} vs {{_CONFIG['workers']}}"
            )
        if not _CONFIG["workers"] and configured_workers not in (None, 0, "0", "no"):
            raise pytest.UsageError("serial selective validation cannot use pytest-xdist workers")
        if _CONFIG["workers"] and getattr(config.option, "dist", None) != "loadfile":
            raise pytest.UsageError("selective parallel validation requires local loadfile distribution")
        transports = getattr(config.option, "tx", None) or []
        if any(not str(transport).startswith("popen") for transport in transports):
            raise pytest.UsageError("remote pytest-xdist transports are not supported")
        if getattr(config.option, "rsyncdir", None):
            raise pytest.UsageError("remote pytest-xdist transports are not supported")
        if _CONFIG["workers"] and str(getattr(config.option, "maxworkerrestart", None)) != "0":
            raise pytest.UsageError("selective parallel validation disables pytest-xdist worker restarts")
        actual_basetemp = getattr(config.option, "basetemp", None)
        if not actual_basetemp or os.path.normcase(os.path.normpath(str(Path(actual_basetemp).resolve()))) != os.path.normcase(os.path.normpath(_CONFIG["pytest_basetemp"])):
            raise pytest.UsageError("selective pytest temporary root differs from the isolated run root")

def _inside(path, roots):
    resolved = Path(path).resolve()
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except (OSError, ValueError):
            pass
    return False

def _observe(spec):
    name = spec["module"]
    result = {{"module": name, "origin": None, "search_locations": []}}
    errors = []
    try:
        module = importlib.import_module(name)
        origin = getattr(module, "__file__", None)
        locations = list(getattr(module, "__path__", ()) or ())
        result["origin"] = str(Path(origin).resolve()) if origin else None
        result["search_locations"] = [str(Path(path).resolve()) for path in locations]
        paths = ([result["origin"]] if result["origin"] else []) + result["search_locations"]
        if not paths:
            errors.append(f"import {{name}} has no runtime filesystem origin")
        elif any(not _inside(path, spec["runtime_expected_roots"]) for path in paths):
            errors.append(f"import {{name}} resolves outside expected roots {{spec['runtime_expected_roots']}}")
    except Exception as exc:
        errors.append(f"import {{name}} failed in pytest process: {{type(exc).__name__}}: {{exc}}")

    distribution_name = spec.get("distribution")
    if distribution_name:
        try:
            distribution = metadata.distribution(distribution_name)
            result["distribution"] = distribution.metadata.get("Name", distribution_name)
            result["version"] = distribution.version
            if result["distribution"] != distribution_name:
                errors.append(f"distribution mismatch for {{name}}: {{result['distribution']}}")
            if spec.get("version") and result["version"] != spec["version"]:
                errors.append(f"version mismatch for {{name}}: {{result['version']}}")
        except metadata.PackageNotFoundError:
            result["distribution"] = None
            result["version"] = None
            errors.append(f"distribution {{distribution_name}} is missing in pytest process")
    return result, errors

def _write_evidence(payload):
    path = Path(_CONFIG["evidence_path"])
    if _CONFIG["workers"]:
        path.mkdir(parents=True, exist_ok=True)
        path = path / (payload["worker_id"] + ".json")
    _atomic_write(path, payload)

def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + "." + str(os.getpid()) + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)

def _worker_id(session):
    return getattr(session.config, "workerinput", {{}}).get("workerid", "main")

def _runtime_payload(session):
    worker_id = _worker_id(session)
    identities = []
    errors = []
    for spec in _CONFIG["imports"]:
        identity, item_errors = _observe(spec)
        identities.append(identity)
        errors.extend(item_errors)
    for root in _CONFIG["forbidden_roots"]:
        if Path(root).exists():
            errors.append(f"retired source root is present: {{root}}")
    return {{
        "worker_id": worker_id,
        "imports": identities,
        "errors": errors,
        "pytest_basetemp": str(getattr(session.config.option, "basetemp", "") or ""),
    }}

def _record_runtime(session):
    payload = _runtime_payload(session)
    _write_evidence(payload)
    return payload

@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node):
    worker_id = node.workerinput["workerid"]
    path = Path(_CONFIG["expected_workers_path"])
    path.mkdir(parents=True, exist_ok=True)
    _atomic_write(path / (worker_id + ".json"), {{"worker_id": worker_id}})

def pytest_sessionstart(session):
    payload = _record_runtime(session)
    if payload["errors"]:
        pytest.exit("runtime import provenance failed: " + "; ".join(payload["errors"]), returncode=4)

def pytest_runtest_setup(item):
    payload = _record_runtime(item.session)
    if payload["errors"]:
        pytest.fail("runtime import provenance failed: " + "; ".join(payload["errors"]), pytrace=False)
'''


def _collect_parallel_runtime_receipts(
    evidence_path: Path,
    expected_workers_path: Path,
    workers: int,
    pytest_root: Path,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    expected_ids: list[str] = []
    errors: list[str] = []
    for path in sorted(expected_workers_path.glob("*.json")) if expected_workers_path.is_dir() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"invalid registered-worker receipt: {path.name}")
            continue
        worker_id = payload.get("worker_id") if isinstance(payload, dict) else None
        if worker_id != path.stem or not isinstance(worker_id, str):
            errors.append(f"registered-worker identity mismatch: {path.name}")
            continue
        expected_ids.append(worker_id)
    expected_ids.sort(key=_worker_id_sort_key)
    wanted_ids = [f"gw{index}" for index in range(workers)]
    if expected_ids != wanted_ids:
        errors.append(f"pytest-xdist registered workers {expected_ids!r}; expected {wanted_ids!r}")

    reports: dict[str, dict[str, Any]] = {}
    for path in sorted(evidence_path.glob("*.json")) if evidence_path.is_dir() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"invalid runtime worker receipt: {path.name}")
            continue
        worker_id = payload.get("worker_id") if isinstance(payload, dict) else None
        if not isinstance(worker_id, str) or worker_id != path.stem:
            errors.append(f"runtime worker identity mismatch: {path.name}")
            continue
        if worker_id in reports:
            errors.append(f"duplicate runtime worker receipt: {worker_id}")
            continue
        reports[worker_id] = payload

    required_ids = ["main", *wanted_ids]
    if set(reports) != set(required_ids):
        errors.append(
            f"runtime worker receipts were {sorted(reports)!r}; expected {required_ids!r}"
        )
    expected_root = pytest_root.resolve()
    worker_temp_roots: list[str] = []
    for worker_id in wanted_ids:
        payload = reports.get(worker_id)
        if payload is None:
            continue
        temp_value = payload.get("pytest_basetemp")
        if not isinstance(temp_value, str) or not temp_value:
            errors.append(f"worker {worker_id} did not report its pytest temporary root")
            continue
        temp_path = Path(temp_value).resolve()
        try:
            temp_path.relative_to(expected_root)
        except ValueError:
            errors.append(f"worker {worker_id} pytest temporary root escapes run root")
            continue
        worker_temp_roots.append(os.path.normcase(os.path.normpath(str(temp_path))))
    if len(worker_temp_roots) != len(set(worker_temp_roots)):
        errors.append("pytest-xdist workers reported equivalent temporary roots")
    return reports, errors


def _redact_text(text: str) -> str:
    patterns = (
        re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?([^\s,;]+)"),
        re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*)([^\s,;]+)"),
        re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    )
    result = text
    for pattern in patterns:
        result = pattern.sub(r"\1<redacted>", result)
    return result


def _failure_evidence(output: str, *, max_chars: int = 8000) -> str:
    lines = deque(output.splitlines(), maxlen=50)
    result = _redact_text("\n".join(lines))
    if len(result) > max_chars:
        result = "[earlier failure output omitted]\n" + result[-max_chars:]
    return result


def _base_report(repo_root: Path, target_name: str, execution_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "execution_id": execution_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repository": str(repo_root.resolve()),
        "worktree": str(repo_root.resolve()),
        "target": target_name,
        "status": "blocked",
        "duration_seconds": 0.0,
        "pytest_duration_seconds": 0.0,
        "exit_code": 2,
        "selected": [],
        "command": [],
        "runtime_worker_ids": [],
        "report_path": None,
        "temp_root": None,
        "failure_evidence": "",
    }


def run_selective_target(
    repo_root: Path,
    target_name: str,
    target_spec: dict[str, Any],
    node_ids: Sequence[str],
    files: Sequence[str],
    modules: Sequence[str],
    *,
    python_executable: str,
    import_probe: Callable[..., dict[str, Any]] = probe_imports,
    command_runner: Callable[..., Any] = subprocess.run,
    reuse_evidence: bool = False,
    temporary_root: Path | None = None,
    workers: int = 0,
) -> dict[str, Any]:
    """Run only selected pytest items for one manifest target, without bootstrap."""
    started = time.monotonic()
    execution_id = uuid.uuid4().hex
    repo_root = repo_root.resolve()
    report = _base_report(repo_root, target_name, execution_id)
    runs_root = repo_root / "docs" / "test-results" / "selective" / "runs"
    selective = target_spec.get("selective_validation")
    target_relative = str(target_spec.get("working_directory", ""))
    target_root = (repo_root / target_relative).resolve()
    report["working_directory"] = str(target_root)
    report["revision"] = _revision(repo_root)
    report["interpreter"] = {"path": str(Path(python_executable).resolve())}
    report["qualification_scope"] = "source-level"
    report["workers"] = workers

    try:
        if isinstance(workers, bool) or not isinstance(workers, int) or not 0 <= workers <= MAX_SELECTIVE_WORKERS:
            raise SelectiveValidationError(f"Worker count must be from 0 (serial) to {MAX_SELECTIVE_WORKERS}.")
        if not isinstance(selective, dict):
            raise SelectiveValidationError(f"target {target_name} has no selective_validation contract")
        if not target_relative or not _contained(target_root, repo_root) or not target_root.is_dir():
            raise SelectiveValidationError(f"target working_directory is missing or escapes repository: {target_relative}")

        selected = resolve_pytest_selectors(
            target_root,
            selective.get("test_roots", []),
            node_ids=node_ids,
            files=files,
            modules=modules,
        )
        report["selected"] = selected
        environment = _resolve_environment(target_spec, repo_root, target_root, python_executable)
        environment_fingerprint = _environment_fingerprint(environment)
        import_specs = list(selective.get("imports", []))
        report["qualification_scope"] = (
            "installed-distribution"
            if import_specs and all(item.get("expected_root") == "site-packages" for item in import_specs)
            else "source-level"
        )
        pytest_arguments = [str(value) for value in selective.get("pytest_arguments", [])]
        inherited_addopts = environment.get("PYTEST_ADDOPTS")
        try:
            native_addopts = _pytest_addopts(
                _native_pytest_addopts(python_executable, target_root, selected, inherited_addopts)
            )
            pytest_arguments = _pytest_addopts(pytest_arguments)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            report["stage"] = "configuration-preflight"
            raise SelectiveValidationError(f"pytest configuration preflight failed: {error}") from error
        environment.pop("PYTEST_ADDOPTS", None)
        command_template = [
            str(Path(python_executable).resolve()), "-m", "pytest", "-p", "<provenance-plugin>",
            *selected, *pytest_arguments, "--rootdir", str(target_root), "--basetemp", "<temp-root>/pytest",
            "-o", "addopts=" + shlex.join(native_addopts),
        ]
        if workers:
            command_template.extend(["-n", str(workers), "--dist=loadfile", "--max-worker-restart=0"])
        command_template.extend(["-W", "error::pytest.PytestUnhandledThreadExceptionWarning"])
        report["command_template"] = command_template
        revision = report["revision"]
        def snapshot_inputs() -> dict[str, Any]:
            probe_result = import_probe(import_specs, target_root, python_executable, environment)
            provenance_result = assess_import_provenance(
                repo_root,
                target_root,
                import_specs,
                probe_result.get("imports", []),
                forbidden_roots=selective.get("forbidden_source_roots", []),
                site_packages=probe_result.get("site_packages", []),
            )
            if not provenance_result["ok"]:
                raise SelectiveValidationError(
                    "import provenance failed: " + "; ".join(provenance_result["errors"])
                )
            dependency_identities, unverified_dependencies = _editable_dependency_identities(
                probe_result.get("distributions", []), repo_root
            )
            interpreter = {
                "path": str(Path(python_executable).resolve()),
                "version": probe_result.get("python_version"),
                "prefix": probe_result.get("prefix"),
                "site_packages": probe_result.get("site_packages", []),
                "distributions": dependency_identities,
            }
            fingerprint, inputs = compute_input_fingerprint(
                repo_root,
                target_root,
                selective,
                selected,
                command_template,
                interpreter,
                provenance_result["imports"],
                environment_fingerprint,
                revision,
                temporary_root.resolve() if temporary_root else target_root / ".pytest_tmp_root",
            )
            unverified_dependencies.extend(
                f"input file identity unavailable: {path}"
                for path, identity in inputs["file_sha256"].items()
                if identity.startswith("<")
            )
            return {
                "probe": probe_result,
                "provenance": provenance_result,
                "dependencies": dependency_identities,
                "unverified_dependencies": unverified_dependencies,
                "interpreter": interpreter,
                "fingerprint": fingerprint,
                "inputs": inputs,
            }

        snapshot = snapshot_inputs()
        report["environment_sha256"] = environment_fingerprint
        report["dependency_identities"] = snapshot["dependencies"]
        report["interpreter"] = snapshot["interpreter"]
        report["import_identities"] = snapshot["provenance"]["imports"]
        report["provenance_warnings"] = snapshot["provenance"]["warnings"]
        report["input_fingerprint"] = snapshot["fingerprint"]
        report["input_identities"] = snapshot["inputs"]
        reuse_eligible = not snapshot["unverified_dependencies"]
        report["evidence_reuse"] = {
            "requested": reuse_evidence,
            "eligible": reuse_eligible,
            "reason": "; ".join(snapshot["unverified_dependencies"]) if not reuse_eligible else None,
        }

        if reuse_evidence and reuse_eligible:
            prior = find_matching_evidence(runs_root, snapshot["fingerprint"])
            if prior is not None and prior.get("evidence_reusable") is True:
                confirm = snapshot_inputs()
                if confirm["fingerprint"] == snapshot["fingerprint"] and not confirm["unverified_dependencies"]:
                    report["status"] = "reused"
                    report["exit_code"] = 0
                    report["evidence_reusable"] = True
                    report["reused_from"] = prior["execution_id"]
                    report["pytest_summary"] = prior.get("pytest_summary", "")
                    report["runtime_import_identities"] = prior.get("runtime_import_identities", [])
                    for field in (
                        "runtime_imports_by_worker",
                        "runtime_worker_ids",
                        "runtime_worker_temp_roots",
                    ):
                        if field in prior:
                            report[field] = prior[field]
                    report["failure_evidence"] = ""
                    report["report_path"] = str(write_run_report(runs_root, report))
                    return report
                snapshot = confirm
                reuse_eligible = not snapshot["unverified_dependencies"]
                report["evidence_reuse"]["eligible"] = reuse_eligible
                report["evidence_reuse"]["reason"] = (
                    "; ".join(snapshot["unverified_dependencies"]) if not reuse_eligible else None
                )
                report["input_fingerprint"] = snapshot["fingerprint"]
                report["input_identities"] = snapshot["inputs"]

        temp_root = create_temporary_root(target_root, execution_id, temporary_root)
        report["temp_root"] = str(temp_root)
        pytest_root = temp_root / "pytest"
        pytest_root.mkdir()
        plugin_module = f"selective_validation_provenance_{execution_id}"
        evidence_path = temp_root / ("runtime-imports" if workers else "runtime-imports.json")
        plugin_path = temp_root / f"{plugin_module}.py"
        plugin_path.write_text(
            _provenance_plugin_source(
                repo_root,
                target_root,
                import_specs,
                selective.get("forbidden_source_roots", []),
                snapshot["probe"].get("site_packages", []),
                evidence_path,
                workers,
            ),
            encoding="utf-8",
        )
        runtime_environment = dict(environment)
        configured_pythonpath = runtime_environment.get("PYTHONPATH", "")
        runtime_environment["PYTHONPATH"] = os.pathsep.join(
            [str(temp_root), *([configured_pythonpath] if configured_pythonpath else [])]
        )
        runtime_environment["SCRIPTS_SELECTIVE_PROVENANCE_EVIDENCE"] = str(evidence_path)
        report["environment"] = _safe_environment(runtime_environment)
        command = [
            str(Path(python_executable).resolve()), "-m", "pytest", "-p", plugin_module,
            *selected, *pytest_arguments, "--rootdir", str(target_root), "--basetemp", str(pytest_root),
            "-o", "addopts=" + shlex.join(native_addopts),
        ]
        if workers:
            command.extend(["-n", str(workers), "--dist=loadfile", "--max-worker-restart=0"])
        command.extend(["-W", "error::pytest.PytestUnhandledThreadExceptionWarning"])
        report["command"] = command
        report["display_command"] = shlex.join(command)
        pytest_started = time.monotonic()
        try:
            completed = command_runner(
                command,
                cwd=target_root,
                env=runtime_environment,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            completed = None
            report["failure_evidence"] = f"pytest could not start: {type(error).__name__}: {error}"
            report["exit_code"] = 127
        report["pytest_duration_seconds"] = round(time.monotonic() - pytest_started, 6)
        if completed is not None:
            output = (completed.stdout or "") + (completed.stderr or "")
            report["exit_code"] = int(completed.returncode)
            if completed.returncode == 0:
                runtime_errors: list[str] = []
                worker_import_identities: dict[str, list[dict[str, Any]]] = {}
                if workers:
                    receipts, receipt_errors = _collect_parallel_runtime_receipts(
                        evidence_path, temp_root / "expected-workers", workers, pytest_root
                    )
                    runtime_errors.extend(receipt_errors)
                    for worker_id, runtime_result in receipts.items():
                        runtime_errors.extend(
                            f"{worker_id}: {error}" for error in runtime_result.get("errors", [])
                        )
                        runtime_provenance = assess_import_provenance(
                            repo_root,
                            target_root,
                            import_specs,
                            runtime_result.get("imports", []),
                            forbidden_roots=selective.get("forbidden_source_roots", []),
                            site_packages=snapshot["probe"].get("site_packages", []),
                        )
                        runtime_errors.extend(
                            f"{worker_id}: {error}" for error in runtime_provenance["errors"]
                        )
                        worker_import_identities[worker_id] = runtime_provenance["imports"]
                    report["runtime_worker_ids"] = sorted(receipts, key=_worker_id_sort_key)
                    report["runtime_imports_by_worker"] = worker_import_identities
                    report["runtime_worker_temp_roots"] = {
                        worker_id: receipts[worker_id].get("pytest_basetemp")
                        for worker_id in [f"gw{index}" for index in range(workers)]
                        if worker_id in receipts
                    }
                    report["runtime_import_identities"] = worker_import_identities.get("main", [])
                else:
                    try:
                        runtime_result = json.loads(evidence_path.read_text(encoding="utf-8"))
                        runtime_imports = runtime_result.get("imports", [])
                        runtime_errors = list(runtime_result.get("errors", []))
                        runtime_worker_id = runtime_result.get("worker_id")
                        report["runtime_worker_ids"] = [runtime_worker_id] if isinstance(runtime_worker_id, str) else []
                        if runtime_worker_id != "main":
                            runtime_errors.append(
                                f"pytest runtime receipt worker identity was {runtime_worker_id!r}, expected 'main'"
                            )
                    except (OSError, json.JSONDecodeError) as error:
                        runtime_imports = []
                        runtime_errors = [f"pytest process did not produce runtime provenance evidence: {error}"]
                    runtime_provenance = assess_import_provenance(
                        repo_root,
                        target_root,
                        import_specs,
                        runtime_imports,
                        forbidden_roots=selective.get("forbidden_source_roots", []),
                        site_packages=snapshot["probe"].get("site_packages", []),
                    )
                    runtime_errors.extend(runtime_provenance["errors"])
                    report["runtime_import_identities"] = runtime_provenance["imports"]
                report["runtime_provenance_errors"] = [_redact_text(item) for item in runtime_errors]
                if runtime_errors:
                    report["status"] = "failed"
                    report["exit_code"] = 4
                    report["failure_evidence"] = _failure_evidence("; ".join(runtime_errors))
                else:
                    after = snapshot_inputs()
                    if after["fingerprint"] != snapshot["fingerprint"]:
                        report["status"] = "invalidated"
                        report["exit_code"] = 3
                        report["evidence_reuse"]["eligible"] = False
                        report["evidence_reuse"]["reason"] = "relevant inputs changed during pytest execution"
                        report["evidence_reusable"] = False
                        report["failure_evidence"] = "Inputs changed while pytest was running; the result was not recorded as reusable."
                    else:
                        report["status"] = "passed"
                        summary_lines = [line.strip() for line in output.splitlines() if re.search(r"\b(passed|failed|error|skipped)\b", line)]
                        report["pytest_summary"] = summary_lines[-1] if summary_lines else "pytest exited successfully"
                        report["evidence_reusable"] = reuse_eligible
                        if not reuse_eligible:
                            report["evidence_reuse"]["eligible"] = False
                            report["evidence_reuse"]["reason"] = "; ".join(snapshot["unverified_dependencies"])
            else:
                report["status"] = "failed"
                report["failure_evidence"] = _failure_evidence(output)
                if workers:
                    observed_receipts, _ = _collect_parallel_runtime_receipts(
                        evidence_path, temp_root / "expected-workers", workers, pytest_root
                    )
                    report["runtime_worker_ids"] = sorted(observed_receipts, key=_worker_id_sort_key)
                else:
                    try:
                        observed_receipt = json.loads(evidence_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        report["runtime_worker_ids"] = []
                    else:
                        worker_id = observed_receipt.get("worker_id") if isinstance(observed_receipt, dict) else None
                        report["runtime_worker_ids"] = [worker_id] if isinstance(worker_id, str) else []
        else:
            report["status"] = "failed"

    except (SelectiveValidationError, ValueError, OSError, KeyError, TypeError) as error:
        report["status"] = "blocked"
        report["exit_code"] = 2
        report["error"] = _redact_text(f"{type(error).__name__}: {error}")
        report["failure_evidence"] = _failure_evidence(str(error))
    finally:
        report["duration_seconds"] = round(time.monotonic() - started, 6)

    report["report_path"] = str(write_run_report(runs_root, report))
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run explicit pytest selections against existing environments.")
    parser.add_argument("-r", "--repo-root", required=True)
    parser.add_argument("-t", "--target", action="append", required=True)
    parser.add_argument("-e", "--python-executable", default=sys.executable)
    parser.add_argument("-n", "--node-id", action="append", default=[])
    parser.add_argument("-f", "--file", action="append", default=[])
    parser.add_argument("-u", "--module", action="append", default=[])
    parser.add_argument("--workers", type=int, choices=range(0, MAX_SELECTIVE_WORKERS + 1), default=0)
    parser.add_argument("--reuse-evidence", action="store_true")
    parser.add_argument("--temporary-root", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    manifest_path = repo_root / "validation-targets.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Cannot read validation manifest: {error}", file=sys.stderr)
        return 2

    failures = 0
    for target_name in dict.fromkeys(args.target):
        target_spec = manifest.get("targets", {}).get(target_name)
        if not isinstance(target_spec, dict):
            print(f"Unknown validation target: {target_name}", file=sys.stderr)
            failures += 1
            continue
        selective = target_spec.get("selective_validation")
        if not isinstance(selective, dict):
            print(f"Target does not support selective pytest: {target_name}", file=sys.stderr)
            failures += 1
            continue
        result = run_selective_target(
            repo_root,
            target_name,
            target_spec,
            args.node_id,
            args.file,
            args.module,
            python_executable=args.python_executable,
            reuse_evidence=args.reuse_evidence,
            temporary_root=args.temporary_root,
            workers=args.workers,
        )
        print(
            f"{target_name}: {result['status'].upper()} "
            f"execution={result['execution_id']} report={result['report_path']}"
        )
        if result["status"] in {"failed", "blocked", "invalidated"}:
            failures += 1
            evidence = result.get("failure_evidence") or result.get("error")
            if evidence:
                print(evidence, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
