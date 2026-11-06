"""Read-only URL, AEBN metadata, and configured-root inventory scan."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from .models import InputError, ParsedInputs, ScanResult, SceneRequest
from .store import ReconciliationStore


MEDIA_EXTENSIONS = {".mp4", ".mkv", ".m4v", ".mov", ".avi", ".webm"}
_SCENE_LABEL = re.compile(r"(?:^|[\s._\-\[(])scene[\s._-]*(\d+)(?=$|[\s._\-\])])", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z0-9]+")


def _parse_aebn_scene_url(url: str) -> SceneRequest:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("expected an HTTP(S) AEBN movie URL")
    host = parsed.hostname.lower()
    if host != "aebn.com" and not host.endswith(".aebn.com"):
        raise ValueError("expected an AEBN movie URL")
    parts = parsed.path.strip("/").split("/")
    if (len(parts) < 4 or not re.fullmatch(r"[A-Za-z0-9-]+", parts[0]) or parts[1].lower() != "movies"
            or not parts[2].isdigit() or not parts[3]):
        raise ValueError("expected a /<content-type>/movies/<movie-id>/<slug> URL")
    match = re.fullmatch(r"scene-(\d+)", parsed.fragment)
    if not match:
        raise ValueError("expected an explicit #scene-<digits> fragment")
    movie_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    return SceneRequest(
        site=host,
        content_type=parts[0],
        movie_id=parts[2],
        movie_url=movie_url,
        scene_id=match.group(1),
        original_url=url,
    )


def parse_scene_inputs(files: list[Path | str]) -> ParsedInputs:
    """Read scene URL files, retaining every source line and reporting errors individually."""
    requests: dict[tuple[str, str], SceneRequest] = {}
    errors: list[InputError] = []
    for raw_path in files:
        path = Path(raw_path).expanduser().resolve()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            errors.append(InputError(str(path), 0, "", f"cannot read URL file: {exc}"))
            continue
        for line_number, raw in enumerate(lines, 1):
            value = raw.strip()
            if not value or value.startswith((";", "]")) or (value.startswith("#") and not value.lower().startswith("#scene-")):
                continue
            value = value.split("  #", 1)[0].split("  ;", 1)[0].strip()
            if not value:
                continue
            try:
                request = _parse_aebn_scene_url(value)
            except ValueError as exc:
                errors.append(InputError(str(path), line_number, value, str(exc)))
                continue
            key = (request.movie_key, request.scene_id)
            if key not in requests:
                requests[key] = request
            requests[key].sources.append((str(path), line_number))
    return ParsedInputs(list(requests.values()), errors)


def probe_video(path: Path) -> dict | None:
    """Return container and independent stream coverage facts using bounded probes."""
    executable = shutil.which("ffprobe")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "-v", "error", "-count_packets", "-show_entries",
             "format=duration:stream=codec_type,duration,start_time,nb_read_packets,time_base",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=45, check=True,
        )
        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration"))
        stream_facts = {}
        for kind, selector in (("video", "v:0"), ("audio", "a:0")):
            stream = next((item for item in data.get("streams", []) if item.get("codec_type") == kind), None)
            if not stream:
                continue
            sample_count = 128 if kind == "audio" else 16
            head = subprocess.run(
                [executable, "-v", "error", "-select_streams", selector, "-read_intervals", f"%+#{sample_count}",
                 "-show_packets", "-show_entries", "packet=pts_time,dts_time", "-of", "json", str(path)],
                capture_output=True, text=True, timeout=30, check=True,
            )
            stream_duration = float(stream.get("duration")) if stream.get("duration") is not None else None
            stream_start = float(stream.get("start_time", 0) or 0)
            if stream_duration is None:
                return None
            tail_start = max(0.0, stream_start + stream_duration - 1.0)
            tail = subprocess.run(
                [executable, "-v", "error", "-select_streams", selector,
                 "-read_intervals", f"{tail_start}%+#{sample_count}", "-show_packets", "-show_entries", "packet=pts_time,dts_time",
                 "-of", "json", str(path)],
                capture_output=True, text=True, timeout=30, check=True,
            )
            head_stamps = [float(packet.get("pts_time", packet.get("dts_time")))
                           for packet in json.loads(head.stdout).get("packets", [])
                           if packet.get("pts_time", packet.get("dts_time")) is not None]
            tail_stamps = [float(packet.get("pts_time", packet.get("dts_time")))
                           for packet in json.loads(tail.stdout).get("packets", [])
                           if packet.get("pts_time", packet.get("dts_time")) is not None]
            if kind != "video" and (not head_stamps or not tail_stamps):
                return None
            stream_facts[kind] = {
                "duration": stream_duration,
                "start_time": stream_start,
                "packet_count": int(stream.get("nb_read_packets", 0) or 0),
                "first_pts": min(head_stamps) if head_stamps else None,
                "last_pts": max(tail_stamps) if tail_stamps else None,
                "timestamp_span": max(tail_stamps) - min(head_stamps) if head_stamps and tail_stamps else None,
                "time_base": stream.get("time_base"),
            }
        continuity = None
        if "video" in stream_facts:
            try:
                from aebn_dl.media_validation import scan_video_packet_timing
            except ImportError:
                return None
            continuity = scan_video_packet_timing(path, ffprobe=executable)
            if continuity is None:
                return None
            first, last = continuity.get("min_pts_s"), continuity.get("max_pts_s")
            if first is None or last is None:
                return None
            stream_facts["video"].update({"first_pts": first, "last_pts": last, "timestamp_span": last - first})
        return {"duration": duration, "video": "video" in stream_facts,
                "streams": stream_facts, "video_continuity": continuity}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _tokens(value: str | None) -> list[str]:
    return _TOKEN.findall((value or "").casefold())


def _contains_tokens(haystack: str, needle: str | None) -> bool:
    source, target = _tokens(haystack), _tokens(needle or "")
    if not source or not target or len(target) > len(source):
        return False
    return any(source[index:index + len(target)] == target for index in range(len(source) - len(target) + 1))


def _within_duration(actual: float | None, expected: float | None) -> bool:
    if actual is None or expected is None or expected <= 0:
        return False
    return abs(actual - expected) <= max(120.0, expected * 0.2)


def _enumerate_media(roots: list[Path]):
    def reparse(path: Path) -> bool:
        is_junction = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(is_junction and is_junction())

    for root in roots:
        resolved_root = root.expanduser().resolve()
        if not resolved_root.is_dir():
            continue
        for current, dirs, files in os.walk(resolved_root, topdown=True, followlinks=False):
            # Prune junctions/symlinks so traversal cannot escape the selected root.
            dirs[:] = [name for name in dirs if not reparse(Path(current) / name)]
            for name in files:
                path = Path(current) / name
                if path.suffix.lower() not in MEDIA_EXTENSIONS or reparse(path):
                    continue
                try:
                    resolved = path.resolve(strict=True)
                    resolved.relative_to(resolved_root)
                    info = resolved.stat()
                    if not resolved.is_file():
                        continue
                except (OSError, ValueError):
                    continue
                yield resolved_root, resolved, info


def _archive_statuses(archive_dir: Path | None) -> dict[str, str]:
    """Read archive history as context only; it never marks a scene verified."""
    statuses: dict[str, str] = {}
    if not archive_dir or not archive_dir.is_dir():
        return statuses
    for archive in archive_dir.glob("*.txt"):
        try:
            for line in archive.read_text(encoding="utf-8", errors="replace").splitlines():
                columns = line.split("\t")
                if len(columns) >= 6 and columns[-1].startswith(("http://", "https://")):
                    statuses[columns[-1]] = columns[0]
        except OSError:
            continue
    return statuses


def scan_reconciliation(
    *, files: list[Path | str], download_roots: list[Path | str], archive_dir: Path | str | None,
    database_path: Path | str, movie_factory=None, session=None, probe_video_fn=None, offline: bool = False,
    refresh_metadata: bool = False, progress_callback: Callable[[dict], None] | None = None,
) -> ScanResult:
    """Resolve requested scenes, inventory selected roots, and persist a read-only scan."""
    parsed = parse_scene_inputs(files)
    db_path = Path(database_path).expanduser().resolve()
    roots: list[Path] = []
    root_errors = []
    for raw_root in download_roots:
        try:
            root = Path(raw_root).expanduser().resolve()
            if not root.is_dir():
                root_errors.append(f"download root is not a directory: {root}")
                continue
            roots.append(root)
        except OSError as exc:
            root_errors.append(f"cannot resolve download root {raw_root}: {exc}")
    archive_path = Path(archive_dir).expanduser().resolve() if archive_dir else None
    archive_status = _archive_statuses(archive_path)
    probe = probe_video_fn or probe_video
    if not offline and movie_factory is None:
        from aebn_dl.movie_scraper import Movie
        movie_factory = Movie
    if not offline and session is None:
        from ytaedl.scene_cli import _session
        session = _session()

    metadata_by_movie: dict[str, object | Exception] = {}
    metadata_values: dict[str, dict] = {}
    boundary_errors: dict[str, str] = {}
    map_errors: dict[tuple[str, str], str] = {}
    ordinals: dict[tuple[str, str], int] = {}
    timing: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    movie_requests: dict[str, list[SceneRequest]] = {}
    for request in parsed.requests:
        movie_requests.setdefault(request.movie_key, []).append(request)

    with ReconciliationStore(db_path) as store:
        store.set_setting("download_roots", [str(root) for root in roots])
        store.set_setting("archive_dir", str(archive_path) if archive_path else None)
        # A database is a cumulative reconciliation record. Re-scanning with
        # another URL file must retain earlier requested scenes so candidate
        # eligibility can never shrink to only the newest batch.
        for row in store.execute(
            """SELECT s.movie_key,s.scene_id,s.original_url,m.site,m.content_type,m.movie_id,m.canonical_url
               FROM requested_scenes s JOIN movies m USING(movie_key)"""
        ).fetchall():
            requests = movie_requests.setdefault(row["movie_key"], [])
            existing_request = next((item for item in requests if item.scene_id == row["scene_id"]), None)
            prior_sources = [(source["source_file"], source["source_line"]) for source in store.execute(
                "SELECT source_file,source_line FROM scene_sources WHERE movie_key=? AND scene_id=?",
                (row["movie_key"], row["scene_id"]),
            )]
            if existing_request:
                existing_request.sources = list(dict.fromkeys(existing_request.sources + prior_sources))
            else:
                requests.append(SceneRequest(site=row["site"], content_type=row["content_type"],
                                             movie_id=row["movie_id"], movie_url=row["canonical_url"],
                                             scene_id=row["scene_id"], original_url=row["original_url"],
                                             sources=prior_sources))
        scene_total_done = 0
        for movie_number, (movie_key, requests) in enumerate(movie_requests.items(), 1):
            request = requests[0]
            cached_row = store.execute("SELECT * FROM movies WHERE movie_key=?", (movie_key,)).fetchone()
            cached_scenes = store.metadata_scenes(movie_key) if cached_row else []
            cache_valid = bool(cached_row and cached_row["metadata_status"] == "resolved" and cached_scenes
                               and len(cached_scenes) == cached_row["scene_count"]
                               and [item["ordinal"] for item in cached_scenes] == list(range(1, len(cached_scenes) + 1)))
            using_cache = cache_valid and not refresh_metadata
            if using_cache:
                if cached_row["timing_error"]:
                    boundary_errors[movie_key] = cached_row["timing_error"]
                movie = SimpleNamespace(
                    movie_id=cached_row["movie_id"], title=cached_row["title"], studio_name=cached_row["studio"],
                    total_duration_seconds=cached_row["duration_seconds"],
                    scenes=[SimpleNamespace(scene_id=scene["scene_id"], start_timing=scene["start_seconds"],
                                            end_timing=scene["end_seconds"]) for scene in cached_scenes],
                )

                def cached_resolver(scene_id, _scenes=movie.scenes):
                    seen = set()
                    for item in _scenes:
                        if item.scene_id is None or not re.fullmatch(r"\d+", str(item.scene_id)):
                            raise ValueError("Missing or malformed scene ID metadata in cached AEBN movie page")
                        if item.scene_id in seen:
                            raise ValueError(f"Duplicate AEBN scene ID metadata: {item.scene_id}")
                        seen.add(item.scene_id)
                    if scene_id not in seen:
                        raise ValueError(f"AEBN scene ID {scene_id} not found in movie")
                    return next(index for index, item in enumerate(_scenes, 1) if item.scene_id == scene_id)
                movie.scene_ordinal_for_id = cached_resolver
                metadata_by_movie[movie_key] = movie
            elif offline:
                movie = RuntimeError("metadata unavailable in cache during offline scan")
                metadata_by_movie[movie_key] = movie
            else:
                try:
                    movie = movie_factory(request.movie_url, session)
                    boundary_fetch = getattr(movie, "calculate_scenes_boundaries", None)
                    if boundary_fetch and getattr(movie, "scenes", None):
                        try:
                            boundary_fetch(10.0)
                        except Exception as exc:
                            # Scene IDs remain authoritative; missing timing only prevents verification.
                            boundary_errors[movie_key] = str(exc) or type(exc).__name__
                    metadata_by_movie[movie_key] = movie
                except Exception as exc:
                    movie = exc
                    metadata_by_movie[movie_key] = exc

            if isinstance(movie, Exception):
                meta = {"title": None, "studio": None, "duration": None, "scene_count": None,
                        "metadata_status": "offline" if offline else "error", "metadata_error": str(movie),
                        "timing_error": None, "metadata_at": None}
                metadata_values[movie_key] = meta
                with store.transaction():
                    store.upsert_movie({"movie_key": movie_key, "site": request.site, "content_type": request.content_type,
                                        "movie_id": request.movie_id, "canonical_url": request.movie_url,
                                        "title": None, "studio": None, "duration_seconds": None, "scene_count": None,
                                        "metadata_at": None, "metadata_status": meta["metadata_status"],
                                        "metadata_error": meta["metadata_error"], "timing_error": None})
                    for item in requests:
                        historical = archive_status.get(item.original_url)
                        detail = meta["metadata_error"]
                        if historical:
                            detail = f"{detail}; historical archive status={historical} (not verification evidence)"
                        store.upsert_scene({"movie_key": movie_key, "scene_id": item.scene_id, "ordinal": None,
                                            "start_seconds": None, "end_seconds": None, "original_url": item.original_url,
                                            "metadata_status": meta["metadata_status"], "status": "metadata_error",
                                            "status_detail": detail})
                        for source_file, source_line in item.sources:
                            store.add_source(movie_key, item.scene_id, source_file, source_line)
                        store.record_event("metadata_failed", movie_key=movie_key, scene_id=item.scene_id,
                                           details={"error": meta["metadata_error"], "offline": offline})
            else:
                meta = {"title": getattr(movie, "title", None), "studio": getattr(movie, "studio_name", None),
                        "duration": getattr(movie, "total_duration_seconds", None), "scene_count": len(movie.scenes),
                        "metadata_status": "resolved", "metadata_error": None,
                        "timing_error": boundary_errors.get(movie_key),
                        "metadata_at": cached_row["metadata_at"] if using_cache else now}
                metadata_values[movie_key] = meta
                resolved_scenes = []
                for item in requests:
                    key = (movie_key, item.scene_id)
                    try:
                        ordinal = int(movie.scene_ordinal_for_id(item.scene_id))
                        if ordinal < 1 or ordinal > len(movie.scenes):
                            raise ValueError(f"resolver returned out-of-range ordinal {ordinal}")
                        ordinals[key] = ordinal
                        scene = movie.scenes[ordinal - 1]
                        start = getattr(scene, "start_timing", None)
                        end = getattr(scene, "end_timing", None)
                        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                            start = end = None
                        timing[key] = (start, end)
                    except Exception as exc:
                        map_errors[key] = str(exc) or type(exc).__name__
                    ordinal = ordinals.get(key)
                    start, end = timing.get(key, (None, None))
                    if meta["timing_error"] and (start is None or end is None):
                        detail = f"scene timing unavailable: {meta['timing_error']}"
                    else:
                        detail = None
                    if key in map_errors:
                        status, detail = "mapping_error", map_errors[key]
                    else:
                        status = "scene_missing"
                        if detail:
                            detail = f"no verified local scene output found; {detail}"
                        else:
                            detail = "no verified local scene output found"
                    historical = archive_status.get(item.original_url)
                    if historical:
                        detail = f"{detail}; historical archive status={historical} (not verification evidence)"
                    resolved_scenes.append((item, ordinal, start, end, status, detail, historical))
                with store.transaction():
                    store.upsert_movie({"movie_key": movie_key, "site": request.site, "content_type": request.content_type,
                                        "movie_id": request.movie_id, "canonical_url": request.movie_url,
                                        "title": meta["title"], "studio": meta["studio"],
                                        "duration_seconds": meta["duration"], "scene_count": meta["scene_count"],
                                        "metadata_at": meta["metadata_at"], "metadata_status": "resolved",
                                        "metadata_error": None, "timing_error": meta["timing_error"]})
                    if not using_cache:
                        store.replace_metadata_scenes(movie_key, [
                            {"ordinal": index, "scene_id": getattr(scene, "scene_id", None),
                             "start_seconds": getattr(scene, "start_timing", None),
                             "end_seconds": getattr(scene, "end_timing", None)}
                            for index, scene in enumerate(movie.scenes, 1)
                        ])
                    for item, ordinal, start, end, status, detail, historical in resolved_scenes:
                        store.upsert_scene({"movie_key": movie_key, "scene_id": item.scene_id, "ordinal": ordinal,
                                            "start_seconds": start, "end_seconds": end, "original_url": item.original_url,
                                            "metadata_status": "resolved", "status": status, "status_detail": detail})
                        for source_file, source_line in item.sources:
                            store.add_source(movie_key, item.scene_id, source_file, source_line)
                        store.record_event("scene_scanned", movie_key=movie_key, scene_id=item.scene_id,
                                           details={"status": status, "ordinal": ordinal, "archive_status": historical})
            scene_total_done += len(requests)
            if progress_callback:
                progress_callback({"stage": "metadata", "movies_done": movie_number, "movies_total": len(movie_requests),
                                   "scenes_done": scene_total_done})

        with store.transaction():
            for error in parsed.errors:
                store.record_event("input_error", details={"file": error.source_file, "line": error.line_number,
                                                            "value": error.value, "error": error.message})
        existing_by_movie: dict[str, list[dict]] = {key: [] for key in movie_requests}
        movie_by_first_title_token: dict[str, list[str]] = {}
        metadata_identity: dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]] = {}
        for movie_key, meta in metadata_values.items():
            title_tokens = _tokens(meta.get("title"))
            if title_tokens:
                movie_by_first_title_token.setdefault(title_tokens[0], []).append(movie_key)
                identity_key = (tuple(title_tokens), tuple(_tokens(meta.get("studio"))))
                metadata_identity.setdefault(identity_key, set()).add(movie_key)
        probe_cache: dict[str, dict | None] = {}
        media_count = 0
        for root, path, info in _enumerate_media(roots):
            media_count += 1
            if progress_callback and media_count % 1000 == 0:
                progress_callback({"stage": "inventory", "media_files_seen": media_count})
            stem = path.stem
            possible_movies = {movie_key for token in set(_tokens(stem))
                               for movie_key in movie_by_first_title_token.get(token, [])}
            for movie_key in sorted(possible_movies):
                requests = movie_requests[movie_key]
                metadata = metadata_values.get(movie_key, {})
                title, studio = metadata.get("title"), metadata.get("studio")
                if not title or not _contains_tokens(stem, title):
                    continue
                identity_key = (tuple(_tokens(title)), tuple(_tokens(studio)))
                identity_ambiguous = len(metadata_identity.get(identity_key, set())) > 1
                studio_match = bool(studio and _contains_tokens(stem, studio))
                scene_match = _SCENE_LABEL.search(stem)
                duration = None
                has_video = None
                if scene_match:
                    ordinal = int(scene_match.group(1))
                    relevant = [r for r in requests if ordinals.get((movie_key, r.scene_id)) == ordinal]
                    expected_duration = None
                    if relevant:
                        start, end = timing.get((movie_key, relevant[0].scene_id), (None, None))
                        expected_duration = end - start if start is not None and end is not None else None
                    if relevant and str(path) not in probe_cache:
                        probe_cache[str(path)] = probe(path)
                    facts = probe_cache.get(str(path)) if relevant else None
                    if facts:
                        duration = facts.get("duration")
                        has_video = bool(facts.get("video"))
                    # Inventory probing is discovery evidence only. The independent
                    # verifier must establish audio/video packet coverage before a
                    # scene can be considered verified.
                    duration_candidate = bool(relevant and has_video and _within_duration(duration, expected_duration)
                                              and not identity_ambiguous)
                    classification = "unknown" if identity_ambiguous else "scene"
                    confidence = "high" if studio_match and duration_candidate else "low"
                    evidence = {"title_token_match": True, "studio_token_match": studio_match,
                                "scene_ordinal": ordinal, "container_duration_candidate": duration_candidate,
                                "verification_required": True, "ffprobe": facts,
                                "ambiguous_movie_identity": identity_ambiguous}
                    for request in (requests if identity_ambiguous else relevant):
                        status = "scene_candidate_unverified"
                        if identity_ambiguous:
                            status = "scene_ambiguous"
                        detail = "inventory match requires independent audio/video packet coverage verification"
                        if identity_ambiguous:
                            detail = "filename and scene ordinal match more than one AEBN movie identity"
                        store.execute("UPDATE requested_scenes SET status=?, status_detail=? WHERE movie_key=? AND scene_id=?",
                                      (status, detail, movie_key, request.scene_id))
                else:
                    if studio_match and str(path) not in probe_cache:
                        probe_cache[str(path)] = probe(path)
                    facts = probe_cache.get(str(path)) if studio_match else None
                    if facts:
                        duration = facts.get("duration")
                        has_video = bool(facts.get("video"))
                    is_full_movie = bool(studio_match and has_video and
                                         _within_duration(duration, metadata.get("duration")) and not identity_ambiguous)
                    classification = "full_movie" if is_full_movie else "unknown"
                    confidence = "medium" if is_full_movie else "low"
                    evidence = {"title_token_match": True, "studio_token_match": studio_match,
                                "movie_duration_match": is_full_movie, "ffprobe": facts,
                                "ambiguous_movie_identity": identity_ambiguous}
                previous = store.execute("SELECT size_bytes,mtime_ns,device_id,file_id,classification FROM media_candidates WHERE movie_key=? AND path=?",
                                         (movie_key, str(path))).fetchone()
                identity_changed = bool(previous and (previous["size_bytes"] != info.st_size
                    or previous["mtime_ns"] != info.st_mtime_ns
                    or str(previous["device_id"]) != str(getattr(info, "st_dev", ""))
                    or str(previous["file_id"]) != str(getattr(info, "st_ino", ""))
                    or previous["classification"] != classification))
                store.execute(
                    """INSERT INTO media_candidates(movie_key,path,root_path,classification,scene_ordinal,size_bytes,
                       mtime_ns,device_id,file_id,duration_seconds,has_video,match_evidence,confidence,identity_confirmed,
                       approval) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,'undecided') ON CONFLICT(movie_key,path) DO UPDATE SET
                       root_path=excluded.root_path,classification=excluded.classification,scene_ordinal=excluded.scene_ordinal,
                       size_bytes=excluded.size_bytes,mtime_ns=excluded.mtime_ns,device_id=excluded.device_id,file_id=excluded.file_id,
                       duration_seconds=excluded.duration_seconds,has_video=excluded.has_video,match_evidence=excluded.match_evidence,
                       confidence=excluded.confidence""",
                    (movie_key, str(path), str(root), classification,
                     int(scene_match.group(1)) if scene_match else None, info.st_size, info.st_mtime_ns,
                     str(getattr(info, "st_dev", "")), str(getattr(info, "st_ino", "")), duration,
                     int(has_video) if has_video is not None else None,
                     json.dumps(evidence, ensure_ascii=False), confidence),
                )
                candidate = store.execute("SELECT candidate_id FROM media_candidates WHERE movie_key=? AND path=?",
                                          (movie_key, str(path))).fetchone()
                candidate_id = candidate["candidate_id"]
                store.execute("DELETE FROM candidate_scenes WHERE candidate_id=?", (candidate_id,))
                if identity_changed:
                    store.execute("UPDATE media_candidates SET identity_confirmed=0,approval='undecided',"
                                  "approval_fingerprint=NULL,approved_at=NULL WHERE candidate_id=?", (candidate_id,))
                if classification in {"full_movie", "unknown"} and (not scene_match or identity_ambiguous):
                    for request in requests:
                        store.execute("INSERT OR IGNORE INTO candidate_scenes(candidate_id,movie_key,scene_id,required) VALUES(?,?,?,1)",
                                      (candidate_id, movie_key, request.scene_id))
                elif classification == "scene" and scene_match:
                    for request in requests:
                        if ordinals.get((movie_key, request.scene_id)) == int(scene_match.group(1)):
                            store.execute("INSERT OR IGNORE INTO candidate_scenes(candidate_id,movie_key,scene_id,required) VALUES(?,?,?,1)",
                                          (candidate_id, movie_key, request.scene_id))
                existing_by_movie[movie_key].append({"path": str(path), "classification": classification,
                                                       "scene_ordinal": int(scene_match.group(1)) if scene_match else None})
                store.record_event("media_candidate_scanned", movie_key=movie_key, candidate_id=candidate_id,
                                   details={"path": str(path), "classification": classification, "confidence": confidence})
        if progress_callback:
            progress_callback({"stage": "inventory", "media_files_seen": media_count, "complete": True})

        for movie_key, requests in movie_requests.items():
            statuses = {row["scene_id"]: row["status"] for row in store.execute(
                "SELECT scene_id,status FROM requested_scenes WHERE movie_key=?", (movie_key,))}
            for request in requests:
                status = statuses.get(request.scene_id, "scene_missing")
                store.execute(
                    "INSERT OR IGNORE INTO download_jobs(movie_key,scene_id,target_dir,status) VALUES(?,?,?,?)",
                    (movie_key, request.scene_id, str(roots[0]) if roots else "", "verified" if status == "scene_verified" else "pending"),
                )
            for row in store.execute("SELECT candidate_id,scene_ordinal,path FROM media_candidates WHERE movie_key=? AND classification='scene'", (movie_key,)):
                matches = [r for r in requests if ordinals.get((movie_key, r.scene_id)) == row["scene_ordinal"]]
                for request in matches:
                    scene_status = store.execute("SELECT status FROM requested_scenes WHERE movie_key=? AND scene_id=?",
                                                 (movie_key, request.scene_id)).fetchone()[0]
                    job_status = "verified" if scene_status == "scene_verified" else "pending"
                    store.execute("UPDATE download_jobs SET status=?,verification_status=?,output_path=? WHERE movie_key=? AND scene_id=?",
                                  (job_status, "passed" if job_status == "verified" else "pending",
                                   row["path"], movie_key, request.scene_id))
        store.record_event("scan_finished", details={"inputs": len(parsed.requests), "errors": len(parsed.errors),
                                                       "roots": [str(root) for root in roots]})
        scenes = store.list_scenes()
        candidates = store.list_candidates()
        all_requests = [request for requests in movie_requests.values() for request in requests]
        summary = {
            "requested_urls": sum(max(1, len(request.sources)) for request in all_requests),
            "unique_movies": len(movie_requests), "unique_scenes": len(scenes),
            "verified_scenes": sum(scene["status"] == "scene_verified" for scene in scenes),
            "missing_scenes": sum(scene["status"] == "scene_missing" for scene in scenes),
            "metadata_errors": sum(scene["status"] == "metadata_error" for scene in scenes),
            "mapping_errors": sum(scene["status"] == "mapping_error" for scene in scenes),
            "full_movie_candidates": sum(candidate["classification"] == "full_movie" for candidate in candidates),
            "ambiguous_matches": sum(candidate["classification"] == "unknown" for candidate in candidates),
            "input_errors": len(parsed.errors), "root_errors": len(root_errors),
        }
        errors = root_errors + [f"{e.source_file}:{e.line_number}: {e.message}" for e in parsed.errors]
        for scene in scenes:
            if scene["status"] in {"metadata_error", "mapping_error"}:
                errors.append(f"{scene['movie_id']} scene {scene['scene_id']}: {scene['status_detail']}")
        for movie_key, meta in metadata_values.items():
            if meta.get("timing_error"):
                errors.append(f"{movie_key}: scene timing unavailable: {meta['timing_error']}")
        return ScanResult(db_path, summary, errors)
