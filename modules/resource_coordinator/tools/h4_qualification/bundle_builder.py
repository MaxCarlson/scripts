#!/usr/bin/env python3
"""Build and verify a deterministic, integrity-hardened Windows H4 acceptance bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from tools.h4_qualification.source_integrity import (
        HASH_ALGORITHM,
        SourceIntegrityError,
        is_reparse_point,
        load_source_manifest,
        manifest_entry_for_role,
        verify_source_tree,
    )
except ImportError:  # pragma: no cover - direct script execution fallback
    from source_integrity import (  # type: ignore[no-redef]
        HASH_ALGORITHM,
        SourceIntegrityError,
        is_reparse_point,
        load_source_manifest,
        manifest_entry_for_role,
        verify_source_tree,
    )

DEFAULT_OLD_COMMIT = "873a49382a5e03da47f793608d3519f7e69da646"
ARCHIVE_FILENAME = "h4-windows-acceptance.zip"
BUNDLE_MANIFEST_VERSION = 2

# Strict archive extraction limits tailored for the H4 bundle.
MAX_ARCHIVE_MEMBERS = 2000
MAX_ARCHIVE_MEMBER_BYTES = 10 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 100

PINNED_RUNTIME_DIRECT = [
    "anyio==4.12.1",
    "httpx==0.28.1",
    "starlette==0.50.0",
    "uvicorn==0.40.0",
    "psutil==7.1.3",
    "PyYAML==6.0.3",
    "rich==14.2.0",
]
PINNED_RUNTIME_TRANSITIVE = [
    "certifi==2025.11.12",
    "click==8.3.1",
    "colorama==0.4.6",
    "h11==0.16.0",
    "httpcore==1.0.9",
    "idna==3.11",
    "markdown-it-py==4.0.0",
    "mdurl==0.1.2",
    "Pygments==2.19.2",
    "sniffio==1.3.1",
    "typing_extensions==4.15.0",
]
PINNED_DEV_TEST = [
    "iniconfig==2.3.0",
    "packaging==25.0",
    "pluggy==1.6.0",
    "pytest==9.0.3",
    "pytest-asyncio==1.3.0",
]
PINNED_BUILD_SYSTEM = [
    "setuptools>=68",
    "wheel",
]
_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _resolve_commit(repo_root: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if result.returncode != 0:
        raise SourceIntegrityError(
            "git_ref_unresolvable",
            f"Could not resolve Git commit {ref!r} in {repo_root}: {result.stderr.strip()}",
            ref=ref,
        )
    return result.stdout.strip()


def _source_date_epoch(repo_root: Path, commit_sha: str) -> int:
    env_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if env_epoch is not None:
        try:
            return int(env_epoch)
        except ValueError as exc:
            raise SourceIntegrityError("invalid_source_date_epoch", f"Invalid SOURCE_DATE_EPOCH: {env_epoch!r}") from exc
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", "-s", "--format=%ct", commit_sha],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if result.returncode != 0:
        raise SourceIntegrityError(
            "git_timestamp_unavailable",
            f"Could not read commit timestamp for {commit_sha}: {result.stderr.strip()}",
            commit_sha=commit_sha,
        )
    return int(result.stdout.strip())


def _export_git_paths(repo_root: Path, commit_sha: str, dest: Path, paths: Sequence[str]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "-C", str(repo_root), "archive", "--format=tar", commit_sha, *paths],
        capture_output=True, timeout=60, check=False,
    )
    if result.returncode != 0:
        raise SourceIntegrityError(
            "git_archive_failed",
            f"git archive failed for {commit_sha}: {result.stderr.decode('utf-8', errors='replace').strip()}",
            commit_sha=commit_sha,
        )
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:*") as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk() or member.name.startswith("/") or ".." in Path(member.name).parts:
                raise SourceIntegrityError(
                    "source_archive_unsafe_member",
                    f"Refusing unsafe tar member in git archive: {member.name}",
                    member=member.name,
                )
        archive.extractall(dest, filter="data")


def _collect_bundle_files(bundle_root: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    seen_norm: Dict[str, str] = {}
    all_paths = sorted(
        (p for p in bundle_root.rglob("*") if p.is_file() or is_reparse_point(p)),
        key=lambda p: p.relative_to(bundle_root).as_posix(),
    )
    for item in all_paths:
        if is_reparse_point(item):
            raise SourceIntegrityError("bundle_reparse_point", f"Bundle contains reparse point: {item}")
        rel = item.relative_to(bundle_root).as_posix()
        if rel == "manifest.json":
            continue
        norm = unicodedata.normalize("NFC", rel).casefold()
        if norm in seen_norm and seen_norm[norm] != rel:
            raise SourceIntegrityError("ambiguous_relative_path", f"Colliding bundle paths: {seen_norm[norm]!r} vs {rel!r}")
        seen_norm[norm] = rel
        data = item.read_bytes()
        records.append({
            "path": rel,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return records


def _write_deterministic_zip(source_dir: Path, zip_path: Path, *, source_date_epoch: int) -> str:
    dt = datetime.fromtimestamp(max(source_date_epoch, 315532800), tz=timezone.utc)
    zip_dt = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    files = sorted(
        (p for p in source_dir.rglob("*") if p.is_file() and not is_reparse_point(p)),
        key=lambda p: p.relative_to(source_dir).as_posix(),
    )
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in files:
            rel = item.relative_to(source_dir).as_posix()
            info = zipfile.ZipInfo(filename=rel, date_time=zip_dt)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, item.read_bytes())
    return hashlib.sha256(zip_path.read_bytes()).hexdigest()


def _render_guest_script() -> str:
    return """#Requires -Version 7.0
param(
    [Parameter(Mandatory)][string]$BundleRoot,
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$bundle = (Resolve-Path -LiteralPath $BundleRoot).Path
$manifest = Join-Path $bundle "manifest.json"
$newSource = Join-Path $bundle "sources\\rc-1.0.0"
$oldSource = Join-Path $bundle "sources\\rc-0.14.0"
$runner = Join-Path $bundle "harness\\windows_acceptance.py"
foreach ($required in @($manifest, $newSource, $oldSource, $runner)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required bundle component missing: $required"
    }
}
$schedule = Get-Service -Name Schedule -ErrorAction Stop
if ($schedule.Status -ne "Running") {
    throw "Windows Task Scheduler service (Schedule) is not running."
}
$pyVer = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
if ($LASTEXITCODE -ne 0) { throw "Python interpreter check failed: $Python" }
$env:PYTHONPATH = (Join-Path $newSource "modules\\resource_coordinator") + [IO.Path]::PathSeparator + (Join-Path $newSource "modules\\resource_metrics")
$run = Join-Path $env:TEMP ("h4-rc-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $run | Out-Null
& $Python $runner --test-root $run --source-root $newSource --old-source-root $oldSource --source-manifest $manifest --json
exit $LASTEXITCODE
"""


def _render_bundle_readme(manifest: Dict[str, Any]) -> str:
    new_src = manifest["sources"][0]
    old_src = manifest["sources"][1]
    return (
        "# H4 Portable Windows Acceptance Bundle\n\n"
        f"Deterministic bundle (`SOURCE_DATE_EPOCH={manifest['source_date_epoch']}`) verified with "
        f"`{HASH_ALGORITHM}` and complete component manifest (`bundle_manifest_version={BUNDLE_MANIFEST_VERSION}`).\n\n"
        f"- **New RC `1.0.0`**: `{new_src['commit_sha']}` (`{new_src['source_tree_sha256']}`)\n"
        f"- **Legacy RC `0.14.0`**: `{old_src['commit_sha']}` (`{old_src['source_tree_sha256']}`)\n"
        "- **In-repo dependency**: `resource-metrics==0.2.0` is staged under `sources/rc-1.0.0/modules/resource_metrics`.\n\n"
        "## Trusted Guest Bootstrap (Read-Only Preflight)\n\n"
        "Verify the external SHA-256 digest BEFORE extracting or running any bundled script:\n\n"
        "```powershell\n"
        "pwsh -File .\\Bootstrap-H4GuestBundle.ps1 -ArchivePath .\\h4-windows-acceptance.zip -ExpectedSha256 <PUBLISHED_SHA256>\n"
        "```\n"
    )


def _validate_zip_members(zf: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    members = zf.infolist()
    if not members:
        raise SourceIntegrityError("bundle_archive_empty", "Bundle archive contains no entries")
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise SourceIntegrityError("bundle_archive_limits_exceeded", f"Archive member count {len(members)} exceeds {MAX_ARCHIVE_MEMBERS}")

    total_size = 0
    seen_exact: set[str] = set()
    seen_norm: Dict[str, str] = {}
    validated: List[zipfile.ZipInfo] = []

    for info in members:
        name = info.filename
        if (
            not name
            or "\x00" in name
            or "\\" in name
            or name.startswith("/")
            or _DRIVE_RE.match(name)
        ):
            raise SourceIntegrityError("bundle_archive_unsafe_member", f"Unsafe archive member path: {name!r}")
        parts = [p for p in name.split("/") if p]
        if any(p in {".", ".."} for p in parts):
            raise SourceIntegrityError("bundle_archive_unsafe_member", f"Path traversal segment in member: {name!r}")

        mode = (info.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK or (mode not in (0, stat.S_IFREG, stat.S_IFDIR)):
            raise SourceIntegrityError("bundle_archive_unsafe_member", f"Unsupported file mode {oct(mode)} for {name!r}")

        canonical = name.rstrip("/")
        if canonical in seen_exact:
            raise SourceIntegrityError("bundle_archive_duplicate_member", f"Duplicate archive member: {canonical!r}")
        seen_exact.add(canonical)
        norm = unicodedata.normalize("NFC", canonical).casefold()
        if norm in seen_norm and seen_norm[norm] != canonical:
            raise SourceIntegrityError(
                "bundle_archive_duplicate_member",
                f"Colliding archive member names: {seen_norm[norm]!r} vs {canonical!r}",
            )
        seen_norm[norm] = canonical

        if info.file_size < 0 or info.compress_size < 0:
            raise SourceIntegrityError("bundle_archive_limits_exceeded", f"Negative size in member: {name!r}")
        if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            raise SourceIntegrityError("bundle_archive_limits_exceeded", f"Member {name!r} exceeds max size {MAX_ARCHIVE_MEMBER_BYTES}")
        if info.file_size > 65536 and (info.compress_size == 0 or (info.file_size / info.compress_size) > MAX_ARCHIVE_COMPRESSION_RATIO):
            raise SourceIntegrityError("bundle_archive_limits_exceeded", f"Suspicious compression ratio on {name!r}")
        total_size += info.file_size
        if total_size > MAX_ARCHIVE_TOTAL_BYTES:
            raise SourceIntegrityError("bundle_archive_limits_exceeded", f"Total uncompressed size exceeds {MAX_ARCHIVE_TOTAL_BYTES}")
        validated.append(info)

    return validated


def verify_bundle_archive(
    zip_path: Path,
    *,
    expected_archive_sha256: Optional[str] = None,
    allow_untrusted_archive: bool = False,
) -> Dict[str, Any]:
    """Verify external archive digest, member safety, every component file, and source trees."""
    if not zip_path.is_file() or is_reparse_point(zip_path):
        raise SourceIntegrityError("bundle_archive_missing", f"Bundle archive missing or unsafe: {zip_path}")
    archive_sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()

    if not allow_untrusted_archive:
        if not expected_archive_sha256 or not _HEX64_RE.match(expected_archive_sha256):
            raise SourceIntegrityError(
                "bundle_archive_digest_required",
                "Expected external 64-hex archive SHA-256 digest is required to verify bundle provenance",
            )
        if archive_sha256.lower() != expected_archive_sha256.lower():
            raise SourceIntegrityError(
                "bundle_archive_digest_mismatch",
                f"Archive SHA-256 mismatch: expected {expected_archive_sha256.lower()}, got {archive_sha256}",
                expected=expected_archive_sha256.lower(),
                actual=archive_sha256,
            )

    with tempfile.TemporaryDirectory(prefix="h4-bundle-verify-") as temp_dir:
        extract_root = Path(temp_dir).resolve()
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                bad_crc = zf.testzip()
                if bad_crc is not None:
                    raise SourceIntegrityError("bundle_archive_corrupt", f"Corrupt CRC on archive member: {bad_crc}")
                members = _validate_zip_members(zf)
                for info in members:
                    target = (extract_root / info.filename).resolve(strict=False)
                    if os.path.commonpath((str(extract_root), str(target))) != str(extract_root):
                        raise SourceIntegrityError("bundle_archive_unsafe_member", f"Zip member escapes extraction root: {info.filename}")
                    zf.extract(info, extract_root)
        except SourceIntegrityError:
            raise
        except (zipfile.BadZipFile, OSError, EOFError, RuntimeError) as exc:
            raise SourceIntegrityError("bundle_archive_corrupt", f"Bundle archive is corrupt or incomplete: {exc}") from exc

        manifest = load_source_manifest(extract_root / "manifest.json")
        if manifest.get("bundle_manifest_version") != BUNDLE_MANIFEST_VERSION or not isinstance(manifest.get("files"), list):
            raise SourceIntegrityError("source_manifest_invalid", "Bundle manifest missing v2 component 'files' table")

        expected_files: Dict[str, Dict[str, Any]] = {}
        for entry in manifest["files"]:
            if not isinstance(entry, dict) or not entry.get("path") or not _HEX64_RE.match(str(entry.get("sha256", ""))):
                raise SourceIntegrityError("source_manifest_invalid", f"Invalid component file entry in manifest: {entry!r}")
            rel = str(entry["path"])
            if rel in expected_files:
                raise SourceIntegrityError("source_manifest_invalid", f"Duplicate manifest file entry: {rel!r}")
            expected_files[rel] = entry

        actual_files = {
            p.relative_to(extract_root).as_posix(): p
            for p in extract_root.rglob("*")
            if p.is_file() and p.relative_to(extract_root).as_posix() != "manifest.json"
        }
        missing = sorted(set(expected_files) - set(actual_files))
        if missing:
            raise SourceIntegrityError("bundle_component_missing", f"Missing manifested component(s): {missing[:5]}")
        unmanifested = sorted(set(actual_files) - set(expected_files))
        if unmanifested:
            raise SourceIntegrityError("bundle_component_mismatch", f"Unmanifested file(s) in bundle: {unmanifested[:5]}")

        for rel, entry in expected_files.items():
            target = actual_files[rel]
            if is_reparse_point(target):
                raise SourceIntegrityError("bundle_archive_unsafe_member", f"Extracted component is a reparse point: {rel}")
            data = target.read_bytes()
            if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"].lower():
                raise SourceIntegrityError(
                    "bundle_component_mismatch",
                    f"Component integrity mismatch for {rel}",
                    component=rel,
                )

        new_entry = manifest_entry_for_role(manifest, "new_1_0_0")
        old_entry = manifest_entry_for_role(manifest, "old_0_14_0")
        new_info = verify_source_tree(
            extract_root / "sources" / "rc-1.0.0",
            expected_version="1.0.0",
            expected_role="new_1_0_0",
            manifest_entry=new_entry,
        )
        old_info = verify_source_tree(
            extract_root / "sources" / "rc-0.14.0",
            expected_version="0.14.0",
            expected_role="old_0_14_0",
            manifest_entry=old_entry,
        )
        return {
            "verified": True,
            "archive_sha256": archive_sha256,
            "hash_algorithm": HASH_ALGORITHM,
            "component_count": len(expected_files),
            "new_1_0_0": new_info,
            "old_0_14_0": old_info,
        }


def build_bundle(
    *,
    repo_root: Path,
    output_dir: Path,
    new_ref: str = "HEAD",
    old_ref: str = DEFAULT_OLD_COMMIT,
    apply: bool = False,
) -> Dict[str, Any]:
    repo = repo_root.expanduser().resolve(strict=True)
    new_commit = _resolve_commit(repo, new_ref)
    old_commit = _resolve_commit(repo, old_ref)
    epoch = _source_date_epoch(repo, new_commit)
    out = output_dir.expanduser().absolute()
    if (out.exists() and is_reparse_point(out)) or any(is_reparse_point(p) for p in out.parents if p.exists()):
        raise SourceIntegrityError("bundle_output_unsafe", f"Output path crosses a reparse point: {out}")
    protected_module = (repo / "modules" / "resource_coordinator" / "resource_coordinator").resolve()
    if os.path.commonpath((str(protected_module), str(out.resolve(strict=False)))) == str(protected_module):
        raise SourceIntegrityError("bundle_output_unsafe", "Output path cannot reside inside live package source")
    if out.exists() and any(out.iterdir()):
        raise SourceIntegrityError("bundle_output_not_empty", f"Destination directory is not empty: {out}")

    plan = {
        "schema_version": 1,
        "status": "planned" if not apply else "built",
        "apply": apply,
        "repository": str(repo),
        "output_dir": str(out),
        "new_commit": new_commit,
        "old_commit": old_commit,
        "source_date_epoch": epoch,
        "hash_algorithm": HASH_ALGORITHM,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }
    if not apply:
        return plan

    bundle_root = out / "h4-windows-acceptance"
    new_dest = bundle_root / "sources" / "rc-1.0.0"
    old_dest = bundle_root / "sources" / "rc-0.14.0"
    _export_git_paths(repo, new_commit, new_dest, ("modules/resource_coordinator", "modules/resource_metrics"))
    _export_git_paths(repo, old_commit, old_dest, ("modules/resource_coordinator", "modules/resource_metrics"))

    new_info = verify_source_tree(new_dest, expected_version="1.0.0")
    old_info = verify_source_tree(old_dest, expected_version="0.14.0")

    harness_dir = bundle_root / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    src_h4 = new_dest / "modules" / "resource_coordinator" / "tools" / "h4_qualification"
    local_h4 = Path(__file__).resolve().parent
    for name in ("windows_acceptance.py", "source_integrity.py", "wddm_probe.py"):
        candidate = src_h4 / name if (src_h4 / name).is_file() else local_h4 / name
        shutil.copy2(candidate, harness_dir / name)

    config_dir = bundle_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        new_dest / "modules" / "resource_coordinator" / "config.production-template.yaml",
        config_dir / "config.production-template.yaml",
    )

    deps_dir = bundle_root / "dependencies"
    deps_dir.mkdir(parents=True, exist_ok=True)
    all_runtime = [*PINNED_RUNTIME_DIRECT, *PINNED_RUNTIME_TRANSITIVE]
    (deps_dir / "requirements.txt").write_text("\n".join(all_runtime) + "\n", encoding="utf-8")
    (deps_dir / "requirements-dev.txt").write_text("\n".join(PINNED_DEV_TEST) + "\n", encoding="utf-8")
    (deps_dir / "dependency-lock.json").write_text(
        json.dumps({
            "schema_version": 2,
            "python_requires": ">=3.10",
            "dependency_status": "resolved_not_hashed",
            "wheelhouse_status": "unavailable",
            "runtime_direct": PINNED_RUNTIME_DIRECT,
            "runtime_transitive": PINNED_RUNTIME_TRANSITIVE,
            "dev_test": PINNED_DEV_TEST,
            "build_system": PINNED_BUILD_SYSTEM,
            "in_repo_packages": {
                "resource-metrics": {
                    "version": "0.2.0",
                    "path": "sources/rc-1.0.0/modules/resource_metrics",
                }
            },
            "guest_hash_verification_note": (
                "PyPI wheel SHA-256 hashes are not staged in-bundle; on a networked guest, generate hashes with "
                "'pip hash' or 'pip download' into a guest-local wheelhouse before installing with --require-hashes."
            ),
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    scripts_dir = bundle_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "Verify-H4GuestBundle.ps1").write_text(_render_guest_script(), encoding="utf-8")

    manifest_stub: Dict[str, Any] = {
        "schema_version": 1,
        "bundle_manifest_version": BUNDLE_MANIFEST_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "source_date_epoch": epoch,
        "tool_python_version": plan["python_version"],
        "sources": [
            {
                "source_role": "new_1_0_0",
                "repository": "https://github.com/MaxCarlson/scripts",
                "commit_sha": new_commit,
                "package_version": "1.0.0",
                "hash_algorithm": HASH_ALGORITHM,
                "source_tree_sha256": new_info["source_tree_sha256"],
                "dependencies": all_runtime,
            },
            {
                "source_role": "old_0_14_0",
                "repository": "https://github.com/MaxCarlson/scripts",
                "commit_sha": old_commit,
                "package_version": "0.14.0",
                "hash_algorithm": HASH_ALGORITHM,
                "source_tree_sha256": old_info["source_tree_sha256"],
                "dependencies": all_runtime,
            },
        ],
    }
    (bundle_root / "README.md").write_text(_render_bundle_readme(manifest_stub), encoding="utf-8")
    manifest_stub["files"] = _collect_bundle_files(bundle_root)
    (bundle_root / "manifest.json").write_text(
        json.dumps(manifest_stub, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )

    zip_path = out / ARCHIVE_FILENAME
    archive_sha256 = _write_deterministic_zip(bundle_root, zip_path, source_date_epoch=epoch)
    (out / f"{ARCHIVE_FILENAME}.sha256").write_text(f"{archive_sha256} *{ARCHIVE_FILENAME}\n", encoding="utf-8")
    verification = verify_bundle_archive(zip_path, expected_archive_sha256=archive_sha256)
    receipt = {
        **plan,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "bundle_dir": str(bundle_root),
        "archive_path": str(zip_path),
        "archive_sha256": archive_sha256,
        "archive_sha256_file": str(out / f"{ARCHIVE_FILENAME}.sha256"),
        "manifest_path": str(bundle_root / "manifest.json"),
        "component_count": verification["component_count"],
        "new_source_tree_sha256": new_info["source_tree_sha256"],
        "old_source_tree_sha256": old_info["source_tree_sha256"],
        "archive_verified": verification["verified"],
    }
    (out / "build-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, help="Empty destination directory for the bundle")
    parser.add_argument("-n", "--new-ref", default="HEAD", help="Git ref/commit for RC 1.0.0 (default: HEAD)")
    parser.add_argument("-l", "--old-ref", default=DEFAULT_OLD_COMMIT, help="Git ref/commit for RC 0.14.0")
    parser.add_argument("-r", "--repo-root", type=Path, default=Path(__file__).resolve().parents[4],
                        help="Git repository root")
    parser.add_argument("-a", "--apply", action="store_true", help="Write the bundle and verify the archive")
    parser.add_argument("-V", "--verify", type=Path, help="Verify an existing bundle ZIP archive")
    parser.add_argument("-E", "--expected-sha256", help="Expected external 64-hex SHA-256 digest for --verify")
    parser.add_argument("-j", "--json", action="store_true", help="Print machine-readable JSON output")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify is not None:
            result = verify_bundle_archive(args.verify, expected_archive_sha256=args.expected_sha256)
        else:
            if args.output is None:
                raise SourceIntegrityError("bundle_output_required", "--output is required when building a bundle")
            result = build_bundle(
                repo_root=args.repo_root,
                output_dir=args.output,
                new_ref=args.new_ref,
                old_ref=args.old_ref,
                apply=args.apply,
            )
    except SourceIntegrityError as exc:
        payload = {"status": "failed", "reason_code": exc.code, "error": str(exc), "details": exc.details}
        print(json.dumps(payload, sort_keys=True) if args.json else str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True) if args.json else f"H4 bundle {result.get('status', 'verified')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
