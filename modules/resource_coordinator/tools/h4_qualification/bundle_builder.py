#!/usr/bin/env python3
"""Build and verify a portable Windows H4 acceptance bundle from immutable Git commits."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

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
FIXED_ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
ARCHIVE_FILENAME = "h4-windows-acceptance.zip"

PINNED_DEPENDENCIES = [
    "anyio==4.12.1",
    "httpx==0.28.1",
    "starlette==0.50.0",
    "uvicorn==0.40.0",
    "psutil==7.1.3",
    "pyyaml==6.0.3",
    "rich==14.2.0",
]
PINNED_DEV_DEPENDENCIES = [
    "pytest==9.0.3",
    "pytest-asyncio==1.3.0",
]


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


def _write_deterministic_zip(source_dir: Path, zip_path: Path) -> str:
    files = sorted(
        (p for p in source_dir.rglob("*") if p.is_file() and not is_reparse_point(p)),
        key=lambda p: p.relative_to(source_dir).as_posix(),
    )
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in files:
            rel = item.relative_to(source_dir).as_posix()
            info = zipfile.ZipInfo(filename=rel, date_time=FIXED_ZIP_TIMESTAMP)
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
        "This bundle is generated from immutable Git commits and verified with "
        f"`{HASH_ALGORITHM}`.\n\n"
        f"- **New RC `1.0.0`**: `{new_src['commit_sha']}` (`{new_src['source_tree_sha256']}`)\n"
        f"- **Legacy RC `0.14.0`**: `{old_src['commit_sha']}` (`{old_src['source_tree_sha256']}`)\n"
        "- **In-repo dependency**: `resource-metrics==0.2.0` is staged under `sources/rc-1.0.0/modules/resource_metrics`.\n\n"
        "## Guest Verification (Read-Only Preflight)\n\n"
        "```powershell\n"
        "pwsh -File .\\scripts\\Verify-H4GuestBundle.ps1 -BundleRoot .\n"
        "```\n\n"
        "Mutating guest profiles (`task`, `install`, `upgrade`, `rollback`, `full`, `cleanup`) "
        "require a standard Hyper-V checkpoint, `--apply`, `--authorize-guest-mutation`, "
        "and `RC_H4_DISPOSABLE_GUEST_AUTHORIZED`.\n"
    )


def verify_bundle_archive(zip_path: Path) -> Dict[str, Any]:
    """Extract *zip_path* to an isolated temp directory and verify its manifest & source trees."""
    if not zip_path.is_file() or is_reparse_point(zip_path):
        raise SourceIntegrityError("bundle_archive_missing", f"Bundle archive missing or unsafe: {zip_path}")
    archive_sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="h4-bundle-verify-") as temp_dir:
        extract_root = Path(temp_dir)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.infolist():
                    target = (extract_root / member.filename).resolve(strict=False)
                    if os.path.commonpath((str(extract_root.resolve()), str(target))) != str(extract_root.resolve()):
                        raise SourceIntegrityError(
                            "bundle_archive_unsafe_member",
                            f"Zip member escapes extraction root: {member.filename}",
                        )
                zf.extractall(extract_root)
        except (zipfile.BadZipFile, OSError, EOFError) as exc:
            raise SourceIntegrityError(
                "bundle_archive_corrupt",
                f"Bundle archive is corrupt or incomplete: {exc}",
            ) from exc
        manifest = load_source_manifest(extract_root / "manifest.json")
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
    (deps_dir / "requirements.txt").write_text("\n".join(PINNED_DEPENDENCIES) + "\n", encoding="utf-8")
    (deps_dir / "requirements-dev.txt").write_text("\n".join(PINNED_DEV_DEPENDENCIES) + "\n", encoding="utf-8")
    (deps_dir / "dependency-lock.json").write_text(
        json.dumps({
            "schema_version": 1,
            "python_requires": ">=3.10",
            "runtime_packages": PINNED_DEPENDENCIES,
            "dev_packages": PINNED_DEV_DEPENDENCIES,
            "in_repo_packages": {"resource-metrics": {"version": "0.2.0", "path": "sources/rc-1.0.0/modules/resource_metrics"}},
            "offline_wheels_staged": False,
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    scripts_dir = bundle_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "Verify-H4GuestBundle.ps1").write_text(_render_guest_script(), encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "hash_algorithm": HASH_ALGORITHM,
        "bundle_created_at": datetime.now(timezone.utc).isoformat(),
        "tool_python_version": plan["python_version"],
        "sources": [
            {
                "source_role": "new_1_0_0",
                "repository": "https://github.com/MaxCarlson/scripts",
                "commit_sha": new_commit,
                "package_version": "1.0.0",
                "hash_algorithm": HASH_ALGORITHM,
                "source_tree_sha256": new_info["source_tree_sha256"],
                "dependencies": PINNED_DEPENDENCIES,
            },
            {
                "source_role": "old_0_14_0",
                "repository": "https://github.com/MaxCarlson/scripts",
                "commit_sha": old_commit,
                "package_version": "0.14.0",
                "hash_algorithm": HASH_ALGORITHM,
                "source_tree_sha256": old_info["source_tree_sha256"],
                "dependencies": PINNED_DEPENDENCIES,
            },
        ],
    }
    (bundle_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (bundle_root / "README.md").write_text(_render_bundle_readme(manifest), encoding="utf-8")

    zip_path = out / ARCHIVE_FILENAME
    archive_sha256 = _write_deterministic_zip(bundle_root, zip_path)
    verification = verify_bundle_archive(zip_path)
    return {
        **plan,
        "bundle_dir": str(bundle_root),
        "archive_path": str(zip_path),
        "archive_sha256": archive_sha256,
        "manifest_path": str(bundle_root / "manifest.json"),
        "new_source_tree_sha256": new_info["source_tree_sha256"],
        "old_source_tree_sha256": old_info["source_tree_sha256"],
        "archive_verified": verification["verified"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", required=True, type=Path, help="Empty destination directory for the bundle")
    parser.add_argument("-n", "--new-ref", default="HEAD", help="Git ref/commit for RC 1.0.0 (default: HEAD)")
    parser.add_argument("-l", "--old-ref", default=DEFAULT_OLD_COMMIT, help="Git ref/commit for RC 0.14.0")
    parser.add_argument("-r", "--repo-root", type=Path, default=Path(__file__).resolve().parents[4],
                        help="Git repository root")
    parser.add_argument("-a", "--apply", action="store_true", help="Write the bundle and verify the archive")
    parser.add_argument("-j", "--json", action="store_true", help="Print machine-readable JSON output")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
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
    print(json.dumps(result, sort_keys=True) if args.json else f"H4 bundle {result['status']}: {result['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
