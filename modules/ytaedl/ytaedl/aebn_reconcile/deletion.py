"""Explicitly approved, revalidated quarantine or permanent removal."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .review import approval_fingerprint
from .store import ReconciliationStore
from .verifier import verify_replacements


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_in_use(path: Path) -> bool | None:
    """Return true/false when the platform can inspect open handles, else unknown."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.restype = wintypes.HANDLE
        handle = create_file(str(path), 0x80000000, 0, None, 3, 0x80, None)
        invalid = wintypes.HANDLE(-1).value
        if handle == invalid:
            return True
        ctypes.windll.kernel32.CloseHandle(handle)
        return False
    try:
        import psutil
    except ImportError:
        return None
    wanted = str(path.resolve())
    try:
        for process in psutil.process_iter(["open_files"]):
            try:
                if any(item.path == wanted for item in (process.info.get("open_files") or [])):
                    return True
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                return None
        return False
    except Exception:
        return None


def _recover_delete_intents(store: ReconciliationStore) -> int:
    recovered = 0
    rows = store.execute("SELECT * FROM media_candidates WHERE deletion_state='intent'").fetchall()
    for row in rows:
        original = Path(row["path"])
        destination = Path(row["final_path"]) if row["final_path"] else None
        if destination and destination.exists() and not original.exists():
            state, detail = "quarantined", "recovered completed quarantine after interrupted database update"
        elif original.exists():
            state, detail = "interrupted_present", "original is still present after interrupted removal; rerun review"
        else:
            state, detail = "indeterminate", "original and recorded destination are both absent; manual investigation required"
        with store.transaction():
            store.execute("UPDATE media_candidates SET deletion_state=?,error=?,approval=CASE WHEN ? IN ('interrupted_present','indeterminate') THEN 'undecided' ELSE approval END,approval_fingerprint=CASE WHEN ? IN ('interrupted_present','indeterminate') THEN NULL ELSE approval_fingerprint END,approved_at=CASE WHEN ? IN ('interrupted_present','indeterminate') THEN NULL ELSE approved_at END WHERE candidate_id=?",
                          (state, detail, state, state, state, row["candidate_id"]))
            store.record_event("deletion_recovered", movie_key=row["movie_key"], candidate_id=row["candidate_id"],
                               details={"state": state, "detail": detail, "original": str(original),
                                        "destination": str(destination) if destination else None})
        recovered += 1
    return recovered


def delete_approved(database_path: Path | str, *, apply: bool = False, confirm: str | None = None,
                    permanent: bool = False, confirm_permanent: str | None = None,
                    in_use_check: Callable[[Path], bool | None] = _file_in_use,
                    probe_video_fn: Callable | None = None) -> dict:
    """Preview or execute only currently eligible, fingerprint-matched approvals."""
    if permanent and not apply:
        raise ValueError("--permanent is meaningful only with --apply")
    if permanent and not confirm_permanent:
        raise ValueError("permanent deletion requires the separate --confirm-permanent phrase")
    verify_replacements(database_path, probe_video_fn=probe_video_fn)
    with ReconciliationStore(database_path) as store:
        recovered = _recover_delete_intents(store)
        candidates = store.list_candidates()
        plans: list[dict] = []
        skipped: list[dict] = []
        for candidate in candidates:
            if candidate["approval"] != "approved":
                continue
            path = Path(candidate["path"])
            reasons = []
            try:
                stat = path.lstat()
                if path.is_symlink() or not path.is_file():
                    reasons.append("original is not a regular file")
                root = Path(candidate["root_path"]).resolve()
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root):
                    reasons.append("original is outside the configured root")
                if stat.st_size != candidate["size_bytes"] or stat.st_mtime_ns != candidate["mtime_ns"]:
                    reasons.append("original size or modification time changed since scan")
                if str(stat.st_dev) != str(candidate["device_id"]) or str(stat.st_ino) != str(candidate["file_id"]):
                    reasons.append("original filesystem identity changed since scan")
            except OSError as exc:
                reasons.append(f"original cannot be checked: {exc}")
            if not candidate["eligible"]:
                reasons.append(f"replacement eligibility failed ({candidate['verified_scene_count']}/"
                               f"{candidate['required_scene_count']} requested scenes verified, identity confirmed="
                               f"{bool(candidate['identity_confirmed'])})")
            try:
                current_fingerprint = approval_fingerprint(store, candidate["candidate_id"])
                if current_fingerprint != candidate["approval_fingerprint"]:
                    reasons.append("approval fingerprint is stale; review the original again")
            except (OSError, ValueError) as exc:
                reasons.append(f"approval evidence is unavailable: {exc}")
            in_use = in_use_check(path) if not reasons else False
            if in_use is True:
                reasons.append("original is open by another process")
            elif in_use is None:
                reasons.append("cannot determine whether the original is in use")
            if reasons:
                skipped.append({"path": str(path), "reasons": reasons})
                continue
            plans.append({"candidate_id": candidate["candidate_id"], "path": str(path),
                          "size_bytes": candidate["size_bytes"], "root_path": candidate["root_path"],
                          "verified_scene_count": candidate["verified_scene_count"]})
        total_bytes = sum(item["size_bytes"] for item in plans)
        if not apply:
            return {"planned": plans, "skipped": skipped, "total_bytes": total_bytes, "recovered": recovered,
                    "mode": "permanent" if permanent else "quarantine"}
        expected = f"DELETE {len(plans)}"
        if not plans:
            return {"planned": [], "skipped": skipped, "removed": [], "total_bytes": 0, "recovered": recovered}
        if confirm != expected:
            raise ValueError(f"apply confirmation must be exactly {expected!r}")
        if permanent and confirm_permanent != f"PERMANENTLY DELETE {len(plans)}":
            raise ValueError(f"permanent confirmation must be exactly 'PERMANENTLY DELETE {len(plans)}'")
        removed = []
        for item in plans:
            original = Path(item["path"])
            current = store.execute("SELECT * FROM media_candidates WHERE candidate_id=?", (item["candidate_id"],)).fetchone()
            try:
                current_stat = original.lstat()
                is_current = (not original.is_symlink() and original.is_file()
                              and current_stat.st_size == current["size_bytes"]
                              and current_stat.st_mtime_ns == current["mtime_ns"]
                              and str(current_stat.st_dev) == str(current["device_id"])
                              and str(current_stat.st_ino) == str(current["file_id"])
                              and approval_fingerprint(store, item["candidate_id"]) == current["approval_fingerprint"]
                              and in_use_check(original) is False)
            except (OSError, ValueError):
                is_current = False
            if not is_current:
                skipped.append({"path": str(original), "reasons": ["approval or filesystem evidence changed before removal"]})
                continue
            if permanent:
                destination = None
            else:
                quarantine = Path(item["root_path"]) / ".ytaedl-reconcile-quarantine"
                try:
                    quarantine.mkdir(parents=True, exist_ok=True)
                    is_junction = getattr(quarantine, "is_junction", None)
                    if quarantine.is_symlink() or bool(is_junction and is_junction()):
                        raise ValueError("quarantine directory is a symlink or junction")
                    quarantine.resolve(strict=True).relative_to(Path(item["root_path"]).resolve(strict=True))
                    destination = quarantine / f"{item['candidate_id']}-{original.name}"
                    if destination.exists():
                        destination = quarantine / f"{item['candidate_id']}-{uuid.uuid4().hex}-{original.name}"
                except (OSError, ValueError) as exc:
                    skipped.append({"path": str(original), "reasons": [f"safe quarantine destination unavailable: {exc}"]})
                    continue
            with store.transaction():
                store.execute("UPDATE media_candidates SET deletion_state='intent',final_path=?,error=NULL WHERE candidate_id=?",
                              (str(destination) if destination else None, item["candidate_id"]))
                store.record_event("deletion_intent", candidate_id=item["candidate_id"],
                                   details={"original": str(original), "destination": str(destination) if destination else None,
                                            "mode": "permanent" if permanent else "quarantine"})
            try:
                if destination:
                    original.replace(destination)
                    state = "quarantined"
                else:
                    original.unlink()
                    state = "permanently_deleted"
                with store.transaction():
                    store.execute("UPDATE media_candidates SET deletion_state=?,final_path=?,error=NULL WHERE candidate_id=?",
                                  (state, str(destination) if destination else None, item["candidate_id"]))
                    store.record_event("deletion_completed", candidate_id=item["candidate_id"],
                                       details={"original": str(original), "destination": str(destination) if destination else None,
                                                "mode": "permanent" if permanent else "quarantine"})
                removed.append({**item, "state": state, "destination": str(destination) if destination else None})
            except OSError as exc:
                with store.transaction():
                    store.execute("UPDATE media_candidates SET deletion_state='failed',error=? WHERE candidate_id=?",
                                  (str(exc), item["candidate_id"]))
                    store.record_event("deletion_failed", candidate_id=item["candidate_id"], details={"error": str(exc)})
                skipped.append({"path": str(original), "reasons": [f"removal failed: {exc}"]})
        return {"planned": plans, "skipped": skipped, "removed": removed, "total_bytes": total_bytes,
                "recovered": recovered, "mode": "permanent" if permanent else "quarantine"}
