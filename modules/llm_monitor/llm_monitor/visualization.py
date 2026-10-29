"""Offline static SVG/HTML renderers consuming normalized analysis results."""
from __future__ import annotations

from html import escape
import os
from pathlib import Path
import tempfile
from typing import Any


def _svg(title: str, rows: list[tuple[str, list[dict[str, Any]]]], duration: float) -> str:
    width, row_height, top = 1000, 72, 70
    height = top + row_height * max(1, len(rows)) + 50
    scale = (width - 270) / max(duration, 1.0)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<style>text{font:14px sans-serif;fill:#202124}.axis{stroke:#999}.bar{fill:#3977b8}.marker{fill:#c65b37}</style>',
             f'<text x="20" y="32" font-size="20">{escape(title)}</text>',
             f'<line class="axis" x1="250" y1="{top-12}" x2="{width-20}" y2="{top-12}"/>']
    for index, (label, events) in enumerate(rows):
        y = top + index * row_height
        parts.append(f'<text x="20" y="{y+20}">{escape(label)}</text>')
        parts.append(f'<line class="axis" x1="250" y1="{y+30}" x2="{width-20}" y2="{y+30}"/>')
        for event in events:
            timestamp = event.get("timestamp_seconds")
            if timestamp is None:
                continue
            x = 250 + max(0.0, min(duration, float(timestamp))) * scale
            seconds = event.get("duration_seconds")
            if isinstance(seconds, (int, float)) and seconds > 0:
                bar_width = max(2.0, min(float(width-270), seconds * scale))
                parts.append(f'<rect class="bar" x="{x:.1f}" y="{y+9}" width="{bar_width:.1f}" height="18"><title>{escape(str(event.get("label", label)))}</title></rect>')
            else:
                parts.append(f'<circle class="marker" cx="{x:.1f}" cy="{y+18}" r="5"><title>{escape(str(event.get("label", label)))}</title></circle>')
    parts.append(f'<text x="250" y="{height-14}">0 s</text><text x="{width-90}" y="{height-14}">{duration:.1f} s</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def render_session(analysis: dict[str, Any], *, output_format: str = "svg") -> str:
    timeline = analysis.get("metrics", {}).get("timeline", {})
    markers = timeline.get("markers", [])
    start = timeline.get("start") or analysis.get("session", {}).get("first_observed")
    def relative(event: dict[str, Any]) -> float | None:
        value = event.get("timestamp")
        if value is None or start is None:
            return None
        try:
            from datetime import datetime
            return (datetime.fromisoformat(value.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()
        except (ValueError, TypeError):
            return None
    rows = []
    for category in ("inference", "tool", "compaction", "lifecycle", "hardware"):
        events = []
        for marker in markers:
            if marker.get("category") != category:
                continue
            events.append({"timestamp_seconds": relative(marker), "duration_seconds": marker.get("duration_seconds"),
                           "label": marker.get("subtype") or marker.get("tool_name") or category})
        rows.append((category.title(), events))
    inferences = [marker for marker in markers if marker.get("category") == "inference"]
    for token_name in ("input", "output", "reasoning"):
        points = []
        for marker in inferences:
            amount = (marker.get("tokens") or {}).get(token_name)
            if isinstance(amount, (int, float)):
                points.append({"timestamp_seconds": relative(marker), "label": f"{token_name}: {amount:,}"})
        rows.append((f"{token_name.title()} tokens per inference", points))
    context_points = [{"timestamp_seconds": relative(marker),
                       "label": f"context: {marker['context_utilization_percent']:.1f}%"}
                      for marker in inferences if isinstance(marker.get("context_utilization_percent"), (int, float))]
    rows.append(("Context utilization", context_points))
    observed_duration = analysis.get("metrics", {}).get("execution", {}).get("observed_wall_seconds")
    duration = observed_duration.get("value") if isinstance(observed_duration, dict) else None
    duration = duration or 1.0
    session_id = analysis.get("session", {}).get("session_id", "session")
    svg = _svg(f"LLM Monitor history: {session_id}", rows, float(duration))
    if output_format == "svg":
        return svg
    if output_format == "html":
        return '<!doctype html><html><meta charset="utf-8"><title>LLM Monitor history</title><body>' + svg + '</body></html>'
    raise ValueError("output_format must be svg or html")


def render_comparison(comparison: dict[str, Any], *, output_format: str = "svg") -> str:
    sessions = comparison.get("runs", [])
    rows = []
    max_duration = 1.0
    for item in sessions:
        metrics = item.get("metrics", {})
        observed_duration = metrics.get("execution", {}).get("observed_wall_seconds")
        duration = observed_duration.get("value") if isinstance(observed_duration, dict) else None
        duration = duration or 1.0
        max_duration = max(max_duration, float(duration))
        rows.append((str(item.get("session", {}).get("session_id", "session")), [{"timestamp_seconds": 0, "duration_seconds": duration,
                                                                  "label": "observed duration"}]))
    content = _svg("LLM Monitor session comparison", rows, max_duration)
    if output_format == "svg":
        return content
    if output_format == "html":
        return '<!doctype html><html><meta charset="utf-8"><title>LLM Monitor comparison</title><body>' + content + '</body></html>'
    raise ValueError("output_format must be svg or html")


def write_visualization(path: Path, content: str) -> None:
    target = Path(path).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix=".llm-monitor-",
                                         suffix=".tmp", dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
