"""Grouped review and approval binding for original full-movie candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .store import ReconciliationStore


def approval_fingerprint(store: ReconciliationStore, candidate_id: int) -> str:
    row = store.execute("SELECT * FROM media_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
    if not row:
        raise ValueError(f"Unknown media candidate {candidate_id}")
    path = Path(row["path"])
    stat = path.stat()
    if path.is_symlink() or not path.is_file():
        raise ValueError("original candidate is not a regular file")
    scenes = []
    for scene in store.execute(
        """SELECT s.movie_key,s.scene_id,s.ordinal,s.status,s.start_seconds,s.end_seconds,
                  j.output_path,j.verification_status,j.verification_json
           FROM candidate_scenes cs JOIN requested_scenes s USING(movie_key,scene_id)
           LEFT JOIN download_jobs j USING(movie_key,scene_id)
           WHERE cs.candidate_id=? ORDER BY s.scene_id""", (candidate_id,)
    ):
        output = scene["output_path"]
        output_stat = None
        if output:
            try:
                output_path = Path(output)
                current = output_path.stat()
                output_stat = {"path": str(output_path.resolve()), "size": current.st_size,
                               "mtime_ns": current.st_mtime_ns, "file_id": str(current.st_ino)}
            except OSError:
                output_stat = {"path": output, "missing": True}
        scenes.append({"movie_key": scene["movie_key"], "scene_id": scene["scene_id"],
                       "ordinal": scene["ordinal"], "status": scene["status"],
                       "start": scene["start_seconds"], "end": scene["end_seconds"],
                       "verification": scene["verification_status"],
                       "verification_evidence": json.loads(scene["verification_json"] or "{}"),
                       "output": output_stat})
    payload = {
        "path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        "device_id": str(stat.st_dev), "file_id": str(stat.st_ino),
        "classification": row["classification"], "identity_confirmed": bool(row["identity_confirmed"]),
        "root_path": row["root_path"], "confidence": row["confidence"],
        "match_evidence": row["match_evidence"],
        "scenes": scenes,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def decide_candidate(store: ReconciliationStore, candidate_id: int, decision: str, *, confirm_identity: bool = False) -> dict:
    if decision not in {"approve", "decline", "defer"}:
        raise ValueError("decision must be approve, decline, or defer")
    with store.transaction():
        row = store.execute("SELECT * FROM media_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        if not row:
            raise ValueError(f"Unknown media candidate {candidate_id}")
        if decision == "approve":
            same_path_movies = store.execute("SELECT COUNT(DISTINCT movie_key) FROM media_candidates WHERE path=?",
                                             (row["path"],)).fetchone()[0]
            if same_path_movies > 1:
                raise ValueError("the same physical path matches multiple AEBN movie IDs; disambiguate before approval")
            resulting_classification = "full_movie" if confirm_identity else row["classification"]
            if resulting_classification != "full_movie":
                raise ValueError("confirm the exact original identity before approving this candidate")
            fresh = store.execute(
                """SELECT COUNT(*) AS required,
                          SUM(CASE WHEN s.status='scene_verified' THEN 1 ELSE 0 END) AS verified
                   FROM candidate_scenes cs JOIN requested_scenes s USING(movie_key,scene_id)
                   WHERE cs.candidate_id=?""", (candidate_id,)
            ).fetchone()
            if not row["identity_confirmed"] and not confirm_identity:
                raise ValueError("confirm the original file identity before approving it")
            if not fresh["required"] or fresh["verified"] != fresh["required"]:
                raise ValueError("all requested replacement scenes linked to this original must be verified first")
            replacements = store.execute(
                """SELECT s.movie_key,s.scene_id,j.output_path,j.verification_status,j.verification_json
                   FROM candidate_scenes cs JOIN requested_scenes s USING(movie_key,scene_id)
                   LEFT JOIN download_jobs j USING(movie_key,scene_id) WHERE cs.candidate_id=?""", (candidate_id,)
            ).fetchall()
            for replacement in replacements:
                if replacement["verification_status"] != "passed":
                    raise ValueError(f"replacement verification has not passed for scene {replacement['scene_id']}")
                output_value = replacement["output_path"]
                if not output_value:
                    output_value = store.execute(
                        """SELECT c.path FROM media_candidates c JOIN candidate_scenes cs USING(candidate_id)
                           WHERE cs.movie_key=? AND cs.scene_id=? AND c.classification='scene' ORDER BY c.path LIMIT 1""",
                        (replacement["movie_key"], replacement["scene_id"]),
                    ).fetchone()
                    output_value = output_value["path"] if output_value else None
                if not output_value:
                    raise ValueError(f"replacement output is missing for scene {replacement['scene_id']}")
                output_path = Path(output_value)
                try:
                    output_stat = output_path.stat()
                except OSError as exc:
                    raise ValueError(f"replacement output is unavailable for scene {replacement['scene_id']}: {exc}") from exc
                if output_path.is_symlink() or not output_path.is_file() or output_path.resolve() == Path(row["path"]).resolve():
                    raise ValueError(f"replacement output is not a separate regular file for scene {replacement['scene_id']}")
                verification = json.loads(replacement["verification_json"] or "{}")
                coverage = verification.get("av_coverage", {}).get("streams", {})
                if (verification.get("verification_contract") != 2
                        or not {"video", "audio"}.issubset(coverage)):
                    raise ValueError(f"replacement scene {replacement['scene_id']} lacks current audio/video verification evidence")
                if verification.get("size_bytes") is not None:
                    if (verification["size_bytes"] != output_stat.st_size
                            or verification.get("mtime_ns") != output_stat.st_mtime_ns):
                        raise ValueError(f"replacement file changed after verification for scene {replacement['scene_id']}")
                else:
                    scanned = store.execute(
                        """SELECT size_bytes,mtime_ns FROM media_candidates WHERE path=? AND classification='scene'""",
                        (str(output_path.resolve()),),
                    ).fetchone()
                    if not scanned or scanned["size_bytes"] != output_stat.st_size or scanned["mtime_ns"] != output_stat.st_mtime_ns:
                        raise ValueError(f"replacement evidence is unavailable or stale for scene {replacement['scene_id']}")
            if confirm_identity:
                store.execute("UPDATE media_candidates SET identity_confirmed=1,classification='full_movie' WHERE candidate_id=?",
                              (candidate_id,))
            fingerprint = approval_fingerprint(store, candidate_id)
            approved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            store.execute("UPDATE media_candidates SET approval='approved',approval_fingerprint=?,approved_at=? WHERE candidate_id=?",
                          (fingerprint, approved_at, candidate_id))
        elif decision == "decline":
            fingerprint, approved_at = None, None
            store.execute("UPDATE media_candidates SET approval='declined',approval_fingerprint=NULL,approved_at=NULL WHERE candidate_id=?",
                          (candidate_id,))
        else:
            fingerprint, approved_at = None, None
            store.execute("UPDATE media_candidates SET approval='undecided',approval_fingerprint=NULL,approved_at=NULL WHERE candidate_id=?",
                          (candidate_id,))
        store.record_event("approval_changed", movie_key=row["movie_key"], candidate_id=candidate_id,
                           details={"decision": decision,
                                    "identity_confirmed": bool(confirm_identity or row["identity_confirmed"]),
                                    "approval_fingerprint": fingerprint})
    return {"candidate_id": candidate_id, "decision": decision, "approval_fingerprint": fingerprint,
            "approved_at": approved_at}


def review_candidates(database_path: Path | str, *, decisions: dict[str, str] | None = None,
                      confirm_identity: bool = False, interactive: bool = False,
                      input_fn: Callable[[str], str] = input, output_fn: Callable[[str], None] = print) -> list[dict]:
    """Review each persisted original independently; undecided remains the safe default."""
    results = []
    with ReconciliationStore(database_path) as store:
        candidates = store.list_candidates()
        for candidate in candidates:
            if candidate["classification"] not in {"full_movie", "unknown"}:
                continue
            linked = store.execute(
                """SELECT s.scene_id,s.ordinal,s.status,j.output_path,j.verification_status
                   FROM candidate_scenes cs JOIN requested_scenes s USING(movie_key,scene_id)
                   LEFT JOIN download_jobs j USING(movie_key,scene_id)
                   WHERE cs.candidate_id=? ORDER BY s.ordinal""", (candidate["candidate_id"],)
            ).fetchall()
            output_fn(f"Movie: {candidate['title']} ({candidate['movie_id']})")
            output_fn(f"Original: {candidate['path']} ({candidate['size_bytes']} bytes)")
            output_fn(f"Match: {candidate['classification']} / {candidate['confidence']} confidence; "
                      f"identity confirmed={bool(candidate['identity_confirmed'])}")
            for scene in linked:
                size = "unknown"
                if scene["output_path"]:
                    try:
                        size = str(Path(scene["output_path"]).stat().st_size)
                    except OSError:
                        size = "missing"
                output_fn(f"  [{'PASS' if scene['status'] == 'scene_verified' else 'WAIT'}] Scene {scene['ordinal']} "
                          f"ID {scene['scene_id']} | {scene['status']} | {size} bytes")
            output_fn("Warning: only requested scenes are replacements; this original may contain unrequested scenes.")
            decision = (decisions or {}).get(candidate["path"])
            identified = confirm_identity
            if interactive and decision is None:
                if candidate["classification"] != "full_movie" or not candidate["identity_confirmed"]:
                    answer = input_fn("Confirm this exact file is the original full movie? [y/N] ").strip().lower()
                    identified = answer == "y"
                answer = input_fn("Decision: [a]pprove removal, [d]ecline, [k]eep/defer: ").strip().lower()
                decision = {"a": "approve", "d": "decline", "k": "defer"}.get(answer, "defer")
            if decision is None:
                results.append({"candidate_id": candidate["candidate_id"], "path": candidate["path"],
                                "decision": candidate["approval"], "eligible": bool(candidate["eligible"])})
                continue
            result = decide_candidate(store, candidate["candidate_id"], decision,
                                      confirm_identity=identified if decision == "approve" else False)
            result["path"] = candidate["path"]
            results.append(result)
    return results
