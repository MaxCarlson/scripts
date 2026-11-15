"""Deterministic source-tree hashing and manifest enforcement for H4 acceptance."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tomllib
import unicodedata
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

HASH_ALGORITHM = "rc-h4-tree-sha256-v2"
EXCLUDED_DIR_NAMES = frozenset({".git", "__pycache__", ".pytest_cache"})
EXCLUDED_DIR_PREFIXES = (".pytest_tmp_",)
EXCLUDED_FILE_SUFFIXES = (".pyc", ".pyo")
REQUIRED_MODULE_FILES = (
    "pyproject.toml",
    "config.production-template.yaml",
    "resource_coordinator/__init__.py",
    "resource_coordinator/installation.py",
)


class SourceIntegrityError(RuntimeError):
    """Machine-readable source verification failure."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def is_reparse_point(path: Path) -> bool:
    """Return True if *path* is a symlink, junction, or Windows reparse point."""
    try:
        if path.is_symlink():
            return True
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode):
            return True
        attrs = getattr(st, "st_file_attributes", 0)
        return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        return True


def _is_excluded_dir(name: str) -> bool:
    return name in EXCLUDED_DIR_NAMES or any(name.startswith(p) for p in EXCLUDED_DIR_PREFIXES)


def _is_excluded_file(name: str) -> bool:
    return any(name.endswith(s) for s in EXCLUDED_FILE_SUFFIXES)


def hash_source_tree(module_root: Path) -> str:
    """Compute a canonical, order-independent SHA-256 digest of *module_root*.

    Algorithm ``rc-h4-tree-sha256-v2``:
    1. Rejects symlinks, junctions, and reparse points anywhere under *module_root*.
    2. Excludes ephemeral artifacts (``.git``, ``__pycache__``, ``.pytest_cache``,
       ``.pytest_tmp_*``, ``*.pyc``, ``*.pyo``).
    3. Records every regular file (kind ``F``) and every empty non-excluded directory
       (kind ``D``) using canonical POSIX relative paths.
    4. Detects case-insensitive / Unicode-normalized relative-path collisions.
    5. Sorts entries by ``(relative_posix.encode("utf-8"), kind)`` before hashing.
    """
    if not module_root.exists() or not module_root.is_dir() or is_reparse_point(module_root):
        raise SourceIntegrityError(
            "source_reparse_point" if module_root.exists() and is_reparse_point(module_root) else "source_root_missing",
            f"Source module directory is missing or unsafe: {module_root}",
            path=str(module_root),
        )

    root_resolved = module_root.resolve(strict=True)
    entries: list[Tuple[bytes, bytes, bytes]] = []
    seen_canonical: Dict[str, str] = {}

    def record_unique(rel_posix: str) -> None:
        norm = unicodedata.normalize("NFC", rel_posix).casefold()
        previous = seen_canonical.get(norm)
        if previous is not None and previous != rel_posix:
            raise SourceIntegrityError(
                "ambiguous_relative_path",
                f"Ambiguous relative paths in source tree: {previous!r} vs {rel_posix!r}",
                first=previous,
                second=rel_posix,
            )
        seen_canonical[norm] = rel_posix

    def walk_dir(current: Path) -> bool:
        """Walk *current* deterministically; return True if any non-excluded child exists."""
        has_kept_child = False
        try:
            children = sorted(os.scandir(current), key=lambda e: e.name)
        except OSError as exc:
            raise SourceIntegrityError(
                "source_unreadable",
                f"Could not read source directory {current}: {exc}",
                path=str(current),
            ) from exc

        for entry in children:
            child_path = Path(entry.path)
            if is_reparse_point(child_path):
                raise SourceIntegrityError(
                    "source_reparse_point",
                    f"Source bundle contains a reparse point or symlink: {child_path}",
                    path=str(child_path),
                )
            if entry.is_dir(follow_symlinks=False):
                if _is_excluded_dir(entry.name):
                    continue
                rel = child_path.relative_to(root_resolved).as_posix()
                record_unique(rel)
                has_kept_child = True
                child_has_content = walk_dir(child_path)
                if not child_has_content:
                    entries.append((rel.encode("utf-8"), b"D", b""))
            elif entry.is_file(follow_symlinks=False):
                if _is_excluded_file(entry.name):
                    continue
                rel = child_path.relative_to(root_resolved).as_posix()
                record_unique(rel)
                has_kept_child = True
                try:
                    content = child_path.read_bytes()
                except OSError as exc:
                    raise SourceIntegrityError(
                        "source_unreadable",
                        f"Could not read source file {child_path}: {exc}",
                        path=str(child_path),
                    ) from exc
                entries.append((rel.encode("utf-8"), b"F", content))
            else:
                raise SourceIntegrityError(
                    "source_reparse_point",
                    f"Unsupported non-regular filesystem entry in source tree: {child_path}",
                    path=str(child_path),
                )
        return has_kept_child

    walk_dir(root_resolved)
    entries.sort(key=lambda item: (item[0], item[1]))

    digest = hashlib.sha256()
    digest.update(f"{HASH_ALGORITHM}\n".encode("ascii"))
    for rel_bytes, kind_byte, content in entries:
        digest.update(kind_byte)
        digest.update(len(rel_bytes).to_bytes(4, "big"))
        digest.update(rel_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _is_hex_sha(value: Any, length: int) -> bool:
    if not isinstance(value, str) or len(value) != length:
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in value)


def load_source_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Load and validate a pinned H4 source or bundle manifest."""
    if not manifest_path.is_file() or is_reparse_point(manifest_path):
        raise SourceIntegrityError(
            "source_manifest_missing",
            f"Source manifest is missing or unsafe: {manifest_path}",
            path=str(manifest_path),
        )
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceIntegrityError(
            "source_manifest_invalid",
            f"Source manifest is unreadable or invalid JSON: {exc}",
            path=str(manifest_path),
        ) from exc

    if not isinstance(data, dict) or data.get("schema_version") not in (1, 2):
        raise SourceIntegrityError(
            "source_manifest_invalid",
            "Source manifest has unsupported or missing schema_version",
            path=str(manifest_path),
        )
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SourceIntegrityError(
            "source_manifest_invalid",
            "Source manifest must contain a non-empty 'sources' list",
            path=str(manifest_path),
        )
    for entry in sources:
        validate_manifest_entry(entry)
    return data


def validate_manifest_entry(entry: Any) -> Dict[str, Any]:
    """Validate one source entry from a manifest."""
    if not isinstance(entry, dict):
        raise SourceIntegrityError("source_manifest_invalid", "Manifest source entry must be an object")
    required = ("source_role", "repository", "commit_sha", "package_version", "source_tree_sha256", "hash_algorithm")
    for key in required:
        if not entry.get(key):
            raise SourceIntegrityError(
                "source_manifest_invalid",
                f"Manifest source entry missing required field: {key}",
                missing_field=key,
            )
    if not _is_hex_sha(entry["commit_sha"], 40):
        raise SourceIntegrityError(
            "source_manifest_invalid",
            f"Manifest commit_sha must be a 40-hex Git SHA: {entry['commit_sha']!r}",
            commit_sha=entry["commit_sha"],
        )
    if not _is_hex_sha(entry["source_tree_sha256"], 64):
        raise SourceIntegrityError(
            "source_manifest_invalid",
            f"Manifest source_tree_sha256 must be a 64-hex SHA-256 digest: {entry['source_tree_sha256']!r}",
        )
    if entry["hash_algorithm"] != HASH_ALGORITHM:
        raise SourceIntegrityError(
            "hash_algorithm_mismatch",
            f"Unsupported hash_algorithm {entry['hash_algorithm']!r}; expected {HASH_ALGORITHM!r}",
            expected=HASH_ALGORITHM,
            actual=entry["hash_algorithm"],
        )
    return dict(entry)


def manifest_entry_for_role(manifest: Mapping[str, Any], role: str) -> Dict[str, Any]:
    """Return the validated manifest entry for *role*."""
    for entry in manifest.get("sources", ()):
        if isinstance(entry, Mapping) and entry.get("source_role") == role:
            return validate_manifest_entry(entry)
    raise SourceIntegrityError(
        "source_role_mismatch",
        f"Source manifest does not declare role {role!r}",
        expected_role=role,
    )


def verify_source_tree(
    source_root: Path,
    *,
    expected_version: str,
    expected_role: Optional[str] = None,
    manifest_entry: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Verify structure, version, reparse safety, and canonical digest of *source_root*."""
    unresolved = source_root.expanduser()
    if not unresolved.exists() or not unresolved.is_dir():
        raise SourceIntegrityError(
            "source_root_missing",
            f"Source root does not exist: {source_root}",
            path=str(source_root),
        )
    if is_reparse_point(unresolved):
        raise SourceIntegrityError(
            "source_reparse_point",
            f"Source root is a reparse point or symlink: {source_root}",
            path=str(source_root),
        )
    root = unresolved.resolve(strict=True)
    module_root = root / "modules" / "resource_coordinator"
    if not module_root.is_dir() or is_reparse_point(module_root):
        raise SourceIntegrityError(
            "source_structure_invalid",
            f"Expected Resource Coordinator module directory missing or unsafe: {module_root}",
            path=str(module_root),
        )
    for rel_file in REQUIRED_MODULE_FILES:
        candidate = module_root / rel_file
        if not candidate.is_file() or is_reparse_point(candidate):
            raise SourceIntegrityError(
                "source_structure_invalid",
                f"Required Resource Coordinator file missing or unsafe: {rel_file}",
                missing_file=rel_file,
                path=str(candidate),
            )

    manifest_toml = module_root / "pyproject.toml"
    try:
        pyproject = tomllib.loads(manifest_toml.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise SourceIntegrityError(
            "source_structure_invalid",
            f"Invalid pyproject.toml in {module_root}: {exc}",
            path=str(manifest_toml),
        ) from exc
    version = str(pyproject.get("project", {}).get("version", ""))
    if version != expected_version:
        raise SourceIntegrityError(
            "source_version_mismatch",
            f"Expected source version {expected_version}, found {version or 'unknown'}",
            expected_version=expected_version,
            actual_version=version,
        )

    digest = hash_source_tree(module_root)
    if manifest_entry is not None:
        validated = validate_manifest_entry(manifest_entry)
        if expected_role and validated["source_role"] != expected_role:
            raise SourceIntegrityError(
                "source_role_mismatch",
                f"Manifest role {validated['source_role']!r} does not match expected {expected_role!r}",
                expected_role=expected_role,
                actual_role=validated["source_role"],
            )
        if validated["package_version"] != expected_version:
            raise SourceIntegrityError(
                "source_version_mismatch",
                f"Manifest package_version {validated['package_version']!r} != {expected_version!r}",
                expected_version=expected_version,
                actual_version=validated["package_version"],
            )
        if digest.lower() != validated["source_tree_sha256"].lower():
            raise SourceIntegrityError(
                "source_digest_mismatch",
                f"Source tree digest mismatch for {expected_role or version}: "
                f"expected {validated['source_tree_sha256']}, got {digest}",
                expected_digest=validated["source_tree_sha256"],
                actual_digest=digest,
                source_role=validated["source_role"],
            )

    return {
        "source_root": str(root),
        "module_root": str(module_root),
        "package_version": version,
        "hash_algorithm": HASH_ALGORITHM,
        "source_tree_sha256": digest,
    }
