"""Privacy-safe normalized observations derived from OpenCode messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import shlex
from typing import Any


@dataclass(frozen=True)
class NormalizedEvent:
    event_id: str
    timestamp: str | None
    observed_at: str | None
    source: str
    category: str
    subtype: str | None
    session_id: str
    job_id: str | None = None
    agent: str | None = None
    model: str | None = None
    provider_id: str | None = None
    part_id: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_target: str | None = None
    outcome: str | None = None
    finish_reason: str | None = None
    completed_at: str | None = None
    provider_completed_at: str | int | float | None = None
    tokens: dict[str, int | float] | None = None
    error_name: str | None = None
    duration_seconds: float | None = None
    provenance: str = "opencode_message"
    confidence: str = "observed"
    coverage: str = "provider_record"

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}


def events_from_messages(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    source: str = "opencode",
    observed_at: str | None = None,
) -> list[NormalizedEvent]:
    """Project provider records into metadata-only events; never copy text/output payloads."""
    events: list[NormalizedEvent] = []
    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        info = _mapping(message.get("info")) or message
        message_id = _string(info.get("id"))
        agent = _string(info.get("agent") or info.get("mode"))
        model = _string(info.get("modelID"))
        message_time = _mapping(info.get("time"))
        role = info.get("role")
        events.append(
            NormalizedEvent(
                event_id=_event_id(source, session_id, "message", message_id, message_index),
                timestamp=_time_iso(message_time.get("created")),
                observed_at=observed_at,
                source=source,
                category="message",
                subtype=_string(role),
                session_id=session_id,
                agent=agent,
                model=model,
                provider_id=message_id,
            )
        )
        if role == "assistant":
            tokens = _tokens(info.get("tokens"))
            completed = message_time.get("completed")
            finish = _string(info.get("finish"))
            error_data = _mapping(info.get("error"))
            events.append(
                NormalizedEvent(
                    event_id=_event_id(source, session_id, "inference", message_id, message_index),
                    timestamp=_time_iso(message_time.get("created")),
                    observed_at=observed_at,
                    source=source,
                    category="inference",
                    subtype="completed" if completed is not None or finish else "running",
                    session_id=session_id,
                    agent=agent,
                    model=model,
                    provider_id=message_id,
                    outcome="failed" if error_data else "completed" if completed is not None or finish else "running",
                    finish_reason=finish,
                    error_name=_string(error_data.get("name")),
                    completed_at=_time_iso(completed),
                    provider_completed_at=completed if isinstance(completed, (str, int, float)) else None,
                    tokens=tokens,
                    duration_seconds=_duration(message_time.get("created"), completed),
                )
            )

        parts = message.get("parts")
        if not isinstance(parts, list):
            continue
        for part_index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            part_id = _string(part.get("id"))
            part_type = part.get("type")
            if part_type == "compaction":
                part_time = _mapping(part.get("time"))
                state = _string(part.get("status") or part.get("state"))
                if part_time.get("completed") is not None:
                    state = "completed"
                elif part_time.get("started") is not None:
                    state = "running"
                compaction_id = (_string(part.get("compactionID")) or _string(part.get("operationID"))
                                 or part_id or _string(part.get("messageID")) or message_id)
                events.append(
                    NormalizedEvent(
                        event_id=_event_id(source, session_id, "compaction", compaction_id, part_index),
                        timestamp=_time_iso(part_time.get("started") or message_time.get("created")),
                        observed_at=observed_at,
                        source=source,
                        category="compaction",
                        subtype="cycle",
                        session_id=session_id,
                        agent=agent,
                        model=model,
                        provider_id=compaction_id,
                        part_id=part_id,
                        outcome=state,
                        duration_seconds=_duration(part_time.get("started"), part_time.get("completed")),
                        provenance="opencode_compaction_part",
                    )
                )
            elif part_type == "tool":
                state = _mapping(part.get("state"))
                tool_time = _mapping(state.get("time"))
                input_data = _mapping(state.get("input"))
                call_id = _string(part.get("callID"))
                tool_name = _string(part.get("tool"))
                tool_status = _string(state.get("status"))
                outcome = {
                    "completed": "succeeded",
                    "error": "failed",
                    "running": "running",
                }.get(tool_status, tool_status)
                events.append(
                    NormalizedEvent(
                        event_id=_event_id(source, session_id, "tool", call_id or part_id or message_id,
                                           part_index),
                        timestamp=_time_iso(tool_time.get("start") or message_time.get("created")),
                        observed_at=observed_at,
                        source=source,
                        category="tool",
                        subtype="invocation",
                        session_id=session_id,
                        agent=agent,
                        model=model,
                        provider_id=message_id,
                        part_id=part_id,
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        tool_target=_tool_target(tool_name, input_data),
                        outcome=outcome,
                        duration_seconds=_duration(tool_time.get("start"), tool_time.get("end")),
                        provenance="opencode_tool_part",
                    )
                )
    return events


def _tool_target(name: str | None, tool_input: dict[str, Any]) -> str | None:
    if not name:
        return None
    target_keys = ("filePath", "path", "file", "file_path")
    if name.lower() in {"read", "edit", "write", "patch", "multiedit"}:
        for key in target_keys:
            value = tool_input.get(key)
            if isinstance(value, str) and value and len(value) <= 2048:
                return value
    command = tool_input.get("command")
    if name.lower() in {"shell", "bash", "powershell", "terminal"} and isinstance(command, str):
        return _shell_read_target(command)
    return None


def _shell_read_target(command: str) -> str | None:
    """Extract one path only from clearly recognizable, simple file-read commands."""
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        return None
    if not tokens:
        return None
    executable = tokens[0].strip('"\'').replace("\\", "/").rsplit("/", 1)[-1].lower()
    read_commands = {"cat", "sed", "head", "tail", "get-content", "type", "more"}
    if executable not in read_commands:
        return None
    candidates = [token.strip('"\'') for token in tokens[1:] if token and not token.startswith("-")]
    if executable == "sed":
        candidates = [token for token in candidates if not token.startswith("'")]
    if candidates:
        target = candidates[-1]
        return target[:2048] or None
    return None


def _tokens(value: Any) -> dict[str, int | float] | None:
    token_data = _mapping(value)
    if not token_data:
        return None
    result: dict[str, int | float] = {}
    for source_key, target_key in (("input", "input"), ("output", "output"), ("reasoning", "reasoning"),
                                   ("total", "total")):
        number = _number(token_data.get(source_key))
        if number is not None:
            result[target_key] = number
    cache = _mapping(token_data.get("cache"))
    for source_key, target_key in (("read", "cache_read"), ("write", "cache_write")):
        number = _number(cache.get(source_key))
        if number is not None:
            result[target_key] = number
    return result or None


def _duration(start: Any, end: Any) -> float | None:
    start_value, end_value = _number(start), _number(end)
    if start_value is None or end_value is None or end_value < start_value:
        return None
    # OpenCode message/part time boundaries are epoch milliseconds; duration
    # conversion is therefore independent of the absolute epoch magnitude.
    return round((end_value - start_value) / 1000.0, 3)


def _time_iso(value: Any) -> str | None:
    number = _number(value)
    if number is not None:
        try:
            seconds = number / 1000
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            return None
    return None


def _event_id(source: str, session_id: str, category: str, provider_id: str | None, index: int) -> str:
    stable = provider_id if provider_id else f"missing-id:{index}"
    value = json.dumps([source, session_id, category, stable], separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value
