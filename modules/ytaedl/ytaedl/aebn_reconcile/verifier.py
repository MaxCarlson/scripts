"""Independent verification of existing and replacement scene outputs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

from .scanner import _within_duration, probe_video
from .store import ReconciliationStore


_SCENE_NAME = re.compile(r"(?:^|[\s._\-[(])scene[\s._-]*(\d+)(?=$|[\s._\-\])])", re.IGNORECASE)
VERIFICATION_CONTRACT = 2


def _validate_av_coverage(facts: dict, expected: float) -> dict:
    """Require bounded timestamp and duration evidence for both A/V streams."""
    errors = []
    streams = facts.get("streams") or {}
    tolerance = max(8.0, expected * 0.05)
    evidence = {"expected_duration_s": expected, "tolerance_s": tolerance, "streams": {}}
    for kind in ("video", "audio"):
        stream = streams.get(kind)
        if not stream:
            errors.append(f"{kind} stream timing evidence is unavailable")
            continue
        duration = stream.get("duration")
        timestamp_span = stream.get("timestamp_span")
        packet_count = stream.get("packet_count")
        if duration is None or abs(float(duration) - expected) > tolerance:
            errors.append(f"{kind} stream duration does not cover the expected scene interval")
        if timestamp_span is None or float(timestamp_span) < expected - tolerance:
            errors.append(f"{kind} packet timestamps do not span the expected scene interval")
        if packet_count is None or int(packet_count) <= 0:
            errors.append(f"{kind} stream has no verified packets")
        evidence["streams"][kind] = dict(stream)
    if len(evidence["streams"]) == 2:
        video_duration = evidence["streams"]["video"].get("duration")
        audio_duration = evidence["streams"]["audio"].get("duration")
        if video_duration is not None and audio_duration is not None and abs(float(video_duration) - float(audio_duration)) > tolerance:
            errors.append("audio and video coverage differs materially")
    return {"valid": not errors, "errors": errors, "evidence": evidence}


def _content_edges(path: Path, block: int = 65536) -> str:
    """Fingerprint small file edges to detect obvious accidental duplicate outputs."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        digest.update(stream.read(block))
        size = path.stat().st_size
        if size > block:
            stream.seek(max(0, size - block))
            digest.update(stream.read(block))
    return digest.hexdigest()


def verify_replacements(database_path: Path | str, *, probe_video_fn: Callable | None = None) -> dict[str, int]:
    """Verify files against AEBN scene ordinal, duration, video, and completion evidence."""
    probe = probe_video_fn or probe_video
    checked = verified = failed = skipped = 0
    with ReconciliationStore(database_path) as store:
        scenes = store.list_scenes()
        for scene in scenes:
            if scene["ordinal"] is None or scene["metadata_status"] != "resolved":
                detail = "scene identity or timing metadata is not resolved under the current verification contract"
                store.execute("UPDATE requested_scenes SET status='scene_invalid',status_detail=? WHERE movie_key=? AND scene_id=?",
                              (detail, scene["movie_key"], scene["scene_id"]))
                store.execute("UPDATE download_jobs SET verification_status='failed',verification_json=? WHERE movie_key=? AND scene_id=?",
                              (json.dumps({"verification_contract": VERIFICATION_CONTRACT, "error": detail}),
                               scene["movie_key"], scene["scene_id"]))
                skipped += 1
                continue
            job = store.execute("SELECT * FROM download_jobs WHERE movie_key=? AND scene_id=?",
                                (scene["movie_key"], scene["scene_id"])).fetchone()
            path_value = job["output_path"] if job and job["status"] == "downloaded" else None
            if not path_value:
                candidate = store.execute(
                    """SELECT c.path FROM media_candidates c JOIN candidate_scenes cs USING(candidate_id)
                       WHERE cs.movie_key=? AND cs.scene_id=? AND c.classification='scene'
                       ORDER BY c.confidence DESC,c.path LIMIT 1""",
                    (scene["movie_key"], scene["scene_id"]),
                ).fetchone()
                path_value = candidate["path"] if candidate else None
            if not path_value:
                missing_status = "scene_invalid" if job and job["status"] == "downloaded" else "scene_missing"
                missing_detail = "downloaded output is missing from disk" if missing_status == "scene_invalid" else "no scene output found"
                store.execute("UPDATE requested_scenes SET status=?,status_detail=? WHERE movie_key=? AND scene_id=?",
                              (missing_status, missing_detail, scene["movie_key"], scene["scene_id"]))
                if job and job["status"] == "downloaded":
                    store.execute("UPDATE download_jobs SET verification_status='failed',verification_json=? WHERE job_id=?",
                                  (json.dumps({"error": missing_detail}), job["job_id"]))
                skipped += 1
                continue
            checked += 1
            path = Path(path_value)
            evidence: dict = {"verification_contract": VERIFICATION_CONTRACT,
                              "path": str(path), "scene_id": scene["scene_id"], "ordinal": scene["ordinal"],
                              "downloader_completed": bool(job and job["status"] == "downloaded" and job["exit_code"] == 0)}
            error = None
            try:
                stat = path.stat()
                if not path.is_file() or path.is_symlink():
                    raise ValueError("output is not a regular file")
                if path.suffix.lower() not in {".mp4", ".mkv", ".m4v", ".mov", ".avi", ".webm"} or path.name.lower().endswith((".part", ".temp")):
                    raise ValueError("output has an unsupported or incomplete media extension")
                if job and job["status"] == "downloaded" and not evidence["downloader_completed"]:
                    raise ValueError("download did not report successful completion")
                labeled = _SCENE_NAME.search(path.stem)
                if not labeled or int(labeled.group(1)) != int(scene["ordinal"]):
                    raise ValueError("output filename does not identify the expected scene ordinal")
                full_movie = store.execute("SELECT 1 FROM media_candidates WHERE movie_key=? AND path=? AND classification='full_movie'",
                                           (scene["movie_key"], str(path))).fetchone()
                if full_movie:
                    raise ValueError("output path is also classified as an original full movie")
                facts = probe(path)
                if not facts:
                    raise ValueError("ffprobe is unavailable or could not parse the output")
                if not facts.get("video"):
                    raise ValueError("output contains no video stream")
                expected = None
                if scene["start_seconds"] is not None and scene["end_seconds"] is not None:
                    expected = scene["end_seconds"] - scene["start_seconds"]
                if expected is None:
                    raise ValueError("AEBN scene timing metadata is unavailable")
                duration = float(facts.get("duration"))
                if not _within_duration(duration, expected):
                    raise ValueError(f"duration {duration:.1f}s is implausible for expected scene duration {expected:.1f}s")
                coverage = _validate_av_coverage(facts, expected)
                evidence["av_coverage"] = coverage["evidence"]
                if not coverage["valid"]:
                    raise ValueError("audio/video stream coverage failed: " + "; ".join(coverage["errors"]))
                evidence.update({"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                                 "duration_seconds": duration, "expected_duration_seconds": expected,
                                 "has_video": True, "verification_contract": VERIFICATION_CONTRACT})
                other = store.execute(
                    """SELECT c.path FROM media_candidates c JOIN candidate_scenes cs USING(candidate_id)
                       WHERE cs.movie_key=? AND cs.scene_id!=? AND c.path!=?""",
                    (scene["movie_key"], scene["scene_id"], str(path)),
                ).fetchall()
                edge_hash = None
                for other_row in other:
                    other_path = Path(other_row["path"])
                    try:
                        if other_path.stat().st_size == stat.st_size:
                            if edge_hash is None:
                                edge_hash = _content_edges(path)
                            if _content_edges(other_path) == edge_hash:
                                raise ValueError(f"output is byte-edge-identical to a different scene candidate: {other_path}")
                    except FileNotFoundError:
                        continue
                evidence["edge_fingerprint"] = edge_hash
            except (OSError, ValueError, TypeError) as exc:
                error = str(exc)
            status = "scene_verified" if error is None else "scene_invalid"
            store.execute("UPDATE requested_scenes SET status=?,status_detail=? WHERE movie_key=? AND scene_id=?",
                          (status, error, scene["movie_key"], scene["scene_id"]))
            if job:
                store.execute("UPDATE download_jobs SET verification_status=?,verification_json=? WHERE job_id=?",
                              ("passed" if error is None else "failed", json.dumps(evidence, ensure_ascii=False), job["job_id"]))
            store.record_event("verification_passed" if error is None else "verification_failed",
                               movie_key=scene["movie_key"], scene_id=scene["scene_id"],
                               details={**evidence, "error": error})
            if error is None:
                verified += 1
            else:
                failed += 1
    return {"checked": checked, "verified": verified, "failed": failed, "skipped": skipped}
