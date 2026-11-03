"""Run-owned Harbor task snapshots with the study's explicit egress policy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import tomllib
from typing import Any

NETWORK_POLICY_ID = "sv-network-policy-v1"
NETWORK_POLICY: dict[str, dict[str, Any]] = {
    "environment": {"network_mode": "public"},
    "agent": {"network_mode": "allowlist", "allowed_hosts": ["host.docker.internal"]},
    "verifier": {"network_mode": "no-network"},
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_REVISION = "f30b14415dd733c83627204bad0af69a89ceb46f"
_SOURCE_GIT_URL = "https://github.com/laude-institute/harbor-datasets.git"


def _tree_sha256(root: Path, *, task_toml_override: bytes | None = None) -> str:
    """Hash regular files and their relative names; reject links/special entries."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"study task tree contains a symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"study task tree contains a non-regular entry: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = (
            task_toml_override
            if task_toml_override is not None and path.name == "task.toml" and path.parent == root
            else path.read_bytes()
        )
        digest.update(relative + b"\0" + hashlib.sha256(content).digest())
    return digest.hexdigest()


def _verifier_sha256(root: Path) -> str:
    tests = root / "tests"
    if not tests.is_dir():
        raise ValueError("study task verifier directory is missing")
    digest = hashlib.sha256()
    for path in sorted(tests.rglob("*")):
        if path.is_symlink():
            raise ValueError("study verifier tree contains a symlink")
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _insert_after_section(text: str, section: str, values: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == f"[{section}]"]
    if len(matches) != 1:
        raise ValueError(f"task.toml must contain exactly one [{section}] section")
    index = matches[0]
    section_end = next(
        (i for i in range(index + 1, len(lines)) if lines[i].lstrip().startswith("[")),
        len(lines),
    )
    section_text = "".join(lines[index + 1:section_end])
    if re.search(r"(?m)^\s*(?:network_mode|allowed_hosts)\s*=", section_text):
        raise ValueError("task.toml network policy metadata already exists")
    newline = "\r\n" if "\r\n" in lines[index] else "\n"
    header = lines[index]
    if not header.endswith(("\n", "\r")):
        header += newline
    lines[index] = header
    lines[index + 1:index + 1] = [value + newline for value in values]
    return "".join(lines)


def _apply_network_policy(task_toml: Path) -> None:
    try:
        original_text = task_toml.read_bytes().decode("utf-8")
        original_config = tomllib.loads(original_text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError("study task.toml is not valid UTF-8 TOML") from error
    required_sections = {"environment", "agent", "verifier"}
    if not required_sections.issubset(original_config):
        raise ValueError("study task.toml is missing an environment, agent, or verifier section")
    if any(
        key in original_config.get(section, {})
        for section in required_sections
        for key in ("network_mode", "allowed_hosts")
    ):
        raise ValueError("task.toml network policy metadata already exists")

    text = original_text
    text = _insert_after_section(text, "environment", ['network_mode = "public"'])
    text = _insert_after_section(
        text, "agent", ['network_mode = "allowlist"', 'allowed_hosts = ["host.docker.internal"]']
    )
    text = _insert_after_section(text, "verifier", ['network_mode = "no-network"'])
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError("generated task network policy is not valid TOML") from error
    for section, expected in NETWORK_POLICY.items():
        actual = {key: config[section].get(key) for key in expected}
        if actual != expected:
            raise ValueError(f"generated task network policy is invalid for [{section}]")
    task_toml.write_bytes(text.encode("utf-8"))


def _restore_original_task_toml(task_toml: bytes) -> bytes:
    newline = b"\r\n" if b"\r\n" in task_toml else b"\n"
    expected = [
        b'network_mode = "public"' + newline,
        b'network_mode = "allowlist"' + newline,
        b'allowed_hosts = ["host.docker.internal"]' + newline,
        b'network_mode = "no-network"' + newline,
    ]
    lines = task_toml.splitlines(keepends=True)
    for value in expected:
        if lines.count(value) != 1:
            raise ValueError("derived task.toml does not contain the exact declared network metadata")
        lines.remove(value)
    return b"".join(lines)


def materialize_study_task_snapshot(
    *,
    run_dir: Path,
    source_path: Path,
    task_id: str,
    source_revision: str,
    source_git_url: str,
    original_task_sha256: str,
    original_verifier_sha256: str,
) -> dict[str, Any]:
    """Copy a verified original task and apply only the approved task.toml policy."""
    from .study_task_integrity import EXPECTED

    if task_id not in EXPECTED or source_revision != _SOURCE_REVISION or source_git_url != _SOURCE_GIT_URL:
        raise ValueError("unsupported frozen study task source")
    if not _SHA256.fullmatch(original_task_sha256) or not _SHA256.fullmatch(original_verifier_sha256):
        raise ValueError("original study task identity is incomplete")
    source_input = Path(source_path)
    if source_input.is_symlink():
        raise ValueError("resolved Harbor source task path is invalid")
    source = source_input.resolve(strict=True)
    if not source.is_dir() or source.name != task_id:
        raise ValueError("resolved Harbor source task path is invalid")
    if (source / "task.toml").is_symlink() or not (source / "task.toml").is_file():
        raise ValueError("resolved Harbor source task.toml is missing or unsafe")
    if _verifier_sha256(source) != original_verifier_sha256:
        raise ValueError("original verifier bytes do not match the frozen fingerprint")
    if (original_task_sha256, original_verifier_sha256) != EXPECTED[task_id]:
        raise ValueError("original study task identity does not match the frozen fingerprint")
    original_tree_sha256 = _tree_sha256(source)
    original_task_toml = (source / "task.toml").read_bytes()
    target = Path(run_dir).resolve() / "study-network" / "tasks" / task_id
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=True)
    if _tree_sha256(target) != original_tree_sha256 or _tree_sha256(source) != original_tree_sha256:
        raise ValueError("source task changed while the network-policy snapshot was copied")
    if _verifier_sha256(target) != original_verifier_sha256:
        raise ValueError("copied verifier bytes differ from the original frozen verifier")
    _apply_network_policy(target / "task.toml")
    return {
        "schema": "sv-study-task-network-snapshot-v1",
        "policy_id": NETWORK_POLICY_ID,
        "task_id": task_id,
        "source_git_url": source_git_url,
        "source_revision": source_revision,
        "snapshot_path": (Path("study-network") / "tasks" / task_id).as_posix(),
        "original_task_sha256": original_task_sha256,
        "original_verifier_sha256": original_verifier_sha256,
        "derived_verifier_sha256": _verifier_sha256(target),
        "original_tree_sha256": original_tree_sha256,
        "original_task_toml_sha256": hashlib.sha256(original_task_toml).hexdigest(),
        "derived_task_toml_sha256": hashlib.sha256((target / "task.toml").read_bytes()).hexdigest(),
        "derived_tree_sha256": _tree_sha256(target),
        "network_policy": json.loads(json.dumps(NETWORK_POLICY)),
    }


def verify_study_task_snapshot(run_dir: Path, metadata: dict[str, Any]) -> Path:
    """Fail closed if the run-owned derived task or declared policy drifted."""
    if metadata.get("schema") != "sv-study-task-network-snapshot-v1" or metadata.get("policy_id") != NETWORK_POLICY_ID:
        raise ValueError("study network snapshot identity is unsupported")
    if (metadata.get("source_git_url") != _SOURCE_GIT_URL
            or metadata.get("source_revision") != _SOURCE_REVISION):
        raise ValueError("study network snapshot source provenance changed")
    if metadata.get("network_policy") != NETWORK_POLICY:
        raise ValueError("study network policy metadata changed")
    task_id = metadata.get("task_id")
    if not isinstance(task_id, str) or task_id not in {
        "polyglot_python_beer-song", "polyglot_python_bottle-song", "polyglot_python_bowling"
    }:
        raise ValueError("study network snapshot task is unsupported")
    expected_relative = (Path("study-network") / "tasks" / task_id).as_posix()
    if metadata.get("snapshot_path") != expected_relative:
        raise ValueError("study network snapshot path changed")
    root = Path(run_dir).resolve(strict=True)
    candidate = root / expected_relative
    if candidate.is_symlink():
        raise ValueError("study network snapshot path is unsafe")
    task_path = candidate.resolve(strict=True)
    if not task_path.is_relative_to(root) or not task_path.is_dir():
        raise ValueError("study network snapshot path is unsafe")
    if _tree_sha256(task_path) != metadata.get("derived_tree_sha256"):
        raise ValueError("study network snapshot changed after run creation")
    derived_verifier_sha256 = _verifier_sha256(task_path)
    if (derived_verifier_sha256 != metadata.get("original_verifier_sha256")
            or derived_verifier_sha256 != metadata.get("derived_verifier_sha256")):
        raise ValueError("derived snapshot verifier bytes differ from the frozen original")
    from .study_task_integrity import EXPECTED

    if (metadata.get("original_task_sha256"), metadata.get("original_verifier_sha256")) != EXPECTED[task_id]:
        raise ValueError("study network snapshot original identity differs from the frozen fingerprint")
    task_toml = (task_path / "task.toml").read_bytes()
    restored_task_toml = _restore_original_task_toml(task_toml)
    if hashlib.sha256(restored_task_toml).hexdigest() != metadata.get("original_task_toml_sha256"):
        raise ValueError("derived task.toml differs beyond the declared network-policy overlay")
    if hashlib.sha256(task_toml).hexdigest() != metadata.get("derived_task_toml_sha256"):
        raise ValueError("derived task.toml digest differs from snapshot provenance")
    if _tree_sha256(task_path, task_toml_override=restored_task_toml) != metadata.get("original_tree_sha256"):
        raise ValueError("derived task snapshot contains content outside the approved metadata overlay")
    try:
        config = tomllib.loads((task_path / "task.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError("study network snapshot task.toml is unavailable or invalid") from error
    for section, expected in NETWORK_POLICY.items():
        if any(config.get(section, {}).get(key) != value for key, value in expected.items()):
            raise ValueError(f"study network policy drift in [{section}]")
    return task_path


def verify_study_network_manifest(manifest: dict[str, Any], run_dir: Path, task_id: str) -> tuple[Path, dict[str, Any]]:
    """Verify the selected task is bound to the exact manifest's restrictive policy."""
    provenance = manifest.get("provenance", {})
    policy = provenance.get("study_network")
    if not isinstance(policy, dict) or policy.get("policy_id") != NETWORK_POLICY_ID:
        raise ValueError("study run has no declared network policy")
    if policy.get("network_policy") != NETWORK_POLICY:
        raise ValueError("study run network policy is missing or unsupported")
    if policy["network_policy"].get("agent", {}).get("network_mode") == "public":
        raise ValueError("public agent network policy is forbidden for study dispatch")
    snapshots = policy.get("task_snapshots")
    if not isinstance(snapshots, dict) or task_id not in snapshots:
        raise ValueError("study run has no frozen network snapshot for selected task")
    row = snapshots[task_id]
    task_path = verify_study_task_snapshot(run_dir, row)
    return task_path, row
