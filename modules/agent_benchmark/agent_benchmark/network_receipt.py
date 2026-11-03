"""Fail-closed validation of run-bound network qualification evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .study_network_policy import NETWORK_POLICY, NETWORK_POLICY_ID, verify_study_network_manifest

RECEIPT_NAME = "network-qualification.json"
MAX_AGE = timedelta(hours=24)
REQUIRED_GATES = (
    "policy",
    "local_monitor_gateway_route",
    "external_dns_direct_denied",
    "external_tcp_direct_ip_denied",
    "external_dns_name_lookup_denied",
    "external_https_unlisted_sni_denied",
    "external_https_direct_ip_no_sni_denied",
    "no_outbound_proxy_environment",
    "verifier_no_network_denies_monitor",
)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def snapshot_digest(manifest: dict[str, Any], run_dir: Path) -> str:
    network = manifest["provenance"]["study_network"]
    snapshots = network["task_snapshots"]
    if not isinstance(snapshots, dict) or not snapshots or set(snapshots) != set(manifest["tasks"]):
        raise ValueError("task snapshot set is incomplete")
    for task in sorted(snapshots):
        verify_study_network_manifest(manifest, run_dir, task)
    return canonical_sha256(network)


def runtime_fingerprint(image: str, monitor_url: str) -> dict[str, Any]:
    """Measure the selected daemon, image, and Harbor executable without inference."""

    def docker(*args: str) -> Any:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=10, check=True)
        return json.loads(result.stdout)

    info = docker("info", "--format", "{{json .}}")
    images = docker("image", "inspect", image)
    configured_python = os.environ.get("HARBOR_025_PYTHON")
    if not configured_python:
        raise ValueError("HARBOR_025_PYTHON must identify the qualified Harbor runtime")
    python = Path(configured_python).resolve(strict=True)
    runtime_script = r"""
import hashlib, importlib.metadata, json
from pathlib import Path

dist = importlib.metadata.distribution("harbor")
digest = hashlib.sha256()
files = sorted(str(item) for item in (dist.files or []) if str(item).startswith("harbor/")
               and (Path(str(item)).suffix in {".py", ".yaml", ".yml", ".sh", ".toml"}
                    or Path(str(item)).name == "Dockerfile"))
if not files:
    raise RuntimeError("Harbor package files unavailable")
for name in files:
    path = Path(dist.locate_file(name))
    if not path.is_file():
        raise RuntimeError("Harbor package file unavailable")
    digest.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
print(json.dumps({"version": dist.version, "package_sha256": digest.hexdigest()}))
"""
    version_result = subprocess.run(
        [str(python), "-B", "-c", runtime_script],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    harbor_identity = json.loads(version_result.stdout)
    harbor_version = harbor_identity["version"]
    result = {
        "docker_id": info.get("ID"),
        "docker_server_version": info.get("ServerVersion"),
        "docker_os": info.get("OperatingSystem"),
        "docker_host": os.environ.get("DOCKER_HOST", "default"),
        "docker_context": os.environ.get("DOCKER_CONTEXT", "default"),
        "image": image,
        "image_id": images[0].get("Id") if isinstance(images, list) and images else None,
        "harbor_version": harbor_version,
        "harbor_python": str(python),
        "harbor_python_sha256": hashlib.sha256(python.read_bytes()).hexdigest(),
        "harbor_package_sha256": harbor_identity["package_sha256"],
        "monitor_url": monitor_url,
    }
    if any(not isinstance(value, str) or not value for value in result.values()) or harbor_version != "0.25.0":
        raise ValueError("runtime fingerprint contains unavailable measurements")
    return result


def _evidence_matches(receipt: dict[str, Any]) -> bool:
    from .network_qualification import _probe_gates

    evidence = receipt["evidence"]
    return not (
        not isinstance(evidence, dict)
        or evidence.get("status") != "PASS"
        or evidence.get("inference") != "never"
        or evidence.get("benchmark_tasks") != "never"
        or evidence.get("container_created") is not True
        or evidence.get("egress_sidecar_enabled") is not True
        or evidence.get("container_cleanup") != "PASS"
        or evidence.get("gates") != receipt["gates"]
        or evidence.get("created_at") != receipt["created_at"]
        or evidence.get("schema") != "sv-harbor-network-qualification-v1"
        or evidence.get("evidence_origin") != "live-probe"
        or evidence.get("harbor_version") != "0.25.0"
        or evidence.get("harbor_task_config_network_policy") != NETWORK_POLICY
        or evidence.get("effective_verifier_policy") != NETWORK_POLICY["verifier"]
        or evidence.get("policy_id") != NETWORK_POLICY_ID
        or evidence.get("network_policy") != NETWORK_POLICY
        or evidence.get("docker_image") != receipt["runtime"]["image"]
        or evidence.get("probes", {}).get("agent_phase_exit_code") != 0
        or evidence.get("probes", {}).get("verifier_no_network_exit_code") != 0
        or any(
            evidence["gates"].get(k) != v
            for k, v in _probe_gates(evidence["probes"], evidence.get("effective_agent_policy", {})).items()
        )
    )


def make_receipt(
    report: dict[str, Any], manifest: dict[str, Any], run_dir: Path, *, image: str, monitor_url: str
) -> dict[str, Any]:
    created = datetime.fromisoformat(report["created_at"])
    if created.utcoffset() is None:
        raise ValueError("probe timestamp must include a timezone")
    receipt = {
        "schema": "sv-network-receipt-v1",
        "run_id": manifest["run_id"],
        "policy_id": NETWORK_POLICY_ID,
        "network_policy": NETWORK_POLICY,
        "task_snapshot_sha256": snapshot_digest(manifest, run_dir),
        "study_policy_sha256": canonical_sha256(manifest["prompt_policy"]),
        "runtime": runtime_fingerprint(image, monitor_url),
        "created_at": created.isoformat(),
        "expires_at": (created + MAX_AGE).isoformat(),
        "gates": report.get("gates", {}),
        "container_cleanup": report.get("container_cleanup", "UNVERIFIED"),
        "status": report.get("status", "UNVERIFIED"),
        "evidence": report,
    }
    if not isinstance(receipt["gates"], dict) or any(receipt["gates"].get(gate) != "PASS" for gate in REQUIRED_GATES):
        receipt["status"] = "UNVERIFIED"
    try:
        if not _evidence_matches(receipt):
            receipt["status"] = "UNVERIFIED"
    except (AttributeError, KeyError, TypeError, ValueError):
        receipt["status"] = "UNVERIFIED"
    receipt["sha256"] = canonical_sha256(receipt)
    return receipt


class ReceiptRejected(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"NETWORK_QUALIFICATION_{reason}")


def validate_receipt(run_dir: Path | None, manifest: dict[str, Any] | None) -> None:
    if run_dir is None or manifest is None:
        raise ReceiptRejected("MISSING")
    try:
        receipt = json.loads((run_dir / RECEIPT_NAME).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReceiptRejected("MISSING") from exc
    except (OSError, ValueError) as exc:
        raise ReceiptRejected("MALFORMED") from exc
    if not isinstance(receipt, dict):
        raise ReceiptRejected("MALFORMED")
    try:
        digest = receipt["sha256"]
        if not isinstance(digest, str) or digest != canonical_sha256(
            {k: v for k, v in receipt.items() if k != "sha256"}
        ):
            raise ReceiptRejected("INTEGRITY")
        if (
            receipt["schema"] != "sv-network-receipt-v1"
            or receipt["policy_id"] != NETWORK_POLICY_ID
            or receipt["network_policy"] != NETWORK_POLICY
        ):
            raise ReceiptRejected("POLICY_MISMATCH")
        if (
            not isinstance(manifest.get("run_id"), str)
            or not manifest["run_id"]
            or receipt["run_id"] != manifest["run_id"]
        ):
            raise ReceiptRejected("RUN_MISMATCH")
        created = datetime.fromisoformat(receipt["created_at"])
        expires = datetime.fromisoformat(receipt["expires_at"])
        now = datetime.now(timezone.utc)
        if (
            created.utcoffset() is None
            or expires.utcoffset() is None
            or created > now
            or expires <= now
            or expires <= created
            or expires - created > MAX_AGE
        ):
            raise ReceiptRejected("STALE")
        if receipt["status"] != "PASS" or receipt["container_cleanup"] != "PASS":
            raise ReceiptRejected("FAILED")
        if not isinstance(receipt["gates"], dict) or any(
            receipt["gates"].get(gate) != "PASS" for gate in REQUIRED_GATES
        ):
            raise ReceiptRejected("PROBE_FAILED")
        if not _evidence_matches(receipt):
            raise ReceiptRejected("EVIDENCE_MISMATCH")
        if receipt["study_policy_sha256"] != canonical_sha256(manifest["prompt_policy"]):
            raise ReceiptRejected("STUDY_POLICY_MISMATCH")
        if receipt["task_snapshot_sha256"] != snapshot_digest(manifest, run_dir):
            raise ReceiptRejected("SNAPSHOT_MISMATCH")
        runtime = receipt["runtime"]
        expected_url = manifest["provenance"]["effective_base_url"].rstrip("/") + "/chat/completions"
        if runtime["monitor_url"] != expected_url:
            raise ReceiptRejected("ENDPOINT_MISMATCH")
        if not isinstance(runtime, dict) or runtime != runtime_fingerprint(runtime["image"], runtime["monitor_url"]):
            raise ReceiptRejected("RUNTIME_MISMATCH")
    except ReceiptRejected:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        OverflowError,
        OSError,
        subprocess.SubprocessError,
        importlib.metadata.PackageNotFoundError,
    ) as exc:
        raise ReceiptRejected("INCOMPLETE_OR_UNVERIFIED") from exc
