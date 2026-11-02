import hashlib
import json
from pathlib import Path
import pytest

from local_inference_optimization.apply import (
    RECEIPT_SCHEMA,
    apply_plan_to_target,
    rollback_transaction,
)
from local_inference_optimization.compiler import compile_plan

DIGEST = "a" * 64
SAMPLE_VARIANT = {
    "schema": "lio-variant-v1",
    "model": {
        "alias": "qwen2.5-coder-7b",
        "file_identity": {"status": "weak", "size_bytes": 4800000000, "sha256": None},
        "quantization": "q4_k_m",
    },
    "context": 4096,
    "output_limit": 1024,
    "reasoning": "off",
    "sampling": {"temperature": 0.0},
    "features": {},
    "prompt_policy": "strict-v1",
    "config_sha256": DIGEST,
}
BACKEND_INFO = {
    "identity": "lmstudio",
    "version": "0.3.0",
    "api_type": "lmstudio_rest_v1",
}


def test_apply_requires_explicit_authorization(tmp_path: Path):
    target = tmp_path / "mock_config.json"
    target.write_text('{"context": 2048}', encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()

    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)

    # Without authorized=True -> raises PermissionError
    with pytest.raises(PermissionError, match="Application not authorized"):
        apply_plan_to_target(
            plan, target, '{"context": 4096}', before_sha, authorized=False
        )

    # Confirm target was NOT mutated (dry-run safety invariant)
    assert target.read_text(encoding="utf-8") == '{"context": 2048}'


def test_safe_fixture_application_and_receipt(tmp_path: Path):
    target = tmp_path / "mock_config.json"
    target.write_text('{"context": 2048}', encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()

    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)
    receipt_dir = tmp_path / "receipts"

    receipt = apply_plan_to_target(
        plan,
        target,
        '{"context": 4096}',
        before_sha,
        authorized=True,
        receipt_dir=receipt_dir,
    )

    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["status"] == "applied"
    assert receipt["before_sha256"] == before_sha
    assert receipt["backup_content"] == '{"context": 2048}'
    assert target.read_text(encoding="utf-8") == '{"context": 4096}'

    # Check receipt file persisted
    receipt_files = list(receipt_dir.glob("receipt-*.json"))
    assert len(receipt_files) == 1
    persisted = json.loads(receipt_files[0].read_text(encoding="utf-8"))
    assert persisted["transaction_id"] == receipt["transaction_id"]


def test_idempotent_application(tmp_path: Path):
    target = tmp_path / "mock_config.json"
    target.write_text('{"context": 4096}', encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()

    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)
    receipt = apply_plan_to_target(
        plan,
        target,
        '{"context": 4096}',
        before_sha,
        authorized=True,
    )

    assert receipt["status"] == "applied"
    assert receipt["before_sha256"] == receipt["after_sha256"]
    assert target.read_text(encoding="utf-8") == '{"context": 4096}'


def test_drift_detection_aborts_apply(tmp_path: Path):
    target = tmp_path / "mock_config.json"
    target.write_text('{"context": 2048}', encoding="utf-8")

    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)

    # Supply an outdated expected_before_sha256
    wrong_sha = "0" * 64
    with pytest.raises(ValueError, match="Pre-condition mismatch"):
        apply_plan_to_target(
            plan,
            target,
            '{"context": 4096}',
            wrong_sha,
            authorized=True,
        )

    # Target unchanged
    assert target.read_text(encoding="utf-8") == '{"context": 2048}'


def test_rollback_requires_authorization(tmp_path: Path):
    target = tmp_path / "mock_config.json"
    target.write_text('{"context": 2048}', encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()

    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)
    receipt = apply_plan_to_target(
        plan,
        target,
        '{"context": 4096}',
        before_sha,
        authorized=True,
    )

    # Rollback without authorized=True -> raises PermissionError
    with pytest.raises(PermissionError, match="Rollback not authorized"):
        rollback_transaction(receipt, target, authorized=False)

    assert target.read_text(encoding="utf-8") == '{"context": 4096}'


def test_successful_rollback(tmp_path: Path):
    target = tmp_path / "mock_config.json"
    target.write_text('{"context": 2048}', encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()

    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)
    receipt = apply_plan_to_target(
        plan,
        target,
        '{"context": 4096}',
        before_sha,
        authorized=True,
    )

    assert target.read_text(encoding="utf-8") == '{"context": 4096}'

    rolled_back_receipt = rollback_transaction(receipt, target, authorized=True)
    assert rolled_back_receipt["status"] == "rolled_back"
    assert target.read_text(encoding="utf-8") == '{"context": 2048}'


def test_external_mutation_blocks_rollback(tmp_path: Path):
    target = tmp_path / "mock_config.json"
    target.write_text('{"context": 2048}', encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()

    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)
    receipt = apply_plan_to_target(
        plan,
        target,
        '{"context": 4096}',
        before_sha,
        authorized=True,
    )

    # Simulate external concurrent edit
    target.write_text('{"context": 99999, "user_custom": true}', encoding="utf-8")

    # Rollback must refuse to overwrite external user changes
    with pytest.raises(ValueError, match="rollback drift detected"):
        rollback_transaction(receipt, target, authorized=True)

    # External modification is preserved!
    assert (
        target.read_text(encoding="utf-8") == '{"context": 99999, "user_custom": true}'
    )


def test_apply_rejects_symlinks(tmp_path: Path, monkeypatch):
    target = tmp_path / "mock_config.json"
    target.write_text('{"context": 2048}', encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)

    monkeypatch.setattr(Path, "is_symlink", lambda self: True)
    with pytest.raises(ValueError, match="symlinks are forbidden"):
        apply_plan_to_target(
            plan, target, '{"context": 4096}', before_sha, authorized=True
        )


def test_apply_enforces_allowed_root(tmp_path: Path):
    target = tmp_path / "mock_config.json"
    target.write_text('{"context": 2048}', encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)

    other_dir = tmp_path / "allowed_jail"
    other_dir.mkdir()

    with pytest.raises(PermissionError, match="outside allowed root"):
        apply_plan_to_target(
            plan,
            target,
            '{"context": 4096}',
            before_sha,
            authorized=True,
            allowed_root=other_dir,
        )


def test_apply_rejects_live_production_paths(tmp_path: Path):
    fake_live = tmp_path / ".lmstudio" / "models.json"
    fake_live.parent.mkdir(parents=True)
    fake_live.write_text('{"context": 2048}', encoding="utf-8")
    before_sha = hashlib.sha256(fake_live.read_bytes()).hexdigest()
    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)

    with pytest.raises(PermissionError, match="live production/user config"):
        apply_plan_to_target(
            plan, fake_live, '{"context": 4096}', before_sha, authorized=True
        )


def test_receipt_failure_reverts_target_file(tmp_path: Path, monkeypatch):
    target = tmp_path / "mock_config.json"
    target.write_text('{"context": 2048}', encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)
    receipt_dir = tmp_path / "receipts"

    def broken_write_text(self, *args, **kwargs):
        raise OSError("Disk write error")

    monkeypatch.setattr(Path, "write_text", broken_write_text)

    with pytest.raises(RuntimeError, match="rolled back target file"):
        apply_plan_to_target(
            plan,
            target,
            '{"context": 4096}',
            before_sha,
            authorized=True,
            receipt_dir=receipt_dir,
        )

    # Target content MUST be preserved / rolled back
    assert target.read_text(encoding="utf-8") == '{"context": 2048}'


def test_repeated_rollback_from_file_rejected(tmp_path: Path):
    target = tmp_path / "mock_config.json"
    target.write_text('{"context": 2048}', encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    plan = compile_plan(SAMPLE_VARIANT, BACKEND_INFO)
    receipt_dir = tmp_path / "receipts"

    receipt = apply_plan_to_target(
        plan,
        target,
        '{"context": 4096}',
        before_sha,
        authorized=True,
        receipt_dir=receipt_dir,
    )
    receipt_file = receipt_dir / f"receipt-{receipt['transaction_id']}.json"
    assert receipt_file.exists()

    # First rollback succeeds
    res1 = rollback_transaction(receipt_file, target, authorized=True)
    assert res1["status"] == "rolled_back"
    assert target.read_text(encoding="utf-8") == '{"context": 2048}'

    # Second rollback using the same receipt file must be explicitly rejected
    with pytest.raises(
        ValueError, match="Cannot rollback receipt with status: 'rolled_back'"
    ):
        rollback_transaction(receipt_file, target, authorized=True)
