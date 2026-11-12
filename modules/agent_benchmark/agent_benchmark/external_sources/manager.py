"""Generic external source and dependency manager for benchmark suites."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
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
    get_store_layout,
    hash_directory_tree,
    hash_file,
)


def image_reference(spec: ResourceSpec) -> str:
    """Exact image reference (digest-pinned where declared) shared by setup and the verifier."""
    return spec.url or spec.name


def inspect_image(ref: str, *, timeout: float = 5.0) -> tuple[str, str | None, str]:
    """
    Inspect exactly ``ref`` in the local Docker daemon.

    Returns ``(state, image_id, detail)`` where state is ``available`` (present, and carrying the
    pinned digest if one is declared), ``missing`` (daemon reachable, image absent/mismatched) or
    ``unavailable`` (Docker missing or daemon unreachable).
    """
    docker_cmd = shutil.which("docker")
    if not docker_cmd:
        return "unavailable", None, "Docker executable not found on host"
    try:
        res = subprocess.run(
            [docker_cmd, "image", "inspect", ref, "--format", "{{.Id}}|{{json .RepoDigests}}"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return "unavailable", None, f"docker inspect failed: {exc}"
    err = (res.stderr or "").lower()
    if res.returncode != 0:
        if "no such image" in err or "no such object" in err:
            return "missing", None, "image not present"
        return "unavailable", None, (res.stderr or "docker daemon unreachable").strip()[:200]
    out = res.stdout.strip()
    image_id, _, repo_digests = out.partition("|")
    if not image_id:
        return "missing", None, "empty inspect result"
    if "@sha256:" in ref:
        digest = ref.split("@", 1)[1]
        if digest not in repo_digests:
            return "missing", image_id, f"local image does not carry pinned digest {digest}"
    return "available", image_id, "ok"


class SourceManager:
    """Manages external source checkouts, datasets, and isolated Python environments."""

    def __init__(self, resource_root: Path | None = None) -> None:
        self.root = (resource_root or get_default_resource_root()).resolve()
        self.layout = get_store_layout(self.root)
        self.lock_file = self.layout["locks"] / "installed-sources.json"

    def resolve_installed_path(self, benchmark_id: str, resource_name: str) -> Path | None:
        """
        Resolve the installed directory or file path for a benchmark resource
        using verified installation receipts or canonical layout.
        """
        lock = load_sources_lock(self.lock_file)
        receipt = lock.get_receipt(benchmark_id, resource_name)
        if receipt and receipt.status in ("installed", "verified"):
            p = Path(receipt.install_path)
            if p.exists():
                return p.resolve()

        # Fallback check canonical locations under layout
        for category in ("datasets", "sources", "envs"):
            parent = self.layout[category] / benchmark_id
            if parent.is_dir():
                for child in parent.iterdir():
                    if child.is_dir():
                        if category == "sources" and (child / "src").is_dir():
                            return (child / "src").resolve()
                        return child.resolve()
        return None

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

        if spec.resource_type == "container_image":
            ref = image_reference(spec)
            state, image_id, _detail = inspect_image(ref, timeout=5.0)
            is_present = state == "available"
            return {
                "benchmark_id": spec.benchmark_id,
                "resource_name": spec.name,
                "resource_type": spec.resource_type,
                "url": spec.url,
                "revision": spec.revision,
                "image_reference": ref,
                "target_location": f"docker://{ref}",
                "installed": is_present,
                "availability": state,
                "action": "skip" if is_present else "externally_managed_prerequisite",
                "optional": spec.optional,
                "description": spec.description,
                "image_id": image_id,
            }

        is_stale = receipt is not None and (
            receipt.spec_digest != spec.digest() or receipt.revision != spec.revision
        )
        verification = self.verify_resource(spec) if receipt is not None else {"status": "not_installed"}
        is_installed = verification.get("status") == "verified" and not is_stale
        action = "skip" if is_installed else ("upgrade" if is_stale else ("repair" if receipt is not None and verification.get("status") != "not_installed" else "install"))

        return {
            "benchmark_id": spec.benchmark_id,
            "resource_name": spec.name,
            "resource_type": spec.resource_type,
            "url": spec.url,
            "revision": spec.revision,
            "target_location": str(target),
            "installed": is_installed,
            "action": action,
            "verification_status": verification.get("status"),
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

        # Ensure root directory layout exists only when authorized to execute
        self.layout = ensure_store_layout(self.root)
        plan = self.plan_resource(spec)
        if plan["action"] == "skip":
            receipt = load_sources_lock(self.lock_file).get_receipt(spec.benchmark_id, spec.name)
            if receipt is not None:
                return receipt
        if plan["action"] == "upgrade":
            raise RuntimeError(f"Resource {spec.name!r} has a stale revision/specification; use setup upgrade.")
        if Path(plan["target_location"]).exists():
            raise RuntimeError(f"Resource target already exists without a current valid receipt; repair required: {plan['target_location']}")
        now_iso = datetime.now(timezone.utc).isoformat()
        current_platform = f"{platform.system().lower()}-{platform.machine().lower()}"
        tx_id = f"tx_{uuid4().hex[:12]}"

        if spec.resource_type == "container_image":
            ref = image_reference(spec)
            state, image_id, detail = inspect_image(ref, timeout=10.0)
            if state == "unavailable":
                raise RuntimeError(
                    f"Container image resource '{spec.name}' ({ref}) cannot be verified: {detail}. "
                    f"Docker must be installed and its daemon running."
                )
            if state != "available" or not image_id:
                raise RuntimeError(
                    f"Container image '{ref}' is not present in local Docker daemon. "
                    f"It is an externally managed prerequisite; run: docker pull {ref}"
                )
            receipt = InstallReceipt(
                benchmark_id=spec.benchmark_id,
                resource_name=spec.name,
                resource_type=spec.resource_type,
                install_path=f"docker://{ref}",
                revision=spec.revision,
                spec_digest=spec.digest(),
                installed_at=now_iso,
                platform=current_platform,
                status="installed",
                content_hash=image_id,
                file_hashes={},
                metadata={"tx_id": tx_id, "docker_image_id": image_id, "image_reference": ref},
            )
            record_receipt(self.lock_file, receipt)
            return receipt

        target = self.get_target_path(spec)
        staging = create_staging_dir(self.root, tx_id)

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
                    def git(stage: str, argv: list[str]) -> subprocess.CompletedProcess[str]:
                        try:
                            result = subprocess.run(argv, capture_output=True, text=True)
                        except OSError as exc:
                            raise RuntimeError(f"Git {stage} could not execute {argv[0]!r}; target={target}; staging={staging}: {exc}") from exc
                        if result.returncode:
                            raise RuntimeError(
                                f"Git {stage} failed ({argv[0]} {' '.join(argv[1:])}); exit={result.returncode}; "
                                f"target={target}; staging={staging}; stderr={(result.stderr or '')[-2000:]}; "
                                f"stdout={(result.stdout or '')[-1000:]}"
                            )
                        return result
                    git("clone", ["git", "clone", "--filter=blob:none", "--no-checkout", spec.url, str(staging)])
                    git("sparse-checkout", ["git", "-C", str(staging), "sparse-checkout", "init", "--cone"])
                    git("sparse-checkout", ["git", "-C", str(staging), "sparse-checkout", "set", *spec.paths])
                    rev = spec.revision or "HEAD"
                    git("checkout", ["git", "-C", str(staging), "checkout", "--detach", rev])
                    actual = git("validation", ["git", "-C", str(staging), "rev-parse", "HEAD"]).stdout.strip()
                    if spec.revision and actual != spec.revision:
                        raise RuntimeError(f"Pinned Git revision mismatch: expected {spec.revision}, got {actual}; target={target}; staging={staging}")
                    for required in spec.paths:
                        if not (staging / required).exists():
                            raise RuntimeError(f"Git validation failed: required path {required!r} missing; target={target}; staging={staging}")
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
                py_exe = staging / "Scripts" / "python.exe" if platform.system() == "Windows" else staging / "bin" / "python"
                if not py_exe.is_file():
                    raise RuntimeError(f"Virtual environment creation failed: missing python executable at {py_exe}")

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
                import httpx

                raw_url = spec.url or ""
                repo_id = raw_url.replace("https://huggingface.co/datasets/", "").strip("/") or spec.name
                files_to_download = list(spec.paths) if spec.paths else ["dataset_manifest.json"]

                for rel_file in files_to_download:
                    dest_file = staging / rel_file
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    dl_url = f"https://huggingface.co/datasets/{repo_id}/resolve/{spec.revision}/{rel_file}"
                    try:
                        with httpx.stream("GET", dl_url, follow_redirects=True, timeout=120.0) as resp:
                            if resp.status_code == 404:
                                raise ValueError(f"Hugging Face dataset file not found: {dl_url}")
                            resp.raise_for_status()
                            with dest_file.open("wb") as f_out:
                                for chunk in resp.iter_bytes(chunk_size=65536):
                                    f_out.write(chunk)
                    except Exception as dl_err:
                        if not dest_file.exists():
                            raise RuntimeError(
                                f"Failed to download Hugging Face dataset resource '{spec.name}' from {dl_url}: {dl_err}"
                            ) from dl_err

                    # Content validation: file must exist, non-empty, and valid JSONL if .jsonl
                    if not dest_file.is_file() or dest_file.stat().st_size == 0:
                        raise ValueError(f"Downloaded dataset file {rel_file} is empty or missing")
                    if rel_file.endswith(".jsonl"):
                        with dest_file.open("r", encoding="utf-8") as f_check:
                            first_line = f_check.readline()
                            if not first_line.strip():
                                raise ValueError(f"Downloaded JSONL file {rel_file} has empty first line")
                            json.loads(first_line)

                (staging / "dataset_manifest.json").write_text(
                    json.dumps({
                        "dataset": spec.name,
                        "revision": spec.revision,
                        "repo_id": repo_id,
                        "files": files_to_download,
                    }, indent=2) + "\n",
                    encoding="utf-8",
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
        lock = load_sources_lock(self.lock_file)
        receipt = lock.get_receipt(spec.benchmark_id, spec.name)

        if spec.resource_type == "container_image":
            ref = image_reference(spec)
            state, image_id, detail = inspect_image(ref, timeout=5.0)
            if state == "unavailable":
                return {
                    "benchmark_id": spec.benchmark_id,
                    "resource_name": spec.name,
                    "status": "unavailable",
                    "image_reference": ref,
                    "details": f"Docker unavailable: {detail}",
                }
            if state == "missing":
                return {
                    "benchmark_id": spec.benchmark_id,
                    "resource_name": spec.name,
                    "status": "not_installed",
                    "image_reference": ref,
                    "details": f"Container image {ref} not found in local Docker daemon",
                }
            return {
                "benchmark_id": spec.benchmark_id,
                "resource_name": spec.name,
                "status": "verified",
                "image_reference": ref,
                "details": f"Container image {ref} verified ({image_id[:19]})",
                "content_hash": image_id,
            }

        target = self.get_target_path(spec)

        if not receipt:
            return {
                "benchmark_id": spec.benchmark_id,
                "resource_name": spec.name,
                "status": "not_installed",
                "details": f"Target path {target} has no recorded receipt in installed-sources.json",
            }

        if spec.revision and receipt.revision and receipt.revision != spec.revision:
            return {
                "benchmark_id": spec.benchmark_id,
                "resource_name": spec.name,
                "status": "stale",
                "installed_revision": receipt.revision,
                "expected_revision": spec.revision,
                "details": f"Installed revision {receipt.revision} does not match expected revision {spec.revision}",
            }

        if not target.exists():
            return {
                "benchmark_id": spec.benchmark_id,
                "resource_name": spec.name,
                "status": "incomplete",
                "details": f"Target path {target} does not exist on disk",
            }

        if spec.resource_type == "python_environment":
            py_exe = target / "Scripts" / "python.exe" if platform.system() == "Windows" else target / "bin" / "python"
            if not py_exe.is_file():
                return {
                    "benchmark_id": spec.benchmark_id,
                    "resource_name": spec.name,
                    "status": "incomplete",
                    "details": f"Python executable missing in virtual environment at {py_exe}",
                }

        # Check required paths
        if spec.paths:
            for p in spec.paths:
                if not (target / p).exists():
                    return {
                        "benchmark_id": spec.benchmark_id,
                        "resource_name": spec.name,
                        "status": "incomplete",
                        "details": f"Required resource file or directory missing: {p}",
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
