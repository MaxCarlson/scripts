"""Read-only, feature-tolerant OpenCode server polling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


@dataclass
class ApiResult:
    data: Any = None
    error: str | None = None


class OpenCodeClient:
    def __init__(self, base_url: str = "http://127.0.0.1:4096", timeout: float = 3.0, message_limit: int = 100):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.message_limit = max(1, message_limit)
        self._message_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self._history_limited: set[str] = set()
        self._started_at = time.monotonic()

    def get_json(self, path: str, directory: str | None = None) -> ApiResult:
        headers = {"Accept": "application/json"}
        if directory:
            headers["x-opencode-directory"] = directory
        try:
            request = Request(self.base_url + path, headers=headers, method="GET")
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
            return ApiResult(json.loads(payload.decode("utf-8")))
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return ApiResult(error=f"{type(exc).__name__}: {exc}")

    def sessions(self, directory: str | None = None) -> ApiResult:
        return self.get_json("/session", directory)

    def poll(self, session_id: str, directory: str | None = None) -> dict[str, Any]:
        encoded_id = quote(session_id, safe="")
        query = "?" + urlencode({"limit": self.message_limit})
        responses = {
            "status": self.get_json("/session/status", directory),
            "messages": self.get_json(f"/session/{encoded_id}/message{query}", directory),
            "permissions": self.get_json("/permission", directory),
            "questions": self.get_json("/question", directory),
        }
        errors = {key: value.error for key, value in responses.items() if value.error}
        data = {key: value.data for key, value in responses.items()}
        incoming = data["messages"] if isinstance(data["messages"], list) else []
        if len(incoming) >= self.message_limit:
            self._history_limited.add(session_id)
        cache = self._message_cache.setdefault(session_id, {})
        for index, message in enumerate(incoming):
            if not isinstance(message, dict):
                continue
            info = _info(message)
            message_id = info.get("id") or f"anonymous-{index}"
            cache[str(message_id)] = message
        merged = list(cache.values())
        summary = summarize_session(
            session_id,
            merged,
            data["status"] if isinstance(data["status"], dict) else {},
            data["permissions"] if isinstance(data["permissions"], list) else [],
            data["questions"] if isinstance(data["questions"], list) else [],
            polled_at=datetime.now(timezone.utc).isoformat(),
            errors=errors,
            message_limit=self.message_limit if session_id in self._history_limited else None,
        )
        summary["elapsed_sec"] = round(time.monotonic() - self._started_at, 2)
        summary["elapsed_scope"] = "monitor_observation"
        return summary


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
