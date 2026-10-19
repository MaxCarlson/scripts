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


# Compatibility alias for callers expecting iter_sse_events
iter_sse_events = parse_sse_events


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
    Supports common OpenAI and LM Studio streaming shapes for assistant output:
      - chat.completion.chunk: choices[0].delta.content
      - legacy completion: choices[0].text
      - responses stream: output[0].content[0].text or delta string.
    Note: Does not extract reasoning_content to prevent accidental dumping.
    """
    choices = chunk.get("choices")
    if isinstance(choices, list) and choices:
        c0 = choices[0]
        if isinstance(c0, dict):
            delta = c0.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str):
                    return content
            text = c0.get("text")
            if isinstance(text, str):
                return text

    # Responses API deltas
    delta = chunk.get("delta")
    if isinstance(delta, str):
        return delta

    output = chunk.get("output")
    if isinstance(output, list) and output:
        parts = output[0].get("content")
        if isinstance(parts, list) and parts:
            p0 = parts[0]
            if isinstance(p0, dict) and isinstance(p0.get("text"), str):
                return p0["text"]

    if "output_text" in chunk and isinstance(chunk["output_text"], str):
        return chunk["output_text"]
    return ""


def extract_reasoning_delta(chunk: Dict[str, Any]) -> str:
    """
    Extract reasoning/thinking tokens when reported.
    """
    choices = chunk.get("choices")
    if isinstance(choices, list) and choices:
        c0 = choices[0]
        if isinstance(c0, dict):
            delta = c0.get("delta")
            if isinstance(delta, dict):
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if isinstance(reasoning, str):
                    return reasoning
    return ""


def extract_usage_from_chunk(chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    usage = chunk.get("usage")
    if isinstance(usage, dict):
        return usage
    return None

