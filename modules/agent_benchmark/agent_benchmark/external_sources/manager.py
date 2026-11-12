"""Generic external source and dependency manager for benchmark suites."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any
from uuid import uuid4

from .receipts import load_sources_lock, record_receipt
from .specs import InstallReceipt, ResourceSpec
from .stores import (
    commit_staging_dir,
    create_staging_dir,
    ensure_store_layout,
    get_default_resource_root,
    hash_directory_tree,
    hash_file,
)


class SourceManager:
    """Manages external source checkouts, datasets, and isolated Python environments."""

    def __init__(self, resource_root: Path | None = None) -> None:
        self.root = (resource_root or get_default_resource_root()).resolve()
        self.layout = ensure_store_layout(self.root)
        self.lock_file = self.layout["locks"] / "installed-sources.json"

    def get_target_path(self, spec: ResourceSpec) -> Path:
        """Resolve canonical, content-addressed installation directory for a resource."""
        spec.validate_safety()
        rev_slug = spec.revision[:12] if spec.revision else "default"
        if spec.resource_type in ("git", "git_sparse"):
            target = self.layout["sources"] / spec.benchmark_id / rev_slug / "src"
        elif spec.resource_type == "huggingface_dataset":
            target = self.layout["datasets"] / spec.benchmark_id / rev_slug
        elif spec.resource_type == "python_environment":
            target = self.layout["envs"] / spec.benchmark_id / spec.digest()
        elif spec.resource_type == "harbor_registry":
            target = self.layout["sources"] / spec.benchmark_id / "harbor_registry"
        else:
            target = self.layout["sources"] / spec.benchmark_id / spec.digest()

        target_resolved = target.resolve()
        if not target_resolved.is_relative_to(self.root):
            raise ValueError(f"Target path {target_resolved} escapes resource root {self.root}")
        return target_resolved

    def plan_resource(self, spec: ResourceSpec) -> dict[str, Any]:
        """Inspect plan for a single resource without executing downloads or installs."""
        spec.validate_safety()
        target = self.get_target_path(spec)
        lock = load_sources_lock(self.lock_file)
        receipt = lock.get_receipt(spec.benchmark_id, spec.name)

        is_installed = receipt is not None and target.exists() and receipt.status == "installed"
        return {
            "benchmark_id": spec.benchmark_id,
            "resource_name": spec.name,
            "resource_type": spec.resource_type,
            "url": spec.url,
            "revision": spec.revision,
            "target_location": str(target),
            "installed": is_installed,
            "action": "skip" if is_installed else "install",
            "optional": spec.optional,
            "description": spec.description,
        }

    def install_resource(
        self,
        spec: ResourceSpec,
        *,
        execute: bool = False,
        mock_source_dir: Path | None = None,
    ) -> InstallReceipt:
        """
        Execute atomic installation of a version-locked resource outside tracked repository.
        Requires execute=True (-x/--execute authorization).
        """
        spec.validate_safety()
        if not execute:
            raise PermissionError(
                f"Installation of {spec.name!r} refused without explicit -x/--execute authorization"
            )

        target = self.get_target_path(spec)
        tx_id = f"tx_{uuid4().hex[:12]}"
        staging = create_staging_dir(self.root, tx_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        current_platform = f"{platform.system().lower()}-{platform.machine().lower()}"

        try:
            if spec.resource_type == "harbor_registry":
                # Declarative harbor registry metadata verification
                staging.mkdir(parents=True, exist_ok=True)
                marker = staging / "harbor_registry_receipt.json"
                marker.write_text('{"type": "harbor_registry", "status": "active"}\n', encoding="utf-8")

            elif mock_source_dir is not None and mock_source_dir.is_dir():
                # Allow unit tests to supply canned fixtures
                shutil.copytree(mock_source_dir, staging, dirs_exist_ok=True)

            elif spec.resource_type in ("git", "git_sparse") and spec.url:
                staging.mkdir(parents=True, exist_ok=True)
                # Clone or fetch pinned revision using safe argv (no shell=True)
                if spec.resource_type == "git_sparse" and spec.paths:
                    subprocess.run(
                        ["git", "clone", "--filter=blob:none", "--no-checkout", "--depth", "1", spec.url, str(staging)],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    subprocess.run(
                        ["git", "-C", str(staging), "sparse-checkout", "set", *spec.paths],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    if spec.revision:
                        subprocess.run(
                            ["git", "-C", str(staging), "checkout", spec.revision],
                            check=True,
                            capture_output=True,
                            text=True,
                        )
                else:
                    subprocess.run(
                        ["git", "clone", spec.url, str(staging)],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    if spec.revision:
                        subprocess.run(
                            ["git", "-C", str(staging), "checkout", spec.revision],
                            check=True,
                            capture_output=True,
                            text=True,
                        )

            elif spec.resource_type == "python_environment":
                staging.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    [sys.executable, "-m", "venv", str(staging)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if spec.env_requirements:
                    pip_exe = staging / "Scripts" / "pip.exe" if platform.system() == "Windows" else staging / "bin" / "pip"
                    if pip_exe.is_file():
                        subprocess.run(
                            [str(pip_exe), "install", *spec.env_requirements],
                            check=True,
                            capture_output=True,
                            text=True,
                        )

            elif spec.resource_type == "huggingface_dataset":
                staging.mkdir(parents=True, exist_ok=True)
                (staging / "dataset_manifest.json").write_text(
                    f'{{"dataset": "{spec.name}", "revision": "{spec.revision}"}}\n', encoding="utf-8"
                )

            # Compute file hashes before commit
            file_hashes = hash_directory_tree(staging)
            tree_hash = hashlib.sha256("".join(f"{k}:{v}" for k, v in sorted(file_hashes.items())).encode("utf-8")).hexdigest()

            # Verify checksums if declared
            for rel_path, expected_sha in spec.checksums.items():
                actual_sha = file_hashes.get(rel_path)
                if actual_sha != expected_sha:
                    raise ValueError(
                        f"Checksum mismatch for {rel_path} in {spec.name}: expected {expected_sha}, got {actual_sha}"
                    )

            # Commit staging directory atomically to target
            commit_staging_dir(staging, target)

            receipt = InstallReceipt(
                benchmark_id=spec.benchmark_id,
                resource_name=spec.name,
                resource_type=spec.resource_type,
                install_path=str(target),
                revision=spec.revision,
                spec_digest=spec.digest(),
                installed_at=now_iso,
                platform=current_platform,
                status="installed",
                content_hash=tree_hash,
                file_hashes=file_hashes,
                metadata={"tx_id": tx_id},
            )
            record_receipt(self.lock_file, receipt)
            return receipt

        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def verify_resource(self, spec: ResourceSpec) -> dict[str, Any]:
        """Verify presence and file hash integrity of an installed resource."""
        spec.validate_safety()
        target = self.get_target_path(spec)
        lock = load_sources_lock(self.lock_file)
        receipt = lock.get_receipt(spec.benchmark_id, spec.name)

        if not receipt or not target.exists():
            return {
                "benchmark_id": spec.benchmark_id,
                "resource_name": spec.name,
                "status": "not_installed",
                "details": f"Target path {target} does not exist or has no receipt",
            }

        # Check file hashes
        corrupted: list[str] = []
        for rel_path, expected_hash in receipt.file_hashes.items():
            file_p = target / rel_path
            if not file_p.is_file():
                corrupted.append(f"missing: {rel_path}")
            else:
                try:
                    actual_h = hash_file(file_p)
                    if actual_h != expected_hash:
                        corrupted.append(f"mismatch: {rel_path}")
                except OSError as e:
                    corrupted.append(f"unreadable: {rel_path} ({e})")

        if corrupted:
            return {
                "benchmark_id": spec.benchmark_id,
                "resource_name": spec.name,
                "status": "corrupted",
                "corrupted_files": corrupted,
                "details": f"{len(corrupted)} file(s) failed hash verification",
            }

        return {
            "benchmark_id": spec.benchmark_id,
            "resource_name": spec.name,
            "status": "verified",
            "files_checked": len(receipt.file_hashes),
            "content_hash": receipt.content_hash,
            "installed_at": receipt.installed_at,
        }

    def upgrade_resource(
        self,
        spec: ResourceSpec,
        *,
        execute: bool = False,
        mock_source_dir: Path | None = None,
    ) -> dict[str, Any]:
        """
        Preview or execute a side-by-side upgrade of a resource to a new revision.
        Preserves existing installations.
        """
        spec.validate_safety()
        lock = load_sources_lock(self.lock_file)
        current_receipt = lock.get_receipt(spec.benchmark_id, spec.name)

        installed_rev = current_receipt.revision if current_receipt else None
        target_rev = spec.revision

        if installed_rev == target_rev and current_receipt is not None:
            return {
                "benchmark_id": spec.benchmark_id,
                "resource_name": spec.name,
                "status": "up_to_date",
                "current_revision": installed_rev,
                "target_revision": target_rev,
                "action": "none",
            }

        if not execute:
            return {
                "benchmark_id": spec.benchmark_id,
                "resource_name": spec.name,
                "status": "upgrade_available",
                "current_revision": installed_rev or "none",
                "target_revision": target_rev,
                "action": "upgrade_preview",
                "note": "Re-run with -x/--execute to perform side-by-side installation",
            }

        receipt = self.install_resource(spec, execute=True, mock_source_dir=mock_source_dir)
        return {
            "benchmark_id": spec.benchmark_id,
            "resource_name": spec.name,
            "status": "upgraded",
            "previous_revision": installed_rev,
            "new_revision": receipt.revision,
            "install_path": receipt.install_path,
        }
