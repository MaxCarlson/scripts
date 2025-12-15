from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional


@dataclass(frozen=True)
class SseEvent:
    event: str | None
    data: str


def parse_sse_events(lines: Iterator[str]) -> Iterator[SseEvent]:
    """
    Minimal SSE parser.

    Collects consecutive "data:" lines until a blank line.
    Ignores comments and unknown fields.
    """
    cur_event: str | None = None
    data_lines: List[str] = []

    def flush() -> SseEvent | None:
        nonlocal cur_event, data_lines
        if not data_lines:
            cur_event = None
            return None
        data = "\n".join(data_lines)
        ev = SseEvent(event=cur_event, data=data)
        cur_event = None
        data_lines = []
        return ev

    for line in lines:
        if line == "":
            ev = flush()
            if ev is not None:
                yield ev
            continue

        if line.startswith(":"):
            continue

        if line.startswith("event:"):
            cur_event = line[len("event:") :].strip()
            continue

        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
            continue

    ev = flush()
    if ev is not None:
        yield ev


def iter_openai_stream_chunks(lines: Iterator[str]) -> Iterator[Dict[str, Any]]:
    """
    Given raw lines from an OpenAI-compatible streaming response (SSE),
    yield JSON objects for each chunk until [DONE].
    """
    for ev in parse_sse_events(lines):
        payload = ev.data.strip()
        if not payload:
            continue
        if payload == "[DONE]":
            break
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def extract_delta_text(chunk: Dict[str, Any]) -> str:
    """
    Supports common OpenAI streaming shapes:
      - chat.completion.chunk: choices[0].delta.content
      - responses stream: output_text deltas may differ; we do best-effort.
    """
    choices = chunk.get("choices")
    if isinstance(choices, list) and choices:
        delta = choices[0].get("delta", {})
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                return content
    if "output_text" in chunk and isinstance(chunk["output_text"], str):
        return chunk["output_text"]
    return ""
