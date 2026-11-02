"""Safe, disabled-by-default offline apply and rollback engine (P06)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any
import uuid

from .compiler import validate_plan
from .contracts import (
    _id,
    _mapping,
    _sha,
    _version,
    canonical_bytes,
)

RECEIPT_SCHEMA = "lio-receipt-v1"
DISALLOWED_TARGET_PATTERNS = (".lmstudio", ".config/opencode", ".opencode")


def _check_target_safety(
    target_file: Path | str,
    allowed_root: Path | str | None = None,
) -> Path:
    raw_target = Path(target_file)
    if raw_target.is_symlink():
        raise ValueError(
            f"Target path cannot be a symlink (symlinks are forbidden): {target_file}"
        )

    target_path = raw_target.resolve()
    if not target_path.exists() or not target_path.is_file():
        raise FileNotFoundError(
            f"Target file does not exist or is not a regular file: {target_path}"
        )

    if allowed_root is not None:
        resolved_root = Path(allowed_root).resolve()
        try:
            target_path.relative_to(resolved_root)
        except ValueError as exc:
            raise PermissionError(
                f"Target file {target_path} is outside allowed root {resolved_root}"
            ) from exc

    normalized = str(target_path).replace("\\", "/").lower()
    for pattern in DISALLOWED_TARGET_PATTERNS:
        if pattern in normalized:
            raise PermissionError(
                f"Target file path refers to live production/user config and is forbidden: {target_path}"
            )

    return target_path


def validate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    _mapping(
        receipt,
        (
            "schema",
            "transaction_id",
            "plan_sha256",
            "target_path",
            "timestamp",
            "before_sha256",
            "after_sha256",
            "backup_content",
            "status",
        ),
    )
    _version(receipt["schema"], RECEIPT_SCHEMA)
    _id(receipt["transaction_id"])
    _sha(receipt["plan_sha256"])
    _sha(receipt["before_sha256"])
    _sha(receipt["after_sha256"])

    if not isinstance(receipt["target_path"], str) or not receipt["target_path"]:
        raise ValueError("invalid target_path")

    if not isinstance(receipt["backup_content"], str):
        raise ValueError("backup_content must be a string snapshot")

    status = receipt["status"]
    if status not in {"applied", "rolled_back", "failed"}:
        raise ValueError(f"invalid receipt status: {status!r}")

    # Validate ISO timestamp ending with Z
    ts = receipt["timestamp"]
    if not isinstance(ts, str) or not ts.endswith("Z"):
        raise ValueError("timestamp must be UTC ending in Z")
    try:
        datetime.fromisoformat(ts[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("invalid timestamp format") from exc

    canonical_bytes(receipt)
    return receipt


def apply_plan_to_target(
    plan: dict[str, Any],
    target_file: Path | str,
    new_content: str,
    expected_before_sha256: str,
    *,
    authorized: bool = False,
    allowed_root: Path | str | None = None,
    receipt_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Apply a compiled plan to a target file in an isolated test fixture with receipt generation.

    SAFETY: Must NEVER be pointed at live production configurations. Requires explicit authorized=True.
    """
    if not authorized:
        raise PermissionError(
            "Application not authorized: apply requires explicit authorized=True operator consent"
        )

    validate_plan(plan)
    if plan["status"] != "compiled":
        raise ValueError(
            f"Cannot apply uncompiled plan (status: {plan['status']}, blockers: {plan['blockers']})"
        )

    target_path = _check_target_safety(target_file, allowed_root=allowed_root)

    # 1. Inspect existing state and check for drift
    original_bytes = target_path.read_bytes()
    original_content = original_bytes.decode("utf-8")
    actual_before_sha256 = hashlib.sha256(original_bytes).hexdigest()
    original_mode = target_path.stat().st_mode

    if actual_before_sha256 != expected_before_sha256:
        raise ValueError(
            f"Pre-condition mismatch (drift detected): expected before SHA-256 {expected_before_sha256}, "
            f"but found actual file SHA-256 {actual_before_sha256}"
        )

    # 2. Check for idempotency (already at desired content)
    new_bytes = new_content.encode("utf-8")
    after_sha256 = hashlib.sha256(new_bytes).hexdigest()

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tx_id = f"txn-{uuid.uuid4().hex[:16]}"

    # 3. Perform atomic write via temp file in same directory
    if actual_before_sha256 != after_sha256:
        tmp_target = target_path.with_name(
            f"{target_path.name}.tmp-{uuid.uuid4().hex[:8]}"
        )
        try:
            tmp_target.write_bytes(new_bytes)
            try:
                os.chmod(tmp_target, stat.S_IMODE(original_mode))
            except OSError:
                pass
            os.replace(tmp_target, target_path)
        except Exception:
            if tmp_target.exists():
                try:
                    tmp_target.unlink()
                except OSError:
                    pass
            raise

    # 4. Generate transaction receipt
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "transaction_id": tx_id,
        "plan_sha256": plan["plan_sha256"],
        "target_path": str(target_path).replace("\\", "/"),
        "timestamp": now_utc,
        "before_sha256": actual_before_sha256,
        "after_sha256": after_sha256,
        "backup_content": original_content,
        "status": "applied",
    }
    validate_receipt(receipt)

    if receipt_dir is not None:
        r_dir = Path(receipt_dir).resolve()
        r_dir.mkdir(parents=True, exist_ok=True)
        receipt_file = r_dir / f"receipt-{tx_id}.json"
        try:
            receipt_file.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        except Exception as exc:
            # Revert target_path to original content if receipt writing fails
            if actual_before_sha256 != after_sha256:
                try:
                    target_path.write_bytes(original_bytes)
                    os.chmod(target_path, stat.S_IMODE(original_mode))
                except Exception:
                    pass
            if receipt_file.exists():
                try:
                    receipt_file.unlink()
                except OSError:
                    pass
            raise RuntimeError(
                f"Failed to persist transaction receipt; rolled back target file: {target_path}"
            ) from exc

    return receipt


def rollback_transaction(
    receipt_data: dict[str, Any] | Path | str,
    target_file: Path | str,
    *,
    authorized: bool = False,
    allowed_root: Path | str | None = None,
) -> dict[str, Any]:
    """Rollback a previously applied transaction safely without overwriting concurrent edits."""
    if not authorized:
        raise PermissionError(
            "Rollback not authorized: rollback requires explicit authorized=True operator consent"
        )

    receipt_path: Path | None = None
    if isinstance(receipt_data, (str, Path)):
        receipt_path = Path(receipt_data).resolve()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    else:
        receipt = dict(receipt_data)

    validate_receipt(receipt)
    if receipt["status"] != "applied":
        raise ValueError(f"Cannot rollback receipt with status: {receipt['status']!r}")

    target_path = _check_target_safety(target_file, allowed_root=allowed_root)

    # 1. External modification / drift detection
    current_bytes = target_path.read_bytes()
    current_sha256 = hashlib.sha256(current_bytes).hexdigest()

    if current_sha256 != receipt["after_sha256"]:
        raise ValueError(
            f"Target modified externally since transaction (rollback drift detected): "
            f"expected file SHA-256 {receipt['after_sha256']}, but found {current_sha256}; "
            f"refusing to overwrite external changes."
        )

    # 2. Atomic restoration of backup snapshot
    original_mode = target_path.stat().st_mode
    backup_bytes = receipt["backup_content"].encode("utf-8")
    tmp_target = target_path.with_name(
        f"{target_path.name}.tmp-rollback-{uuid.uuid4().hex[:8]}"
    )
    try:
        tmp_target.write_bytes(backup_bytes)
        try:
            os.chmod(tmp_target, stat.S_IMODE(original_mode))
        except OSError:
            pass
        os.replace(tmp_target, target_path)
    except Exception:
        if tmp_target.exists():
            try:
                tmp_target.unlink()
            except OSError:
                pass
        raise

    # Verify restoration matches before_sha256
    restored_sha256 = hashlib.sha256(target_path.read_bytes()).hexdigest()
    if restored_sha256 != receipt["before_sha256"]:
        raise ValueError(
            f"Rollback verification failure: restored SHA-256 {restored_sha256} does not match {receipt['before_sha256']}"
        )

    receipt["status"] = "rolled_back"
    receipt["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    validate_receipt(receipt)

    if receipt_path is not None and receipt_path.exists():
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    return receipt
