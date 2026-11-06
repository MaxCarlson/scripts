"""Fail-closed checks for completed AEBN media artifacts.

These checks use stream-level coverage rather than the container duration, which
can be extended by a healthy audio track while video is truncated.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def validate_media_facts(
    facts: dict,
    *,
    expected_duration: float | None,
    required_streams: tuple[str, ...] = ("video", "audio"),
    tolerance_seconds: float | None = None,
) -> dict:
    """Validate required stream presence and duration/timestamp coverage.

    A 5% duration allowance (at least 8 seconds) covers segment-boundary
    alignment while remaining far below a full-movie/scene mismatch.
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

    tolerance = tolerance_seconds if tolerance_seconds is not None else max(8.0, expected_duration * 0.05)
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
                for interval in ("%+#24", f"{tail_start}%+#24"):
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
        return facts
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError):
        return None
