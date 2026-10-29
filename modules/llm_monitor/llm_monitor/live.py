"""Bounded, read-only OpenCode SSE diagnostics for one worker session."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any, BinaryIO, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

MAX_EVENT_BYTES = 256 * 1024
MAX_PARTS = 64
MAX_PART_CHARS = 4096
MAX_SESSION_TEXT_CHARS = 16 * 1024
MAX_DISPLAY_CHARS = MAX_SESSION_TEXT_CHARS
MAX_TOOL_IDS = 256
MAX_OBSERVE_SECONDS = 3600.0
MAX_REQUEST_EVIDENCE_BYTES = 128 * 1024
READ_ONLY_TOOLS = {"read", "glob", "grep", "list", "search", "webfetch"}
FILE_WRITE_TOOLS = {"edit", "write", "patch", "apply_patch", "multiedit"}
REQUEST_PARAMETER_ALLOWLIST = {"reasoning", "reasoning_effort", "max_tokens", "max_output_tokens", "temperature",
                               "top_p", "top_k"}
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*(['\"]?)[^\s,;\"']{6,}"),
)


@dataclass(frozen=True)
class SSEEvent:
    event: str | None = None
    event_id: str | None = None
    data: str = ""
    error: str | None = None


@dataclass(frozen=True)
class NormalizedLiveEvent:
    event_type: str
    session_id: str
    directory: str | None
    message_id: str | None
    part_id: str | None
    part_type: str | None
    field: str | None
    delta: str | None
    part_text: str | None
    tool_name: str | None
    tool_status: str | None
    finish_reason: str | None
    reasoning_tokens: int | None
    timestamp: float | None
    raw_event_id: str | None = None


def iter_sse_events(stream: BinaryIO, *, max_event_bytes: int = MAX_EVENT_BYTES) -> Iterator[SSEEvent]:
    """Parse SSE frames incrementally, dropping oversized frames without unbounded reads."""
    event_name: str | None = None
    event_id: str | None = None
    data_lines: list[str] = []
    frame_size = 0
    oversized = False

    while True:
        line = stream.readline(max_event_bytes + 2)
        if not line:
            if oversized:
                yield SSEEvent(error="oversized_event")
            elif data_lines or event_name is not None:
                yield _sse_frame(event_name, event_id, data_lines)
            break
        frame_size += len(line)
        if frame_size > max_event_bytes or (len(line) > max_event_bytes and not line.endswith(b"\n")):
            oversized = True
        if line.endswith(b"\n") and not oversized:
            decoded = line.rstrip(b"\r\n").decode("utf-8", errors="replace")
            if decoded == "":
                if oversized:
                    yield SSEEvent(error="oversized_event")
                elif data_lines or event_name is not None:
                    yield _sse_frame(event_name, event_id, data_lines)
                event_name, event_id, data_lines = None, None, []
                frame_size, oversized = 0, False
                continue
            if decoded.startswith(":") or oversized:
                continue
            field, separator, value = decoded.partition(":")
            if separator and value.startswith(" "):
                value = value[1:]
            if field == "event":
                event_name = value
            elif field == "id" and "\x00" not in value:
                event_id = value
            elif field == "data":
                data_lines.append(value)
        elif line in (b"\n", b"\r\n"):
            if oversized:
                yield SSEEvent(error="oversized_event")
            elif data_lines or event_name is not None:
                yield _sse_frame(event_name, event_id, data_lines)
            event_name, event_id, data_lines = None, None, []
            frame_size, oversized = 0, False


def _sse_frame(event_name: str | None, event_id: str | None, data_lines: list[str]) -> SSEEvent:
    return SSEEvent(event_name, event_id, "\n".join(data_lines))


def normalize_opencode_event(
    value: Any,
    *,
    project_directory: str,
    session_id: str,
    raw_event_id: str | None = None,
) -> NormalizedLiveEvent | None:
    """Unwrap project/global envelopes, then discard mismatched identities."""
    if not isinstance(value, dict):
        return None
    outer = value
    directory = _string(outer.get("directory") or outer.get("projectDirectory"))
    payload = outer.get("payload", outer)
    if not isinstance(payload, dict):
        return None
    properties = payload.get("properties", {})
    if not isinstance(properties, dict):
        return None
    directory = directory or _string(properties.get("directory") or properties.get("projectDirectory"))
    if directory is not None and _directory_key(directory) != _directory_key(project_directory):
        return None
    observed_session = _string(properties.get("sessionID") or properties.get("sessionId") or
                               properties.get("session_id"))
    if observed_session != session_id:
        return None
    event_type = _string(payload.get("type"))
    if event_type is None:
        return None

    part = properties.get("part")
    if not isinstance(part, dict):
        part = {}
    message = properties.get("message")
    if not isinstance(message, dict):
        message = {}
    info = properties.get("info")
    if not isinstance(info, dict):
        info = message.get("info") if isinstance(message.get("info"), dict) else message
    part_state = part.get("state") if isinstance(part.get("state"), dict) else {}
    tool_name = _string(part.get("tool") or properties.get("tool"))
    if part.get("type") == "tool" and tool_name is None:
        tool_name = _string(part.get("name"))
    status_value = part_state.get("status") or properties.get("status")
    if isinstance(status_value, dict):
        status_value = status_value.get("type")
    status = _string(status_value)
    reasoning_tokens = info.get("tokens", {}).get("reasoning") if isinstance(info.get("tokens"), dict) else None
    if not isinstance(reasoning_tokens, int) or isinstance(reasoning_tokens, bool) or reasoning_tokens < 0:
        reasoning_tokens = None
    timestamp = _number((info.get("time") or {}).get("created")) if isinstance(info.get("time"), dict) else None
    if timestamp is not None and timestamp > 10_000_000_000:
        timestamp /= 1000.0
    return NormalizedLiveEvent(
        event_type=event_type,
        session_id=observed_session,
        directory=directory,
        message_id=_string(properties.get("messageID") or properties.get("messageId") or
                            properties.get("message_id") or part.get("messageID") or info.get("id")),
        part_id=_string(properties.get("partID") or properties.get("partId") or properties.get("part_id") or
                        part.get("id")),
        part_type=_string(part.get("type")),
        field=_string(properties.get("field")),
        delta=_string(properties.get("delta")),
        part_text=_string(part.get("text")),
        tool_name=tool_name,
        tool_status=status,
        finish_reason=_string(info.get("finish")),
        reasoning_tokens=reasoning_tokens,
        timestamp=timestamp,
        raw_event_id=raw_event_id,
    )


@dataclass
class _Part:
    message_id: str
    part_id: str
    part_type: str | None
    text: str = ""
    completed: bool = False


class LiveSessionState:
    """Bounded in-memory aggregation for one explicitly selected session."""

    def __init__(self, session_id: str, project_directory: str, *, include_reasoning: bool = False):
        self.session_id = session_id
        self.project_directory = project_directory
        self.include_reasoning = include_reasoning
        self.parts: OrderedDict[tuple[str, str], _Part] = OrderedDict()
        self.part_delta_chars: OrderedDict[tuple[str, str], int] = OrderedDict()
        self.part_char_categories: dict[tuple[str, str], str | None] = {}
        self.part_classified_chars: dict[tuple[str, str], int] = {}
        self.pending_deltas: OrderedDict[tuple[str, str], str] = OrderedDict()
        self.tool_ids: OrderedDict[str, str] = OrderedDict()
        self.live_tool_records: OrderedDict[str, tuple[str, str | None]] = OrderedDict()
        self.file_write_ids: set[str] = set()
        self.successful_file_write_ids: set[str] = set()
        self.tool_names: list[str] = []
        self.tool_calls_observed = 0
        self.read_only_tools = 0
        self.file_writes_observed = 0
        self.successful_file_edits = 0
        self.history_coverage = "unavailable"
        self.last_tool: str | None = None
        self.activity = "unknown"
        self.stream_capability = "unavailable"
        self.stream_connected = False
        self.sse_frames_received = 0
        self.matching_session_events = 0
        self.filtered_events = 0
        self.malformed_events = 0
        self.oversized_events = 0
        self.has_session_activity = False
        self.has_incremental_content = False
        self.has_completed_content = False
        self.reasoning_chars = 0
        self.text_chars = 0
        self.last_event_at: float | None = None
        self.last_reasoning_at: float | None = None
        self.reasoning_started_at: float | None = None
        self.started_at: float | None = None
        self.last_completed_reasoning_tokens: int | None = None
        self.last_completed_finish_reason: str | None = None
        self.last_completed_at: float | None = None
        self.last_completed_output_tokens: int | None = None
        self.last_completed_message_id: str | None = None
        self.inference_started_at: float | None = None
        self.output_limits: dict[str, Any] | None = None
        self.reasoning_provenance: dict[str, Any] | None = None
        self.warnings: set[str] = set()
        self._seen_sse_ids: OrderedDict[str, None] = OrderedDict()

    def mark_connected(self) -> None:
        self.stream_connected = True

    def note_telemetry_error(self, reason: str) -> None:
        if reason in {"malformed_event", "oversized_event", "connection_gap", "stream_unavailable"}:
            self.warnings.add("telemetry_incomplete")
        if reason == "connection_gap":
            self.warnings.add("reconnection_gap")

    def reconcile(self, summary: dict[str, Any] | None, *, now: float | None = None) -> None:
        if not isinstance(summary, dict):
            return
        now = time.monotonic() if now is None else now
        raw_status = summary.get("session_state")
        state_type = raw_status.get("type") if isinstance(raw_status, dict) else raw_status
        if raw_status:
            if state_type == "busy" and self.activity in {"unknown", "idle"}:
                self.activity = "working"
                self.has_session_activity = True
                if self.inference_started_at is None:
                    created = _timestamp_seconds(summary.get("last_assistant_created"))
                    self.inference_started_at = now - max(0.0, time.time() - created) if created else now
            elif state_type == "idle" and self.activity == "unknown":
                self.activity = "idle"
        finish = _string(summary.get("last_assistant_finish"))
        tokens = summary.get("last_assistant_tokens")
        self.last_completed_message_id = _string(summary.get("last_assistant_id")) or self.last_completed_message_id
        is_complete = bool(summary.get("last_assistant_is_complete"))
        if finish or tokens:
            self.last_completed_finish_reason = finish
            reasoning = tokens.get("reasoning") if isinstance(tokens, dict) else None
            if is_complete and isinstance(reasoning, int) and not isinstance(reasoning, bool) and reasoning >= 0:
                self.last_completed_reasoning_tokens = reasoning
            output = tokens.get("output") if isinstance(tokens, dict) else None
            if is_complete and isinstance(output, int) and not isinstance(output, bool) and output >= 0:
                self.last_completed_output_tokens = output
            self.last_completed_at = _parse_timestamp(summary.get("last_assistant_completed_at")) or now
            if is_complete:
                self.has_completed_content = True
                if state_type in {None, "idle"} and self.activity in {"unknown", "idle", "working"}:
                    self.activity = "completed"
            if is_complete and not self.has_incremental_content:
                self.stream_capability = "completion_only"
        elif self.has_session_activity and self.stream_connected and not self.has_incremental_content:
            self.stream_capability = "activity_only"
            self.warnings.add("telemetry_incomplete")
        self._update_warnings(now)

    def reconcile_history(self, events: list[Any], coverage: str) -> None:
        """Use the existing bounded OpenCode history window for tool outcome diagnostics."""
        self.history_coverage = coverage if coverage in {"complete", "partial", "unavailable"} else "unavailable"
        tool_events = [event for event in events if _event_value(event, "category") == "tool"]
        records: OrderedDict[str, tuple[str, str | None]] = OrderedDict()
        for event in tool_events:
            name = _string(_event_value(event, "tool_name"))
            outcome = _string(_event_value(event, "outcome"))
            if not name:
                continue
            identity = f"{_event_value(event, 'provider_id') or ''}:{_event_value(event, 'part_id') or _event_value(event, 'event_id') or name}"
            records[identity] = (name, outcome)
        records.update(self.live_tool_records)
        names = [name for name, _outcome in records.values()]
        self.successful_file_edits = sum(1 for name, outcome in records.values()
                                         if name.lower() in FILE_WRITE_TOOLS
                                         and outcome in {"succeeded", "success", "completed"})
        self.file_writes_observed = sum(1 for name, _outcome in records.values()
                                        if name.lower() in FILE_WRITE_TOOLS)
        self.tool_names = names[-MAX_TOOL_IDS:]
        self.tool_calls_observed = len(records)
        self.last_tool = _redact_text(names[-1])[:80] if names else self.last_tool
        self.read_only_tools = sum(1 for name in names if name.lower() in READ_ONLY_TOOLS)
        self._update_warnings(time.monotonic())

    def ingest(self, event: NormalizedLiveEvent | None, *, now: float | None = None) -> None:
        if event is None:
            return
        now = time.monotonic() if now is None else now
        if event.raw_event_id:
            if event.raw_event_id in self._seen_sse_ids:
                return
            self._seen_sse_ids[event.raw_event_id] = None
            while len(self._seen_sse_ids) > MAX_TOOL_IDS:
                self._seen_sse_ids.popitem(last=False)
        self.has_session_activity = True
        self.last_event_at = now
        if event.event_type in {"session.status", "server.connected"}:
            self.stream_connected = True
            status = event.tool_status
            if status in {"busy", "running"}:
                self.activity = "working"
            elif status in {"idle", "done"} and self.activity in {"unknown", "working"}:
                self.activity = "idle"
        if event.finish_reason:
            self.last_completed_finish_reason = event.finish_reason
            self.last_completed_reasoning_tokens = event.reasoning_tokens
            self.last_completed_at = now
            self.has_completed_content = True
            if not self.has_incremental_content:
                self.stream_capability = "completion_only"
            if self.activity != "tool":
                self.activity = "completed"

        if event.event_type == "message.part.delta" and event.message_id and event.part_id:
            text = event.delta or ""
            key = (event.message_id, event.part_id)
            current = self.parts.get(key)
            if current is None:
                field = (event.field or "").lower()
                inferred_type = "reasoning" if field in {"reasoning", "reasoningcontent"} else None
                current = _Part(event.message_id, event.part_id, inferred_type)
                self.parts[key] = current
            current.text = _bounded_text(current.text + text)
            self.pending_deltas[key] = _bounded_text(self.pending_deltas.get(key, "") + text)
            self.part_delta_chars[key] = self.part_delta_chars.get(key, 0) + len(text)
            self.parts.move_to_end(key)
            self.part_delta_chars.move_to_end(key)
            self._bound_parts()
            field = (event.field or "").lower()
            category = self._classify_part(key, current.part_type, field=field)
            if category == "reasoning":
                self.activity = "reasoning"
                self.last_reasoning_at = now
                self.reasoning_started_at = self.reasoning_started_at or now
            elif category == "text":
                self.activity = "output"
            else:
                self.activity = "working"
            self.has_incremental_content = True
            self.stream_capability = "streaming"
        elif event.event_type == "message.part.updated" and event.message_id and event.part_id:
            key = (event.message_id, event.part_id)
            part = self.parts.get(key)
            previous_text = part.text if part is not None else ""
            if part is None:
                part = _Part(event.message_id, event.part_id, event.part_type)
                self.parts[key] = part
            elif event.part_type:
                part.part_type = event.part_type
            part.completed = event.tool_status in {"completed", "done"}
            if event.part_text is not None:
                snapshot_text = _bounded_text(event.part_text)
                pending = self.pending_deltas.pop(key, "")
                if part.completed or (pending and snapshot_text.endswith(pending)):
                    part.text = snapshot_text
                elif pending:
                    part.text = _bounded_text(snapshot_text + pending)
                elif len(snapshot_text) >= len(part.text):
                    part.text = snapshot_text
            elif key in self.pending_deltas:
                part.text = self.pending_deltas.pop(key)
            self.parts.move_to_end(key)
            self._bound_parts()
            self._classify_part(key, event.part_type)
            self._observe_tool(event, key)
            if event.part_type in {"reasoning", "thinking"}:
                grew = bool(previous_text and part.text.startswith(previous_text) and len(part.text) > len(previous_text)
                            and event.tool_status not in {"completed", "done"})
                if grew:
                    self.has_incremental_content = True
                    self.stream_capability = "streaming"
                elif not self.has_incremental_content:
                    self.has_completed_content = True
                    self.stream_capability = "completion_only"
                if event.tool_status not in {"completed", "done"}:
                    self.activity = "reasoning"
            elif event.part_type in {"text", "output_text"}:
                grew = bool(previous_text and part.text.startswith(previous_text) and len(part.text) > len(previous_text)
                            and event.tool_status not in {"completed", "done"})
                if grew:
                    self.has_incremental_content = True
                    self.stream_capability = "streaming"
                else:
                    self.has_completed_content = True
                if not self.has_incremental_content:
                    self.stream_capability = "completion_only"
                self.activity = "output"
        elif event.event_type in {"session.idle", "session.completed"}:
            self.activity = "completed" if self.last_completed_finish_reason else "idle"
        self._update_warnings(now)

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        self._update_warnings(now)
        current_reasoning = "".join(part.text for part in self.parts.values()
                                   if part.part_type in {"reasoning", "thinking"})
        result: dict[str, Any] = {
            "schema_version": 1,
            "server": None,
            "stream_connection": "connected" if self.stream_connected else "unavailable",
            "sse_frames_received": self.sse_frames_received,
            "matching_session_events": self.matching_session_events,
            "filtered_events": self.filtered_events,
            "malformed_events": self.malformed_events,
            "oversized_events": self.oversized_events,
            "project_directory": self.project_directory,
            "session_id": self.session_id,
            "activity": self.activity,
            "stream_capability": self.stream_capability,
            "inference_elapsed_seconds": round(max(0.0, now - (self.inference_started_at or self.reasoning_started_at)), 1)
            if self.inference_started_at is not None or self.reasoning_started_at is not None else None,
            "last_event_age_seconds": round(max(0.0, now - self.last_event_at), 1)
            if self.last_event_at is not None else None,
            "last_tool": self.last_tool,
            "tool_calls": max(len(self.tool_ids), self.tool_calls_observed),
            "file_writes_observed": self.file_writes_observed,
            "successful_file_edits": self.successful_file_edits,
            "tool_names": self.tool_names[-MAX_TOOL_IDS:],
            "history_coverage": self.history_coverage,
            "last_completed_message_id": self.last_completed_message_id,
            "last_completed_output_tokens": self.last_completed_output_tokens,
            "output_limits": self.output_limits,
            "reasoning_configuration": self.reasoning_provenance,
            "diagnostics": [],
            "current_reasoning_tokens": None,
            "streamed_reasoning_characters": self.reasoning_chars,
            "streamed_text_characters": self.text_chars,
            "last_completed_reasoning_tokens": self.last_completed_reasoning_tokens,
            "last_completed_finish_reason": self.last_completed_finish_reason,
            "warnings": sorted(self.warnings),
            "coverage": "complete" if self.stream_connected and not self.warnings else "incomplete",
        }
        if self.include_reasoning and current_reasoning:
            result["current_reasoning_text"] = _redact_text(current_reasoning[-MAX_DISPLAY_CHARS:])
        return result

    def _observe_tool(self, event: NormalizedLiveEvent, key: tuple[str, str]) -> None:
        if event.part_type != "tool" or not event.tool_name:
            return
        identity = f"{key[0]}:{key[1]}"
        is_new = identity not in self.tool_ids
        self.tool_ids[identity] = event.tool_name
        self.live_tool_records[identity] = (event.tool_name, event.tool_status)
        while len(self.live_tool_records) > MAX_TOOL_IDS:
            self.live_tool_records.popitem(last=False)
        while len(self.tool_ids) > MAX_TOOL_IDS:
            self.tool_ids.popitem(last=False)
        self.tool_calls_observed = max(self.tool_calls_observed, len(self.tool_ids))
        self.last_tool = _redact_text(event.tool_name)[:80]
        if is_new and event.tool_name.lower() in READ_ONLY_TOOLS:
            self.read_only_tools += 1
            self.tool_names.append(event.tool_name)
            self.tool_names = self.tool_names[-MAX_TOOL_IDS:]
        if event.tool_name.lower() in FILE_WRITE_TOOLS:
            if identity not in self.file_write_ids:
                self.file_write_ids.add(identity)
                self.file_writes_observed += 1
            if event.tool_status in {"completed", "done"} and identity not in self.successful_file_write_ids:
                self.successful_file_write_ids.add(identity)
                self.successful_file_edits += 1
        if event.tool_status in {"running", "pending"}:
            self.activity = "tool"
        elif event.tool_status in {"completed", "done", "error"}:
            self.activity = "tool"
            if event.tool_name.lower() not in READ_ONLY_TOOLS:
                self.tool_names.append(event.tool_name)
                self.tool_names = self.tool_names[-MAX_TOOL_IDS:]

    def _bound_parts(self) -> None:
        while len(self.parts) > MAX_PARTS:
            key, _part = self.parts.popitem(last=False)
            self.part_delta_chars.pop(key, None)
            self.part_char_categories.pop(key, None)
            self.part_classified_chars.pop(key, None)
        while len(self.pending_deltas) > MAX_PARTS:
            self.pending_deltas.popitem(last=False)
        while len(self.part_delta_chars) > MAX_PARTS:
            key, _count = self.part_delta_chars.popitem(last=False)
            self.part_char_categories.pop(key, None)
            self.part_classified_chars.pop(key, None)
        excess = sum(len(part.text) for part in self.parts.values()) - MAX_SESSION_TEXT_CHARS
        for part in self.parts.values():
            if excess <= 0:
                break
            removed = min(excess, len(part.text))
            part.text = part.text[removed:]
            excess -= removed

    def _classify_part(self, key: tuple[str, str], part_type: str | None, *, field: str | None = None) -> str | None:
        desired = "reasoning" if part_type in {"reasoning", "thinking"} or field in {"reasoning", "reasoningcontent"} \
            else "text" if part_type in {"text", "output_text"} else None
        previous = self.part_char_categories.get(key)
        count = self.part_delta_chars.get(key, 0)
        classified = self.part_classified_chars.get(key, 0)
        if desired == previous:
            difference = max(0, count - classified)
            if desired == "reasoning":
                self.reasoning_chars += difference
            elif desired == "text":
                self.text_chars += difference
            self.part_classified_chars[key] = max(classified, count)
            return desired
        if previous == "reasoning":
            self.reasoning_chars = max(0, self.reasoning_chars - classified)
        elif previous == "text":
            self.text_chars = max(0, self.text_chars - classified)
        if desired == "reasoning":
            self.reasoning_chars += count
        elif desired == "text":
            self.text_chars += count
        self.part_char_categories[key] = desired
        self.part_classified_chars[key] = count if desired else 0
        return desired

    def _update_warnings(self, now: float) -> None:
        if self.last_completed_finish_reason == "length" and self.file_writes_observed == 0:
            self.warnings.add("length_finish")
        if self.read_only_tools >= 3 and self.file_writes_observed == 0:
            self.warnings.add("repeated_read_only_tools")
        if self.activity == "reasoning" and self.reasoning_started_at is not None and \
                now - self.reasoning_started_at >= 60 and self.file_writes_observed == 0:
            self.warnings.add("possible_stall")
        if self.last_event_at is not None and now - self.last_event_at >= 30:
            self.warnings.add("no_recent_events")
        elif self.last_event_at is None and self.inference_started_at is not None and now - self.inference_started_at >= 30:
            self.warnings.add("no_recent_events")
        if self.stream_connected and self.has_session_activity and not self.has_incremental_content and \
                self.stream_capability in {"activity_only", "unavailable"}:
            self.warnings.add("telemetry_incomplete")


class OpenCodeSSEClient:
    """Read-only SSE transport with project header, optional Basic auth, and bounded retries."""

    def __init__(
        self,
        base_url: str,
        project_directory: str,
        *,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 15.0,
        max_reconnects: int = 2,
    ):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("OpenCode URL must be an HTTP(S) origin without embedded credentials")
        self.base_url = base_url.rstrip("/")
        self.project_directory = project_directory
        self.username = username
        self.password = password
        self.timeout = min(max(0.1, timeout), 30.0)
        self.max_reconnects = min(max(0, max_reconnects), 3)
        self.connected = False
        self.reconnection_gaps = 0
        self.server_origin = f"{parsed.scheme}://{parsed.netloc}"

    def events(self, observe_seconds: float | None) -> Iterator[SSEEvent]:
        if observe_seconds is not None and not 0 < observe_seconds <= MAX_OBSERVE_SECONDS:
            raise ValueError(f"observe_seconds must be between 0 and {MAX_OBSERVE_SECONDS:g}")
        deadline = time.monotonic() + observe_seconds if observe_seconds is not None else None
        attempts = 0
        while deadline is None or time.monotonic() < deadline:
            remaining = deadline - time.monotonic() if deadline is not None else self.timeout
            headers = {"Accept": "text/event-stream", "Cache-Control": "no-cache"}
            if self.password:
                import base64

                credentials = base64.b64encode(f"{self.username or 'opencode'}:{self.password}".encode()).decode()
                headers["Authorization"] = f"Basic {credentials}"
            event_url = f"{self.base_url}/event?{urlencode({'directory': self.project_directory})}"
            request = Request(event_url, headers=headers, method="GET")
            try:
                with urlopen(request, timeout=max(0.1, min(self.timeout, remaining))) as response:
                    content_type = response.headers.get("Content-Type", "")
                    if "text/event-stream" not in content_type.lower():
                        yield SSEEvent(error="invalid_content_type")
                        return
                    self.connected = True
                    yield SSEEvent(event="__connected__")
                    yield from iter_sse_events(response)
                    if deadline is not None and time.monotonic() >= deadline:
                        return
                    self._gap()
            except HTTPError as exc:
                yield SSEEvent(error=f"http_{exc.code}")
                if exc.code in {401, 403, 404}:
                    return
                self._gap()
            except (URLError, TimeoutError, OSError, ValueError) as exc:
                yield SSEEvent(error="connection_failed")
                self._gap()
                if isinstance(exc, ValueError):
                    return
            if attempts >= self.max_reconnects:
                yield SSEEvent(error="stream_unavailable")
                return
            attempts += 1
            if deadline is None:
                time.sleep(min(0.25 * attempts, 1.0))

    def _gap(self) -> None:
        self.reconnection_gaps += 1


def observe_session(
    client: Any,
    stream: OpenCodeSSEClient,
    *,
    session_id: str,
    project_directory: str,
    observe_seconds: float | None,
    include_reasoning: bool = False,
    requested_variant: str | None = None,
    model_configuration: dict[str, Any] | None = None,
    lmstudio_model: dict[str, Any] | None = None,
    lmstudio_models: list[dict[str, Any]] | None = None,
    request_evidence: dict[str, Any] | None = None,
    on_update: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Reconcile stored summary, observe a bounded event window, then reconcile once more."""
    state = LiveSessionState(session_id, project_directory, include_reasoning=include_reasoning)
    before = client.poll(session_id, project_directory)
    state.reconcile(before)
    for frame in stream.events(observe_seconds):
        if frame.error:
            if frame.error == "oversized_event":
                state.oversized_events += 1
            elif frame.error not in {"connection_failed", "stream_unavailable", "invalid_content_type"}:
                state.malformed_events += 1
            state.note_telemetry_error("connection_gap" if frame.error == "connection_failed" else frame.error)
            continue
        if frame.event == "__connected__":
            state.mark_connected()
            continue
        state.sse_frames_received += 1
        try:
            payload = json.loads(frame.data)
        except (json.JSONDecodeError, TypeError, ValueError):
            state.malformed_events += 1
            state.note_telemetry_error("malformed_event")
            continue
        scope = _event_scope(payload, project_directory, session_id)
        if scope == "filtered":
            state.filtered_events += 1
            continue
        if scope == "matching":
            state.matching_session_events += 1
        event = normalize_opencode_event(payload, project_directory=project_directory,
                                         session_id=session_id,
                                         raw_event_id=frame.event_id or _string(payload.get("id")))
        if event is not None:
            state.ingest(event)
            if on_update:
                on_update(state.snapshot())
    after = client.poll(session_id, project_directory)
    state.reconcile(after)
    history_events = client.events_for_session(session_id) if hasattr(client, "events_for_session") else []
    coverage = after.get("history_coverage", {}) if isinstance(after, dict) else {}
    coverage_status = coverage.get("status", "unavailable") if isinstance(coverage, dict) else "unavailable"
    state.reconcile_history(history_events, coverage_status)
    if model_configuration is None and hasattr(client, "get_json"):
        config_result = client.get_json("/config/providers", project_directory)
        config_payload = getattr(config_result, "data", None)
        info = after.get("session_info", {}) if isinstance(after, dict) else {}
        if isinstance(config_payload, dict) and isinstance(info, dict):
            from .providers import extract_opencode_model_configuration

            model_configuration = extract_opencode_model_configuration(
                config_payload, info.get("model", ""), provider_id=info.get("provider")
            )
    if lmstudio_model is None and isinstance(lmstudio_models, list):
        info = after.get("session_info", {}) if isinstance(after, dict) else {}
        model_id = info.get("model") if isinstance(info, dict) else None
        lmstudio_model = next((model for model in lmstudio_models if isinstance(model, dict)
                               and model.get("id") == model_id), None)
    provenance = build_reasoning_provenance(
        after if isinstance(after, dict) else {}, requested_variant=requested_variant,
        model_configuration=model_configuration, lmstudio_model=lmstudio_model,
        request_evidence=request_evidence,
    )
    state.reasoning_provenance = provenance
    state.output_limits = provenance.get("output_limits", {}).get("value")
    snapshot = state.snapshot()
    snapshot["server"] = stream.server_origin
    snapshot["tool_names"] = state.tool_names[-MAX_TOOL_IDS:]
    snapshot["diagnostics"] = diagnose_live_attempt(
        snapshot, tool_names=state.tool_names, history_coverage=state.history_coverage
    )
    if stream.reconnection_gaps:
        state.note_telemetry_error("connection_gap")
        snapshot["warnings"] = sorted(state.warnings)
        snapshot["coverage"] = "incomplete"
    if not stream.connected:
        state.note_telemetry_error("stream_unavailable")
        snapshot["stream_capability"] = "unavailable"
        snapshot["warnings"] = sorted(state.warnings)
        snapshot["coverage"] = "incomplete"
    snapshot["reconnection_gaps"] = stream.reconnection_gaps
    return snapshot


def build_reasoning_provenance(
    session_summary: dict[str, Any],
    *,
    requested_variant: str | None = None,
    model_configuration: dict[str, Any] | None = None,
    lmstudio_model: dict[str, Any] | None = None,
    request_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep selected settings, provider reports, and outbound request evidence separate."""
    info = session_summary.get("session_info") if isinstance(session_summary.get("session_info"), dict) else {}
    configuration = model_configuration if isinstance(model_configuration, dict) else {}
    options = configuration.get("options") if isinstance(configuration.get("options"), dict) else {}
    if not options and isinstance(info.get("model_options"), dict):
        options = info["model_options"]
    variants = configuration.get("variants") if isinstance(configuration.get("variants"), dict) else {}
    raw_limit = configuration.get("limit") if isinstance(configuration.get("limit"), dict) else {}
    output_limits = {key: value for key, value in raw_limit.items()
                     if key in {"context", "output"} and isinstance(value, (int, float)) and value > 0}
    config_source = "opencode_config_providers" if configuration else "unavailable"
    model_id = _string(info.get("model"))
    provider_id = _string(info.get("provider"))
    session_variant = _string(session_summary.get("last_assistant_variant")) or _string(info.get("variant"))
    actual_tokens = session_summary.get("last_assistant_tokens")
    if not isinstance(actual_tokens, dict):
        actual_tokens = {}
    loaded_lmstudio = lmstudio_model if isinstance(lmstudio_model, dict) and \
        lmstudio_model.get("id") == model_id and lmstudio_model.get("state") == "loaded" else None
    capabilities = loaded_lmstudio.get("reasoning_capabilities") if loaded_lmstudio else None
    request_parameters = correlate_request_evidence(request_evidence, session_summary) \
        if request_evidence is not None else _evidence(None, "unavailable", "unavailable")
    provenance = {
        "requested_variant": _evidence(requested_variant, "diagnostic_cli", "reported")
        if requested_variant else _evidence(None, "unavailable", "unavailable"),
        "session_recorded_variant": _evidence(session_variant, "opencode_session", "reported")
        if session_variant else _evidence(None, "opencode_session", "unavailable"),
        "effective_model": _evidence({"provider": provider_id, "model": model_id}, "opencode_session", "reported")
        if model_id or provider_id else _evidence(None, "opencode_session", "unavailable"),
        "effective_model_options": _evidence(
            {"options": options, "variants": variants}, config_source, "reported"
        ) if configuration or options else _evidence(None, "opencode_config_providers", "unavailable"),
        "output_limits": _evidence(output_limits, config_source, "reported")
        if output_limits else _evidence(None, "opencode_config_providers", "unavailable"),
        "lm_studio_reasoning_capabilities": _evidence(capabilities, "lmstudio_loaded_model_inventory", "reported")
        if isinstance(capabilities, list) and capabilities else _evidence(None, "lmstudio_loaded_model_inventory", "unavailable"),
        "observed_outbound_provider_parameters": request_parameters,
        "actual_inference_usage": _evidence(
            {"reasoning_tokens": actual_tokens.get("reasoning"), "output_tokens": actual_tokens.get("output"),
             "finish_reason": session_summary.get("last_assistant_finish"),
             "message_id": session_summary.get("last_assistant_id")},
            "opencode_completed_message", "reported"
        ) if session_summary.get("last_assistant_is_complete") else _evidence(None, "opencode_completed_message", "unavailable"),
    }
    findings = []
    if session_variant and configuration and session_variant not in variants:
        findings.append({"code": "variant_not_listed_by_effective_model", "classification": "inferred",
                         "evidence": {"session_variant": session_variant, "configured_variants": sorted(variants)}})
    provenance["configuration_findings"] = findings
    return provenance


def correlate_request_evidence(value: Any, session_summary: dict[str, Any]) -> dict[str, Any]:
    """Correlate only allowlisted parameters with an exact session/message/created-time match."""
    unavailable = _evidence(None, "external_request_capture", "unavailable")
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("records"), list):
        return unavailable
    target_session = session_summary.get("session_id")
    target_message = session_summary.get("last_assistant_id")
    target_created = _canonical_timestamp(session_summary.get("last_assistant_created"))
    for record in value["records"][:100]:
        if not isinstance(record, dict):
            continue
        if (record.get("session_id"), record.get("message_id")) != (target_session, target_message):
            continue
        created = _canonical_timestamp(record.get("message_created_at"))
        request_at = _canonical_timestamp(record.get("request_observed_at"))
        if not target_created or created != target_created or not request_at:
            continue
        parameters = record.get("parameters")
        if not isinstance(parameters, dict):
            continue
        safe_parameters = {}
        for key, parameter in parameters.items():
            if key not in REQUEST_PARAMETER_ALLOWLIST or not isinstance(parameter, (str, int, float, bool)):
                continue
            if isinstance(parameter, str) and len(parameter) > 128:
                continue
            if isinstance(parameter, float) and not math.isfinite(parameter):
                continue
            safe_parameters[key] = parameter
        provider = _string(record.get("provider"))
        model = _string(record.get("model"))
        if not provider or not model or not safe_parameters:
            continue
        return _evidence({"provider": provider[:80], "model": model[:160], "parameters": safe_parameters},
                         "external_request_capture", "verified")
    return unavailable


def diagnose_live_attempt(
    snapshot: dict[str, Any],
    *,
    tool_names: list[str] | None = None,
    history_coverage: str = "unavailable",
) -> list[dict[str, Any]]:
    """Produce evidence-backed advisory summaries; never claim a worker is defective or stalled."""
    diagnostics: list[dict[str, Any]] = []
    finish = snapshot.get("last_completed_finish_reason")
    reasoning = snapshot.get("last_completed_reasoning_tokens")
    output = snapshot.get("last_completed_output_tokens")
    config = snapshot.get("reasoning_configuration") or {}
    limits = (config.get("output_limits") or {}).get("value") or snapshot.get("output_limits") or {}
    output_limit = limits.get("output") if isinstance(limits, dict) else None
    if finish == "length":
        diagnostics.append({"code": "length_finish", "classification": "observed",
                            "evidence": {"finish_reason": finish, "reasoning_tokens": reasoning,
                                         "output_tokens": output}})
        if isinstance(reasoning, (int, float)) and isinstance(output_limit, (int, float)) and \
                reasoning >= output_limit and (output is None or output == 0):
            diagnostics.append({"code": "reasoning_exhausted_allowance", "classification": "observed",
                                "evidence": {"reasoning_tokens": reasoning, "output_limit": output_limit,
                                             "output_tokens": output}})
    writes = snapshot.get("successful_file_edits")
    if finish and writes == 0 and history_coverage == "complete":
        diagnostics.append({"code": "no_successful_file_edits", "classification": "observed",
                            "evidence": {"successful_file_edits": 0, "history_coverage": history_coverage}})
    names = [name.lower() for name in (tool_names if tool_names is not None else snapshot.get("tool_names", []))]
    read_count = sum(name in READ_ONLY_TOOLS for name in names)
    if read_count >= 5:
        diagnostics.append({"code": "long_source_discovery", "classification": "observed",
                            "evidence": {"read_only_tool_calls": read_count}})
    if any(names[index:index + 3].count(names[index]) == 3 for index in range(max(0, len(names) - 2))):
        diagnostics.append({"code": "repeated_tool_calls", "classification": "observed",
                            "evidence": {"recent_tool_names": names[-10:]}})
    elapsed = snapshot.get("inference_elapsed_seconds")
    quiet = snapshot.get("last_event_age_seconds")
    if quiet is None and isinstance(elapsed, (int, float)):
        quiet = elapsed
    if isinstance(elapsed, (int, float)) and isinstance(quiet, (int, float)) and elapsed >= 60 and quiet >= 30:
        diagnostics.append({"code": "extended_inference_without_activity", "classification": "inferred",
                            "evidence": {"inference_elapsed_seconds": elapsed, "last_event_age_seconds": quiet}})
    if isinstance(reasoning, (int, float)) and isinstance(output_limit, (int, float)) and \
            reasoning > output_limit:
        diagnostics.append({"code": "configured_limit_behavior_difference", "classification": "inferred",
                            "evidence": {"reasoning_tokens": reasoning, "reported_output_limit": output_limit}})
    for finding in config.get("configuration_findings", []) if isinstance(config, dict) else []:
        if isinstance(finding, dict):
            diagnostics.append(dict(finding))
    return diagnostics


def load_request_evidence(path: str | Path) -> dict[str, Any]:
    """Load a bounded, sanitized evidence envelope; caller output never includes the source path."""
    try:
        payload = Path(path).read_bytes()
        if len(payload) > MAX_REQUEST_EVIDENCE_BYTES:
            raise ValueError("request evidence exceeds the 128 KiB limit")
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request evidence is unreadable or malformed") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("records"), list):
        raise ValueError("request evidence must use schema_version 1 with a records array")
    return value


def _evidence(value: Any, source: str, verification_status: str) -> dict[str, Any]:
    return {"value": value, "source": source, "verification_status": verification_status}


def _event_value(event: Any, key: str) -> Any:
    return event.get(key) if isinstance(event, dict) else getattr(event, key, None)


def _event_scope(value: Any, project_directory: str, session_id: str) -> str:
    if not isinstance(value, dict):
        return "unscoped"
    directory = _string(value.get("directory") or value.get("projectDirectory"))
    payload = value.get("payload", value)
    properties = payload.get("properties", {}) if isinstance(payload, dict) else {}
    part = properties.get("part", {}) if isinstance(properties, dict) else {}
    if not isinstance(properties, dict):
        properties = {}
    if not isinstance(part, dict):
        part = {}
    directory = directory or _string(properties.get("directory") or properties.get("projectDirectory"))
    if directory and _directory_key(directory) != _directory_key(project_directory):
        return "filtered"
    observed = _string(properties.get("sessionID") or part.get("sessionID"))
    if not observed:
        return "unscoped"
    return "matching" if observed == session_id else "filtered"


def _timestamp_seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) / 1000 if value > 10_000_000_000 else float(value)
    canonical = _canonical_timestamp(value)
    if not canonical:
        return None
    return datetime.fromisoformat(canonical.replace("Z", "+00:00")).timestamp()


def _canonical_timestamp(value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        stamp = float(value) / 1000 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        return stamp.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except ValueError:
        return None


def _redact_text(value: str) -> str:
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]" if match.lastindex else "[REDACTED]", value)
    return value


def _bounded_text(value: str) -> str:
    return value[-MAX_PART_CHARS:]


def _directory_key(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _parse_timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
