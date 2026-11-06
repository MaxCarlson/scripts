"""Fail-closed checks for completed AEBN media artifacts.

These checks use stream-level coverage rather than the container duration, which
can be extended by a healthy audio track while video is truncated.
"""

from __future__ import annotations

import json
import heapq
import math
import shutil
import subprocess
import threading
from pathlib import Path

VALIDATION_CONTRACT = 4


def summarize_video_packets(packets) -> dict:
    """Summarize a packet iterator in bounded memory, allowing B-frame reordering."""
    queue = []
    previous_pts = None
    previous_dts = None
    minimum_pts = maximum_pts = None
    maximum_pts_gap = maximum_dts_gap = 0.0
    count = invalid = regressions = tiny_run = longest_tiny_run = 0
    tiny_dts_run = longest_tiny_dts_run = 0

    def consume(pts: float) -> None:
        nonlocal previous_pts, maximum_pts_gap
        if previous_pts is not None:
            maximum_pts_gap = max(maximum_pts_gap, pts - previous_pts)
        previous_pts = pts

    for packet in packets:
        try:
            pts, dts, duration = (float(packet[key]) for key in ("pts", "dts", "duration"))
            if not all(math.isfinite(value) for value in (pts, dts, duration)) or duration < 0:
                raise ValueError("invalid packet timestamp")
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        count += 1
        minimum_pts = pts if minimum_pts is None else min(minimum_pts, pts)
        maximum_pts = pts if maximum_pts is None else max(maximum_pts, pts)
        if previous_dts is not None:
            increment = dts - previous_dts
            maximum_dts_gap = max(maximum_dts_gap, increment)
            if dts < previous_dts - 0.000001:
                regressions += 1
            tiny_dts_run = tiny_dts_run + 1 if 0 <= increment < 0.001 else 0
            longest_tiny_dts_run = max(longest_tiny_dts_run, tiny_dts_run)
        previous_dts = dts
        tiny_run = tiny_run + 1 if duration < 0.001 else 0
        longest_tiny_run = max(longest_tiny_run, tiny_run)
        heapq.heappush(queue, pts)
        if len(queue) > 128:
            consume(heapq.heappop(queue))
    while queue:
        consume(heapq.heappop(queue))
    return {"packet_count": count, "invalid_packets": invalid, "dts_regressions": regressions,
            "min_pts_s": minimum_pts, "max_pts_s": maximum_pts,
            "max_pts_gap_s": maximum_pts_gap, "max_dts_gap_s": maximum_dts_gap,
            "longest_tiny_duration_run": longest_tiny_run, "longest_tiny_dts_run": longest_tiny_dts_run}


def validate_video_continuity(stats: dict | None, expected_duration: float) -> list[str]:
    """Flag major timing defects; permit ordinary variable rates and B frames."""
    required = {"packet_count", "invalid_packets", "dts_regressions", "max_pts_gap_s", "max_dts_gap_s",
                "longest_tiny_duration_run", "longest_tiny_dts_run"}
    if not stats or not required.issubset(stats) or not stats.get("packet_count") or stats.get("invalid_packets"):
        return ["video packet timing evidence is unavailable or malformed"]
    issues = []
    gap_limit = min(30.0, max(10.0, expected_duration * 0.05))
    if stats.get("dts_regressions", 0):
        issues.append("video decode timestamps regress")
    if max(stats.get("max_pts_gap_s", 0), stats.get("max_dts_gap_s", 0)) > gap_limit:
        issues.append("video packet timeline contains a large internal gap")
    if stats.get("longest_tiny_duration_run", 0) >= 100:
        issues.append("video contains a long cluster of near-zero packet durations")
    if stats.get("longest_tiny_dts_run", 0) >= 100:
        issues.append("video contains a long cluster of near-zero decode-time increments")
    if expected_duration >= 60 and stats["packet_count"] / expected_duration < 0.2:
        issues.append("video packet density is implausibly low")
    return issues


def scan_video_packet_timing(path: str | Path, *, ffprobe: str | None = None, timeout: float = 300) -> dict | None:
    """Stream packet timestamps from ffprobe without retaining the packet list."""
    executable = ffprobe or shutil.which("ffprobe")
    if not executable:
        return None
    try:
        proc = subprocess.Popen(
            [executable, "-v", "error", "-select_streams", "v:0", "-show_packets",
             "-show_entries", "packet=pts_time,dts_time,duration_time", "-of", "csv=p=0", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return None
    timed_out = threading.Event()
    def stop() -> None:
        if proc.poll() is None:
            timed_out.set()
            proc.kill()
    timer = threading.Timer(timeout, stop)
    timer.daemon = True
    timer.start()
    try:
        def packets():
            for line in proc.stdout:
                if not line.strip():
                    continue
                fields = line.strip().split(",")
                if len(fields) < 3:
                    yield {}
                else:
                    yield {"pts": fields[0], "dts": fields[1], "duration": fields[2]}
        stats = summarize_video_packets(packets())
        if proc.wait() != 0 or timed_out.is_set():
            return None
        return stats
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if proc.stdout:
            proc.stdout.close()


def validate_media_facts(
    facts: dict,
    *,
    expected_duration: float | None,
    required_streams: tuple[str, ...] = ("video", "audio"),
    tolerance_seconds: float | None = None,
) -> dict:
    """Validate required stream presence and duration/timestamp coverage.

    A 5% duration allowance (at least 8 seconds) covers segment-boundary
    alignment, capped at 20% so short scenes cannot lose most of their video.
    """
    errors: list[str] = []
    evidence: dict = {"container_duration_s": None, "streams": {}}
    try:
        container_duration = float(facts.get("format", {}).get("duration"))
        if container_duration > 0:
            evidence["container_duration_s"] = container_duration
    except (TypeError, ValueError, AttributeError):
        pass

    if expected_duration is None or expected_duration <= 0:
        return {"valid": False, "status": "unknown", "errors": ["expected media duration is unavailable"], "evidence": evidence}

    tolerance = tolerance_seconds if tolerance_seconds is not None else min(
        max(8.0, expected_duration * 0.05), expected_duration * 0.2
    )
    if "video" in required_streams:
        continuity = facts.get("video_continuity")
        evidence["video_continuity"] = continuity
        errors.extend(validate_video_continuity(continuity, expected_duration))
    streams = facts.get("streams") or []
    for kind in required_streams:
        matches = [stream for stream in streams if stream.get("codec_type") == kind]
        if not matches:
            errors.append(f"required {kind} stream is missing")
            continue
        stream = matches[0]
        try:
            duration = float(stream.get("duration"))
        except (TypeError, ValueError):
            duration = None
        try:
            start = float(stream.get("start_time", 0.0))
        except (TypeError, ValueError):
            start = None
        timeline = (facts.get("packet_timeline") or {}).get(kind) or {}
        try:
            min_pts = float(timeline["min_pts"])
            max_pts = float(timeline["max_pts"])
            span = max_pts - min_pts
        except (KeyError, TypeError, ValueError):
            min_pts = max_pts = span = None
        try:
            packet_count = int(timeline.get("packet_count", stream.get("nb_read_packets", 0)))
        except (TypeError, ValueError):
            packet_count = 0
        record = {"duration_s": duration, "start_time_s": start, "packet_span_s": span,
                  "packet_count": packet_count, "min_pts_s": min_pts, "max_pts_s": max_pts}
        evidence["streams"][kind] = record
        if duration is None or duration <= 0:
            errors.append(f"{kind} stream duration is unavailable")
        elif abs(duration - expected_duration) > tolerance:
            errors.append(f"{kind} stream duration {duration:.3f}s does not cover expected {expected_duration:.3f}s")
        if packet_count <= 0:
            errors.append(f"{kind} stream has no readable packets")
        if span is None:
            errors.append(f"{kind} packet timestamp coverage is unavailable")
        elif span < expected_duration - tolerance:
            errors.append(f"{kind} packet timestamp timeline spans only {span:.3f}s")
        if start is not None and abs(start) > tolerance:
            errors.append(f"{kind} stream starts at {start:.3f}s, outside the expected scene interval")

    durations = [evidence["streams"][kind]["duration_s"] for kind in required_streams
                 if kind in evidence["streams"] and evidence["streams"][kind]["duration_s"] is not None]
    if len(durations) > 1 and max(durations) - min(durations) > tolerance:
        errors.append("required audio/video stream coverage differs materially")
    if evidence["container_duration_s"] is not None and abs(evidence["container_duration_s"] - expected_duration) > tolerance:
        errors.append("container duration does not match expected media duration")

    return {"valid": not errors, "status": "passed" if not errors else "failed", "errors": errors,
            "validation_contract": VALIDATION_CONTRACT,
            "evidence": {**evidence, "expected_duration_s": expected_duration, "tolerance_s": tolerance}}


def probe_media(path: str | Path, *, ffprobe: str | None = None) -> dict | None:
    """Probe stream facts and bounded head/tail packet timestamps.

    The primary stream duration comes from ffprobe's stream metadata. A small
    packet sample at each end independently detects collapsed timestamps without
    materializing every packet from a long movie.
    """
    executable = ffprobe or shutil.which("ffprobe")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "-v", "error", "-count_packets", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=90, check=True,
        )
        facts = json.loads(result.stdout)
        timelines = {}
        for kind, selector in (("video", "v:0"), ("audio", "a:0")):
            selected = next((s for s in facts.get("streams", []) if s.get("codec_type") == kind), None)
            if selected:
                duration = float(selected.get("duration", 0) or 0)
                start = float(selected.get("start_time", 0) or 0)
                tail_start = max(0.0, start + duration - 1.0)
                sampled = []
                sample_count = 128 if kind == "audio" else 24
                for interval in (f"%+#{sample_count}", f"{tail_start}%+#{sample_count}"):
                    packet_result = subprocess.run(
                        [executable, "-v", "error", "-select_streams", selector, "-read_intervals", interval,
                         "-show_packets", "-show_entries", "packet=pts_time,dts_time,size", "-of", "json", str(path)],
                        capture_output=True, text=True, timeout=45, check=True,
                    )
                    sampled.append([
                        float(value)
                        for packet in json.loads(packet_result.stdout).get("packets", [])
                        if (value := packet.get("pts_time", packet.get("dts_time"))) is not None
                    ])
                # Head and tail samples establish coverage while keeping probe output bounded.
                min_pts = min(sampled[0]) if sampled[0] else None
                max_pts = max(sampled[1]) if sampled[1] else None
                timelines[kind] = {"min_pts": min_pts, "max_pts": max_pts,
                                   "packet_count": int(selected.get("nb_read_packets", 0) or 0)}
        facts["packet_timeline"] = timelines
        if any(stream.get("codec_type") == "video" for stream in facts.get("streams", [])):
            facts["video_continuity"] = scan_video_packet_timing(path, ffprobe=executable)
            video_stats = facts["video_continuity"]
            if video_stats and "video" in timelines:
                timelines["video"]["min_pts"] = video_stats["min_pts_s"]
                timelines["video"]["max_pts"] = video_stats["max_pts_s"]
        return facts
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError):
        return None
