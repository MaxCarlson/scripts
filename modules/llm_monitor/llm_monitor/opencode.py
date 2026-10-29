"""Read-only, feature-tolerant OpenCode server polling."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .events import NormalizedEvent, events_from_messages


@dataclass
class ApiResult:
    data: Any = None
    error: str | None = None
    status_code: int | None = None


@dataclass(frozen=True)
class HistoryCoverage:
    status: str
    source: str
    pages: int
    limit: int
    window_start: str | None = None
    window_end: str | None = None
    suspected_gap: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class HistoryResult:
    events: list[NormalizedEvent]
    coverage: HistoryCoverage


class OpenCodeClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:4096",
        timeout: float = 3.0,
        message_limit: int = 100,
        *,
        retries: int = 2,
        max_events: int = 5000,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.message_limit = max(1, message_limit)
        self.retries = max(0, retries)
        self.max_events = max(10, max_events)
        self._message_api: str | None = None
        self._events: dict[str, OrderedDict[str, NormalizedEvent]] = {}
        self._message_roles: dict[str, OrderedDict[str, str | None]] = {}
        self._compaction_parts: dict[str, OrderedDict[str, int]] = {}
        self._coverage: dict[str, HistoryCoverage] = {}
        self._session_info: dict[str, dict[str, Any]] = {}
        self._last_status: dict[str, Any] = {}
        self._last_errors: dict[str, dict[str, str]] = {}
        self._last_message_observed: dict[str, str] = {}
        self._cache_evicted: set[str] = set()
        self._started_at = time.monotonic()

    def get_json(self, path: str, directory: str | None = None) -> ApiResult:
        headers = {"Accept": "application/json"}
        if directory:
            headers["x-opencode-directory"] = directory
        for attempt in range(self.retries + 1):
            try:
                request = Request(self.base_url + path, headers=headers, method="GET")
                with urlopen(request, timeout=self.timeout) as response:
                    payload = response.read()
                    status_code = int(getattr(response, "status", 200))
                return ApiResult(json.loads(payload.decode("utf-8")), status_code=status_code)
            except HTTPError as exc:
                if exc.code in {408, 429, 500, 502, 503, 504} and attempt < self.retries:
                    time.sleep(min(0.1 * (2**attempt), 1.0))
                    continue
                return ApiResult(error=f"HTTP {exc.code}", status_code=exc.code)
            except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                if attempt < self.retries:
                    time.sleep(min(0.1 * (2**attempt), 1.0))
                    continue
                return ApiResult(error=f"{type(exc).__name__}: {exc}")
        return ApiResult(error="request failed")

    def sessions(self, directory: str | None = None) -> ApiResult:
        return self.get_json("/session", directory)

    def poll(self, session_id: str, directory: str | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        messages_result, api_name = self._fetch_messages(session_id, directory)
        errors = {}
        if messages_result.error:
            errors["messages"] = messages_result.error
        else:
            messages = messages_result.data
            if isinstance(messages, list):
                self._remember(session_id, messages, now)
                self._coverage[session_id] = _page_coverage(messages, self.message_limit, api_name)
                self._last_message_observed[session_id] = now
        encoded_id = quote(session_id, safe="")
        status = self.get_json("/session/status", directory)
        permission = self.get_json("/permission", directory)
        question = self.get_json("/question", directory)
        session = self.get_json(f"/session/{encoded_id}", directory)
        for key, result in (("status", status), ("permissions", permission), ("questions", question), ("session", session)):
            if result.error:
                errors[key] = result.error
        if isinstance(status.data, dict):
            self._last_status[session_id] = status.data.get(session_id)
        if isinstance(session.data, dict):
            self._session_info[session_id] = _safe_session_info(session.data)
        session_missing = getattr(session, "status_code", None) == 404
        self._last_errors[session_id] = errors
        return self._snapshot(
            session_id,
            now,
            status=self._last_status.get(session_id),
            permissions=permission.data if isinstance(permission.data, list) else None,
            questions=question.data if isinstance(question.data, list) else None,
            session_missing=session_missing,
        )

    def events_for_session(self, session_id: str) -> list[NormalizedEvent]:
        """Return the bounded, privacy-safe in-memory event window for one session."""
        return list(self._events.get(session_id, {}).values())

    def collect_history(self, session_id: str, directory: str | None = None, *, max_pages: int = 100) -> HistoryResult:
        """Collect available message history, following cursor pages when the runtime supports them."""
        messages_by_id: OrderedDict[str, dict[str, Any]] = OrderedDict()
        first, api_name, cursor = self._fetch_message_page(session_id, directory, order="asc")
        if first.error or not isinstance(first.data, list):
            return HistoryResult([], HistoryCoverage("unavailable", api_name, 0, self.message_limit,
                                                     reason=first.error or "malformed message page"))
        pages = 0
        page = first.data
        def add_page(page_messages: list[dict[str, Any]]) -> None:
            for index, message in enumerate(page_messages):
                info = _info(message)
                message_id = _string(info.get("id")) or f"missing-id:{pages}:{index}"
                messages_by_id[message_id] = message

        while True:
            pages += 1
            add_page(page)
            if api_name != "cursor":
                break
            if not cursor:
                coverage = HistoryCoverage("complete", api_name, pages, self.message_limit)
                break
            if pages >= max(1, max_pages):
                coverage = HistoryCoverage("partial", api_name, pages, self.message_limit,
                                           suspected_gap=True, reason="page limit reached")
                break
            page_result = self.get_json(
                f"/api/session/{quote(session_id, safe='')}/message?" +
                urlencode({"limit": self.message_limit, "cursor": cursor}), directory
            )
            envelope = _cursor_envelope(page_result.data)
            if page_result.error or envelope is None:
                coverage = HistoryCoverage("partial", api_name, pages, self.message_limit,
                                           suspected_gap=True, reason=page_result.error or "invalid cursor page")
                break
            page, cursors = envelope
            cursor = _string(cursors.get("next"))
            if cursor is None:
                pages += 1
                add_page(page)
                coverage = HistoryCoverage("complete", api_name, pages, self.message_limit)
                break
        if 'coverage' not in locals():
            is_full = len(first.data) >= self.message_limit
            coverage = HistoryCoverage("partial" if is_full else "complete", api_name, pages, self.message_limit,
                                       suspected_gap=is_full,
                                       reason="legacy endpoint returned a full bounded window" if is_full else None)
        ordered_messages = list(messages_by_id.values())
        result_events = events_from_messages(
            session_id, ordered_messages, observed_at=datetime.now(timezone.utc).isoformat()
        )
        timestamps = [event.timestamp for event in result_events if event.timestamp]
        coverage = HistoryCoverage(coverage.status, coverage.source, coverage.pages, coverage.limit,
                                   min(timestamps) if timestamps else None, max(timestamps) if timestamps else None,
                                   coverage.suspected_gap, coverage.reason)
        return HistoryResult(result_events, coverage)

    def _fetch_messages(self, session_id: str, directory: str | None) -> tuple[ApiResult, str]:
        page, api_name, _ = self._fetch_message_page(session_id, directory)
        return page, api_name

    def _fetch_message_page(
        self, session_id: str, directory: str | None, *, cursor: str | None = None,
        order: str = "desc",
    ) -> tuple[ApiResult, str, str | None]:
        encoded_id = quote(session_id, safe="")
        query = {"limit": self.message_limit, "order": order}
        if cursor:
            query = {"limit": self.message_limit, "cursor": cursor}
        if self._message_api != "legacy":
            v2 = self.get_json(f"/api/session/{encoded_id}/message?{urlencode(query)}", directory)
            envelope = _cursor_envelope(v2.data)
            if envelope is not None and v2.error is None:
                self._message_api = "cursor"
                messages, cursors = envelope
                return ApiResult(data=messages), "cursor", _string(cursors.get("next"))
            if self._message_api == "cursor" and v2.error and v2.status_code not in {404, 405}:
                return v2, "cursor", None
            self._message_api = "legacy"
        legacy_query = urlencode({"limit": self.message_limit})
        legacy = self.get_json(f"/session/{encoded_id}/message?{legacy_query}", directory)
        if legacy.error:
            return legacy, "legacy", None
        if not isinstance(legacy.data, list):
            return ApiResult(error="malformed legacy message response", status_code=legacy.status_code), "legacy", None
        return legacy, "legacy", None

    def _remember(self, session_id: str, messages: list[dict[str, Any]], observed_at: str) -> None:
        events = self._events.setdefault(session_id, OrderedDict())
        message_roles = self._message_roles.setdefault(session_id, OrderedDict())
        compactions = self._compaction_parts.setdefault(session_id, OrderedDict())
        normalized = events_from_messages(session_id, messages, observed_at=observed_at)
        for event in normalized:
            if event.category == "message" and event.provider_id:
                message_roles[event.provider_id] = event.subtype
                message_roles.move_to_end(event.provider_id)
            events[event.event_id] = event
            events.move_to_end(event.event_id)
        for index, message in enumerate(messages):
            info = _info(message)
            message_id = _string(info.get("id")) or f"unidentified-{index}"
            parts = message.get("parts") if isinstance(message.get("parts"), list) else []
            raw_count = sum(1 for part in parts if isinstance(part, dict) and part.get("type") == "compaction")
            compactions[message_id] = raw_count
            compactions.move_to_end(message_id)
        if len(events) > self.max_events:
            self._cache_evicted.add(session_id)
        while len(events) > self.max_events:
            events.popitem(last=False)
        while len(message_roles) > self.max_events:
            message_roles.popitem(last=False)
        while len(compactions) > self.max_events:
            compactions.popitem(last=False)

    def _snapshot(
        self,
        session_id: str,
        polled_at: str,
        *,
        status: Any,
        permissions: list[dict[str, Any]] | None,
        questions: list[dict[str, Any]] | None,
        session_missing: bool = False,
    ) -> dict[str, Any]:
        events = list(self._events.get(session_id, {}).values())
        messages = self._message_roles.get(session_id, {})
        assistant_events = [event for event in events if event.category == "inference"]
        last = assistant_events[-1] if assistant_events else None
        completed = next((event for event in reversed(assistant_events) if event.outcome == "completed"), None)
        coverage = self._coverage.get(session_id, HistoryCoverage("unavailable", self._message_api or "unknown", 0,
                                                                   self.message_limit, reason="no messages collected"))
        if session_id in self._cache_evicted:
            coverage = HistoryCoverage("partial", coverage.source, coverage.pages, coverage.limit,
                                       coverage.window_start, coverage.window_end, True,
                                       "in-memory event cache evicted older observations")
        session_permissions = [p for p in permissions or [] if p.get("sessionID") == session_id]
        session_questions = [q for q in questions or [] if q.get("sessionID") == session_id]
        compactions = [event for event in events if event.category == "compaction"]
        tool_events = [event for event in events if event.category == "tool"]
        errors = self._last_errors.get(session_id, {})
        message_count = len(messages) if messages else None
        assistant_count = sum(1 for role in messages.values() if role == "assistant") if messages else None
        return {
            "schema_version": 2,
            "session_id": session_id,
            "polled_at": polled_at,
            "timestamp": polled_at,
            "elapsed_sec": round(time.monotonic() - self._started_at, 2),
            "elapsed_scope": "monitor_observation",
            "session_state": status,
            "normalized_state": "unknown" if session_missing else _normalized_state(
                status, last, tool_events, compactions, session_permissions, session_questions
            ),
            "session_exists": False if session_missing else True if self._session_info.get(session_id) else None,
            "total_messages": message_count,
            "assistant_messages": assistant_count,
            "message_counts_scope": "limited_history" if coverage.status != "complete" else "available",
            "history_coverage": coverage.__dict__,
            "compaction_count": len({event.provider_id or event.event_id for event in compactions}),
            "compaction_parts": sum(self._compaction_parts.get(session_id, {}).values()),
            "pending_permissions": len(session_permissions) if permissions is not None else None,
            "pending_questions": len(session_questions) if questions is not None else None,
            "last_assistant_id": last.provider_id if last else None,
            "last_assistant_agent": last.agent if last else None,
            "last_assistant_model": last.model if last else None,
            "last_assistant_finish": last.finish_reason if last else None,
            "last_assistant_completed": last.provider_completed_at if last and last.outcome == "completed" else None,
            "last_assistant_tokens": last.tokens if last else None,
            "latest_completed_inference": completed.to_dict() if completed else None,
            "token_scope": "latest_assistant_message",
            "last_assistant_is_complete": bool(last and last.outcome == "completed"),
            "latest_tool": tool_events[-1].to_dict() if tool_events else None,
            "session_info": self._session_info.get(session_id),
            "errors": errors,
            "stale": bool(errors),
            "last_message_observed_at": self._last_message_observed.get(session_id),
        }


def _cursor_envelope(value: Any) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        return None
    cursor = value.get("cursor")
    if not isinstance(cursor, dict):
        return None
    messages = [item for item in value["data"] if isinstance(item, dict)]
    return messages, cursor


def _page_coverage(messages: list[dict[str, Any]], limit: int, source: str) -> HistoryCoverage:
    if len(messages) >= limit:
        return HistoryCoverage("partial", source, 1, limit, suspected_gap=True,
                               reason="bounded page may omit older or intervening messages")
    return HistoryCoverage("complete", source, 1, limit)


def _safe_session_info(session: dict[str, Any]) -> dict[str, Any]:
    model = session.get("model") if isinstance(session.get("model"), dict) else {}
    time_info = session.get("time") if isinstance(session.get("time"), dict) else {}
    return {
        "id": _string(session.get("id")),
        "title": _string(session.get("title")),
        "directory": _string(session.get("directory")),
        "agent": _string(session.get("agent")),
        "model": _string(model.get("id")),
        "provider": _string(model.get("providerID")),
        "created": time_info.get("created") if isinstance(time_info.get("created"), (int, float)) else None,
        "updated": time_info.get("updated") if isinstance(time_info.get("updated"), (int, float)) else None,
        "summary_files": (
            session.get("summary", {}).get("files")
            if isinstance(session.get("summary"), dict)
            and isinstance(session.get("summary", {}).get("files"), (int, float))
            else None
        ),
    }


def _normalized_state(
    status: Any,
    last_inference: NormalizedEvent | None,
    tool_events: list[NormalizedEvent],
    compaction_events: list[NormalizedEvent],
    permissions: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> str:
    if permissions:
        return "waiting_permission"
    if questions:
        return "waiting_question"
    raw = status.get("type") or status.get("state") if isinstance(status, dict) else status
    if any(event.outcome in {"running", "started", "in_progress"} for event in compaction_events):
        return "compacting"
    if isinstance(raw, str) and raw in {"busy", "running", "retry"}:
        if last_inference and last_inference.outcome == "running":
            return "inference_running"
        if tool_events and tool_events[-1].outcome == "running":
            return "tool_running"
        return "unknown"
    if raw == "idle" or raw is None:
        return "idle"
    if isinstance(raw, str) and raw in {"completed", "finished", "done"}:
        return "completed"
    if isinstance(raw, str) and raw in {"error", "failed"}:
        return "unknown"
    return "unknown"


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def summarize_session(
    session_id: str,
    messages: list[dict[str, Any]],
    statuses: dict[str, Any],
    permissions: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    *,
    polled_at: str | None = None,
    errors: dict[str, str] | None = None,
    message_limit: int | None = None,
) -> dict[str, Any]:
    assistant = [message for message in messages if _info(message).get("role") == "assistant"]
    last_info = _info(assistant[-1]) if assistant else {}
    session_permissions = [item for item in permissions if item.get("sessionID") == session_id]
    session_questions = [item for item in questions if item.get("sessionID") == session_id]
    compact_ids: set[str] = set()
    anonymous_compactions = 0
    for message in messages:
        for part in message.get("parts", []) if isinstance(message.get("parts"), list) else []:
            if isinstance(part, dict) and part.get("type") == "compaction":
                key = part.get("id") or part.get("messageID") or _info(message).get("id")
                if key:
                    compact_ids.add(str(key))
                else:
                    anonymous_compactions += 1

    return {
        "session_id": session_id,
        "polled_at": polled_at or datetime.now(timezone.utc).isoformat(),
        "timestamp": polled_at or datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": None,
        "session_state": statuses.get(session_id),
        "total_messages": len(messages),
        "assistant_messages": len(assistant),
        "message_counts_scope": "limited_history" if message_limit and len(messages) >= message_limit else "available",
        "compaction_count": len(compact_ids) + anonymous_compactions,
        "compaction_parts": sum(
            1
            for message in messages
            for part in message.get("parts", []) if isinstance(message.get("parts"), list)
            if isinstance(part, dict) and part.get("type") == "compaction"
        ),
        "pending_permissions": len(session_permissions),
        "pending_questions": len(session_questions),
        "last_assistant_id": last_info.get("id"),
        "last_assistant_agent": last_info.get("agent"),
        "last_assistant_model": last_info.get("modelID") or last_info.get("model", {}).get("modelID")
        if isinstance(last_info.get("model"), dict) else last_info.get("modelID"),
        "last_assistant_finish": last_info.get("finish"),
        "last_assistant_completed": last_info.get("time", {}).get("completed")
        if isinstance(last_info.get("time"), dict) else None,
        "last_assistant_tokens": last_info.get("tokens"),
        "token_scope": "latest_assistant_message",
        "last_assistant_is_complete": bool(
            (last_info.get("time") or {}).get("completed")
            if isinstance(last_info.get("time"), dict)
            else last_info.get("finish")
        ),
        "errors": errors or {},
    }


def _info(message: dict[str, Any]) -> dict[str, Any]:
    info = message.get("info")
    return info if isinstance(info, dict) else message
