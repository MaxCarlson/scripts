"""Tests for external resource specifications, store management, and setup CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_benchmark.cli import main
from agent_benchmark.external_sources import (
    InstallReceipt,
    ResourceSpec,
    SourceManager,
    ensure_store_layout,
    load_sources_lock,
    record_receipt,
)


def test_resource_spec_safety() -> None:
    """ResourceSpec must reject path traversal and invalid characters."""
    with pytest.raises(ValueError, match="Invalid or unsafe path character"):
        ResourceSpec(benchmark_id="../escaped", resource_type="git", name="evil")

    with pytest.raises(ValueError, match="Invalid or unsafe path character"):
        ResourceSpec(benchmark_id="ifeval", resource_type="git", name="evil/name")

    with pytest.raises(ValueError, match="Invalid or unsafe path character"):
        ResourceSpec(benchmark_id="ifeval", resource_type="git", name="fine", revision="rev/../../bad")

    with pytest.raises(ValueError, match="Invalid or unsafe path character"):
        ResourceSpec(benchmark_id="ifeval", resource_type="git", name="fine", paths=("../secret",))

    # Valid spec produces deterministic digest
    valid = ResourceSpec(
        benchmark_id="ifeval",
        resource_type="git_sparse",
        name="google-research",
        url="https://github.com/google-research/google-research.git",
        revision="9c1ab75d9e504c27a29e479636d36e864ee055ae",
        paths=("instruction_following_eval",),
    )
    assert len(valid.digest()) == 16
    assert valid.to_dict()["benchmark_id"] == "ifeval"


def test_store_layout_creation(tmp_path: Path) -> None:
    """Store layout must create standard isolated directories outside repository."""
    layout = ensure_store_layout(tmp_path)
    assert layout["sources"].is_dir()
    assert layout["envs"].is_dir()
    assert layout["datasets"].is_dir()
    assert layout["locks"].is_dir()
    assert layout["staging"].is_dir()


def test_plan_resource_read_only(tmp_path: Path) -> None:
    """Planning a resource must be completely read-only and create no target files."""
    mgr = SourceManager(tmp_path)
    spec = ResourceSpec(
        benchmark_id="mock_bench",
        resource_type="git",
        name="mock_src",
        revision="abc1234",
    )
    plan = mgr.plan_resource(spec)
    assert plan["benchmark_id"] == "mock_bench"
    assert plan["installed"] is False
    assert plan["action"] == "install"
    assert not Path(plan["target_location"]).exists()


def test_install_requires_explicit_authorization(tmp_path: Path) -> None:
    """Installation without execute=True must raise PermissionError."""
    mgr = SourceManager(tmp_path)
    spec = ResourceSpec(
        benchmark_id="mock_bench",
        resource_type="git",
        name="mock_src",
        revision="abc1234",
    )
    with pytest.raises(PermissionError, match="-x/--execute"):
        mgr.install_resource(spec, execute=False)


def test_atomic_install_and_verification(tmp_path: Path) -> None:
    """Atomic install with mock fixtures records receipts and verifies hashes."""
    # Setup mock source directory with files
    mock_src = tmp_path / "mock_upstream"
    mock_src.mkdir()
    (mock_src / "code.py").write_text("print('hello')", encoding="utf-8")
    sub = mock_src / "sub"
    sub.mkdir()
    (sub / "data.json").write_text('{"val": 42}', encoding="utf-8")

    mgr = SourceManager(tmp_path / "external_store")
    spec = ResourceSpec(
        benchmark_id="mock_bench",
        resource_type="git",
        name="mock_src",
        revision="1234567890ab",
    )

    receipt = mgr.install_resource(spec, execute=True, mock_source_dir=mock_src)
    assert receipt.status == "installed"
    assert receipt.revision == "1234567890ab"
    assert "code.py" in receipt.file_hashes
    assert "sub/data.json" in receipt.file_hashes

    # Verification should pass
    ver = mgr.verify_resource(spec)
    assert ver["status"] == "verified"
    assert ver["files_checked"] == 2

    # Plan should now reflect installed state
    plan = mgr.plan_resource(spec)
    assert plan["installed"] is True
    assert plan["action"] == "skip"


def test_corruption_discovery(tmp_path: Path) -> None:
    """Mutating or deleting installed files must be detected by verify."""
    mock_src = tmp_path / "mock_upstream"
    mock_src.mkdir()
    (mock_src / "eval.py").write_text("score = 1.0", encoding="utf-8")

    mgr = SourceManager(tmp_path / "external_store")
    spec = ResourceSpec(
        benchmark_id="mock_bench",
        resource_type="git",
        name="mock_eval",
        revision="abcdef123456",
    )
    receipt = mgr.install_resource(spec, execute=True, mock_source_dir=mock_src)
    installed_p = Path(receipt.install_path)

    # Mutate the file
    (installed_p / "eval.py").write_text("score = 0.0", encoding="utf-8")
    ver = mgr.verify_resource(spec)
    assert ver["status"] == "corrupted"
    assert any("mismatch: eval.py" in c for c in ver["corrupted_files"])


def test_lock_file_persistence(tmp_path: Path) -> None:
    """Lock file must persist receipts atomically across reload."""
    lock_file = tmp_path / "locks" / "installed-sources.json"
    receipt = InstallReceipt(
        benchmark_id="ifeval",
        resource_name="src",
        resource_type="git_sparse",
        install_path=str(tmp_path / "installed"),
        revision="rev1",
        spec_digest="digest1",
        installed_at="2026-11-11T00:00:00Z",
        platform="windows-x86_64",
        status="installed",
    )
    record_receipt(lock_file, receipt)

    lock = load_sources_lock(lock_file)
    rec = lock.get_receipt("ifeval", "src")
    assert rec is not None
    assert rec.benchmark_id == "ifeval"
    assert rec.revision == "rev1"


def test_cli_setup_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI setup commands must support -A, plan, preview, and JSON output."""
    res_root = str(tmp_path / "cli_store")

    # 1. setup -A (read-only plan all)
    rc = main(["setup", "-A", "-f", "json", "--resource-root", res_root])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "plan"
    assert out["scope"] == "all"
    assert len(out["resources"]) > 0

    # 2. setup plan -A (identical to setup -A)
    rc = main(["setup", "plan", "-A", "-f", "json", "--resource-root", res_root])
    assert rc == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["mode"] == "plan"

    # 3. setup install -A preview (without -x)
    rc = main(["setup", "install", "-A", "-f", "json", "--resource-root", res_root])
    assert rc == 0
    out3 = json.loads(capsys.readouterr().out)
    assert out3["mode"] == "install_preview"
    assert out3["authorized"] is False

    # 4. setup status -A
    rc = main(["setup", "status", "-A", "-f", "json", "--resource-root", res_root])
    assert rc == 0
    out4 = json.loads(capsys.readouterr().out)
    assert out4["mode"] == "status"

    # 5. setup verify -A
    rc = main(["setup", "verify", "-A", "-f", "json", "--resource-root", res_root])
    assert rc == 1
    out5 = json.loads(capsys.readouterr().out)
    assert out5["mode"] == "verify"

    # 6. Mutual exclusivity of -d and -A
    rc = main(["setup", "-A", "-d", "ifeval"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "cannot specify both --all (-A) and a specific target (-d)" in err
