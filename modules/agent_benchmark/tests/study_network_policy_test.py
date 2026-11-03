from __future__ import annotations

import hashlib
import os
import tomllib
from pathlib import Path

import pytest

from agent_benchmark.study_network_policy import (
    NETWORK_POLICY,
    NETWORK_POLICY_ID,
    materialize_study_task_snapshot,
    verify_study_task_snapshot,
)

_TASK_ID = "polyglot_python_beer-song"
_REVISION = "f30b14415dd733c83627204bad0af69a89ceb46f"
_REPOSITORY = "https://github.com/laude-institute/harbor-datasets.git"


def _task_tree(root: Path) -> Path:
    task = root / _TASK_ID
    (task / "tests").mkdir(parents=True)
    (task / "task.toml").write_text(
        'version = "1.0"\n[verifier]\ntimeout_sec = 1800\n[agent]\ntimeout_sec = 1800\n[environment]\ncpus = 1\n',
        encoding="utf-8",
    )
    (task / "tests" / "test_contract.py").write_bytes(b"assert True\n")
    (task / "instruction.md").write_bytes(b"Original instructions.\n")
    return task


def _verifier_hash(task: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((task / "tests").rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(task).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _set_expected(monkeypatch, task: Path, task_sha256: str = "a" * 64) -> str:
    from agent_benchmark.study_task_integrity import EXPECTED

    verifier_sha256 = _verifier_hash(task)
    monkeypatch.setitem(EXPECTED, task.name, (task_sha256, verifier_sha256))
    return verifier_sha256


def test_materialized_snapshot_changes_only_declared_network_metadata(tmp_path: Path, monkeypatch):
    original = _task_tree(tmp_path / "source")
    original_verifier = _set_expected(monkeypatch, original)
    run_dir = tmp_path / "run"

    metadata = materialize_study_task_snapshot(
        run_dir=run_dir,
        source_path=original,
        task_id=original.name,
        source_revision=_REVISION,
        source_git_url=_REPOSITORY,
        original_task_sha256="a" * 64,
        original_verifier_sha256=original_verifier,
    )
    target = run_dir / "study-network" / "tasks" / original.name

    assert metadata["policy_id"] == NETWORK_POLICY_ID
    assert metadata["network_policy"] == NETWORK_POLICY
    assert metadata["derived_verifier_sha256"] == metadata["original_verifier_sha256"]
    assert (target / "instruction.md").read_bytes() == (original / "instruction.md").read_bytes()
    assert (target / "tests" / "test_contract.py").read_bytes() == (
        original / "tests" / "test_contract.py"
    ).read_bytes()
    config = tomllib.loads((target / "task.toml").read_text(encoding="utf-8"))
    assert config["environment"]["network_mode"] == "public"
    assert config["agent"]["network_mode"] == "allowlist"
    assert config["agent"]["allowed_hosts"] == ["host.docker.internal"]
    assert config["verifier"]["network_mode"] == "no-network"
    assert metadata["derived_tree_sha256"]
    assert hashlib.sha256((original / "task.toml").read_bytes()).hexdigest() == metadata["original_task_toml_sha256"]
    derived_task_toml = (target / "task.toml").read_bytes()
    policy_lines = (
        b'network_mode = "public"\n'
        b'network_mode = "allowlist"\n'
        b'allowed_hosts = ["host.docker.internal"]\n'
        b'network_mode = "no-network"\n'
    )
    if b"\r\n" in derived_task_toml:
        policy_lines = policy_lines.replace(b"\n", b"\r\n")
    for line in policy_lines.splitlines(keepends=True):
        derived_task_toml = derived_task_toml.replace(line, b"", 1)
    assert derived_task_toml == (original / "task.toml").read_bytes()
    assert verify_study_task_snapshot(run_dir, metadata) == target.resolve()


def test_snapshot_detects_task_metadata_drift(tmp_path: Path, monkeypatch):
    original = _task_tree(tmp_path / "source")
    verifier_sha256 = _set_expected(monkeypatch, original)
    run_dir = tmp_path / "run"
    metadata = materialize_study_task_snapshot(
        run_dir=run_dir,
        source_path=original,
        task_id=original.name,
        source_revision=_REVISION,
        source_git_url=_REPOSITORY,
        original_task_sha256="a" * 64,
        original_verifier_sha256=verifier_sha256,
    )
    target = run_dir / "study-network" / "tasks" / original.name
    (target / "task.toml").write_text((target / "task.toml").read_text().replace('"no-network"', '"public"'))

    with pytest.raises(ValueError, match="snapshot.*changed|network policy"):
        verify_study_task_snapshot(run_dir, metadata)


def test_snapshot_rejects_git_provenance_drift(tmp_path: Path, monkeypatch):
    original = _task_tree(tmp_path / "source")
    verifier_sha256 = _set_expected(monkeypatch, original)
    run_dir = tmp_path / "run"
    metadata = materialize_study_task_snapshot(
        run_dir=run_dir,
        source_path=original,
        task_id=original.name,
        source_revision=_REVISION,
        source_git_url=_REPOSITORY,
        original_task_sha256="a" * 64,
        original_verifier_sha256=verifier_sha256,
    )
    metadata["source_revision"] = "0" * 40

    with pytest.raises(ValueError, match="source provenance"):
        verify_study_task_snapshot(run_dir, metadata)


def test_snapshot_rejects_preexisting_network_keys_and_symlinks(tmp_path: Path, monkeypatch):
    source = _task_tree(tmp_path / "source")
    verifier_sha256 = _set_expected(monkeypatch, source)
    (source / "task.toml").write_text(
        (source / "task.toml").read_text().replace("[agent]\n", '[agent]\nnetwork_mode = "public"\n')
    )
    with pytest.raises(ValueError, match="network policy metadata already exists"):
        materialize_study_task_snapshot(
            run_dir=tmp_path / "run",
            source_path=source,
            task_id=source.name,
            source_revision=_REVISION,
            source_git_url=_REPOSITORY,
            original_task_sha256="a" * 64,
            original_verifier_sha256=verifier_sha256,
        )


def test_snapshot_manifest_rejects_missing_or_public_agent_policy(tmp_path: Path):
    from agent_benchmark.study_network_policy import verify_study_network_manifest

    with pytest.raises(ValueError, match="no declared network policy"):
        verify_study_network_manifest({"provenance": {}}, tmp_path, _TASK_ID)
    manifest = {
        "provenance": {
            "study_network": {
                "policy_id": NETWORK_POLICY_ID,
                "network_policy": {**NETWORK_POLICY, "agent": {"network_mode": "public", "allowed_hosts": []}},
                "task_snapshots": {},
            }
        }
    }
    with pytest.raises(ValueError, match="unsupported"):
        verify_study_network_manifest(manifest, tmp_path, _TASK_ID)


def test_snapshot_rejects_content_drift_and_paths_outside_run(tmp_path: Path, monkeypatch):
    source = _task_tree(tmp_path / "source")
    verifier_sha256 = _set_expected(monkeypatch, source)
    run_dir = tmp_path / "run"
    metadata = materialize_study_task_snapshot(
        run_dir=run_dir,
        source_path=source,
        task_id=source.name,
        source_revision=_REVISION,
        source_git_url=_REPOSITORY,
        original_task_sha256="a" * 64,
        original_verifier_sha256=verifier_sha256,
    )
    target = run_dir / "study-network" / "tasks" / source.name
    (target / "instruction.md").write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="snapshot.*changed"):
        verify_study_task_snapshot(run_dir, metadata)


def test_materializer_does_not_overwrite_existing_snapshot(tmp_path: Path, monkeypatch):
    source = _task_tree(tmp_path / "source")
    verifier_sha256 = _set_expected(monkeypatch, source)
    target = tmp_path / "run" / "study-network" / "tasks" / source.name
    target.parent.mkdir(parents=True)
    target.mkdir()
    with pytest.raises(FileExistsError):
        materialize_study_task_snapshot(
            run_dir=tmp_path / "run",
            source_path=source,
            task_id=source.name,
            source_revision=_REVISION,
            source_git_url=_REPOSITORY,
            original_task_sha256="a" * 64,
            original_verifier_sha256=verifier_sha256,
        )


def test_cached_frozen_task_overlays_preserve_original_verifier_trees(tmp_path: Path):
    if not os.environ.get("HARBOR_025_PYTHON"):
        pytest.skip("set HARBOR_025_PYTHON to qualify the actual frozen Harbor task cache")
    from agent_benchmark.study_task_integrity import EXPECTED, verify_study_task_trees

    task_ids = sorted(EXPECTED)
    revision = _REVISION
    repository = _REPOSITORY
    manifest = {
        "tasks": task_ids,
        "provenance": {
            "registry_resolution": {
                "tasks": [
                    {
                        "task_id": task_id,
                        "git_url": repository,
                        "git_commit_id": revision,
                        "git_path": f"datasets/aider_polyglot/{task_id}",
                    }
                    for task_id in task_ids
                ]
            }
        },
    }
    original_rows = verify_study_task_trees(manifest)
    run_dir = tmp_path / "network-overlays"
    for row in original_rows:
        metadata = materialize_study_task_snapshot(
            run_dir=run_dir,
            source_path=Path(row["task_root"]),
            task_id=row["task_id"],
            source_revision=revision,
            source_git_url=repository,
            original_task_sha256=row["task_sha256"],
            original_verifier_sha256=row["verifier_sha256"],
        )
        snapshot = verify_study_task_snapshot(run_dir, metadata)
        assert metadata["original_task_sha256"] == EXPECTED[row["task_id"]][0]
        assert metadata["original_verifier_sha256"] == EXPECTED[row["task_id"]][1]
        assert metadata["derived_verifier_sha256"] == EXPECTED[row["task_id"]][1]
        assert _verifier_hash(snapshot) == EXPECTED[row["task_id"]][1]


def test_harbor_command_uses_derived_task_with_frozen_source_and_same_network(tmp_path: Path, monkeypatch):
    from agent_benchmark.harbor.planner import plan_benchmark
    from agent_benchmark.harbor.runner import build_harbor_command

    monkeypatch.setattr("agent_benchmark.harbor.runner.shutil.which", lambda _: "harbor")
    plan = plan_benchmark("aider/aider-polyglot", agent="opencode", task_ids=["polyglot_python_beer-song"])
    task_path = tmp_path / "polyglot_python_beer-song"
    task_path.mkdir()
    cmd = build_harbor_command(
        plan,
        jobs_dir=tmp_path / "jobs",
        study_adapter=True,
        study_task_path=task_path,
        study_source_git_url="https://github.com/laude-institute/harbor-datasets.git",
        study_source_revision="f30b14415dd733c83627204bad0af69a89ceb46f",
        study_network_policy=NETWORK_POLICY,
    )

    assert cmd[cmd.index("--path") + 1] == str(task_path.resolve())
    assert "--task-git-url" not in cmd
    assert "--task-git-commit" not in cmd
    assert "--dataset" not in cmd
    assert "--registry-path" not in cmd
    assert "--include-task-name" not in cmd


def test_harbor_command_fails_closed_for_public_agent_network(tmp_path: Path, monkeypatch):
    from agent_benchmark.harbor.planner import plan_benchmark
    from agent_benchmark.harbor.runner import build_harbor_command

    monkeypatch.setattr("agent_benchmark.harbor.runner.shutil.which", lambda _: "harbor")
    plan = plan_benchmark("aider/aider-polyglot", agent="opencode", task_ids=["polyglot_python_beer-song"])
    public = {**NETWORK_POLICY, "agent": {"network_mode": "public", "allowed_hosts": []}}
    with pytest.raises(ValueError, match="network policy"):
        build_harbor_command(
            plan,
            jobs_dir=tmp_path,
            study_adapter=True,
            study_task_path=tmp_path,
            study_source_git_url="https://example.invalid/repo.git",
            study_source_revision="rev",
            study_network_policy=public,
        )


def test_cached_harbor_run_cli_supports_local_snapshot_path_and_not_git_flags():
    import os
    import subprocess

    interpreter = os.environ.get("HARBOR_025_PYTHON")
    if not interpreter:
        pytest.skip("set HARBOR_025_PYTHON to inspect actual Harbor 0.25.0 CLI")
    result = subprocess.run(
        [interpreter, "-B", "-c", "from harbor.cli.main import app; app()", "run", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--path" in result.stdout
    assert "--task-git-url" not in result.stdout
    assert "--task-git-commit" not in result.stdout
