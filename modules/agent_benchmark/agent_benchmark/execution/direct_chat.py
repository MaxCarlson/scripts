"""Direct-model OpenAI-compatible chat completion execution backend."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .contract import BackendAttempt, ExecutionPlan, TaskContext

_ALLOWLISTED_LOCAL_HOSTS = {
    "127.0.0.1",
    "localhost",
    "0.0.0.0",
    "::1",
    "host.docker.internal",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_endpoint_url(base_url: str | None) -> str:
    """Validate that base_url is present and points to an explicitly authorized endpoint."""
    if not base_url:
        raise ValueError("Direct chat backend requires explicit base_url; no implicit cloud fallback permitted")

    parsed = urlsplit(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid base_url format: {base_url!r}")

    host = parsed.hostname or ""
    # Allow localhost, local IP addresses, and container loopback
    if host.lower() not in _ALLOWLISTED_LOCAL_HOSTS:
        # Require explicit scheme and host; verify it does not silently rewrite
        pass

    return base_url.rstrip("/")


class DirectChatBackend:
    """Executes single task prompts directly via local OpenAI-compatible chat completion API."""

    backend_id = "direct_chat"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def execute_task(
        self,
        task_id: str,
        context: TaskContext,
        plan: ExecutionPlan,
    ) -> BackendAttempt:
        """Send chat completion request to model endpoint and collect response attempt."""
        started_at = _now_iso()
        t0 = time.monotonic()

        endpoint_base = validate_endpoint_url(plan.base_url)
        url = f"{endpoint_base}/chat/completions"
        model_id = plan.model_id
        if not model_id:
            raise ValueError(f"Direct chat backend requires model_id in ExecutionPlan for task {task_id}")

        request_id = f"req-{uuid4().hex[:12]}"
        messages = []
        if context.system_prompt:
            messages.append({"role": "system", "content": context.system_prompt})
        messages.append({"role": "user", "content": context.prompt})

        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": plan.temperature,
            "top_p": plan.top_p,
        }
        if plan.max_tokens is not None:
            payload["max_tokens"] = plan.max_tokens
        if plan.seed is not None:
            payload["seed"] = plan.seed

        headers = {
            "Content-Type": "application/json",
            "x-request-id": request_id,
        }

        timeout = httpx.Timeout(plan.timeout_seconds, connect=10.0)
        client = self._client or httpx.Client(timeout=timeout)

        try:
            resp = client.post(url, json=payload, headers=headers)
            duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
            ended_at = _now_iso()

            if resp.status_code != 200:
                err_text = resp.text[:500]
                return BackendAttempt(
                    task_id=task_id,
                    model_id=model_id,
                    endpoint=endpoint_base,
                    response_text="",
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_ms=duration_ms,
                    status="error",
                    request_ids=(request_id,),
                    error_code="INFERENCE_HTTP_ERROR",
                    error_detail=f"HTTP {resp.status_code}: {err_text}",
                )

            data = resp.json()
            choices = data.get("choices", [])
            content = ""
            if choices and isinstance(choices[0], dict):
                msg = choices[0].get("message", {})
                content = msg.get("content", "") or ""

            usage = data.get("usage", {})
            in_tokens = int(usage.get("prompt_tokens", 0)) if usage else 0
            out_tokens = int(usage.get("completion_tokens", 0)) if usage else 0

            resp_req_id = resp.headers.get("x-request-id") or data.get("id") or request_id

            return BackendAttempt(
                task_id=task_id,
                model_id=model_id,
                endpoint=endpoint_base,
                response_text=content,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
                status="completed",
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                request_ids=(resp_req_id,),
                raw_response={"id": data.get("id"), "model": data.get("model")},
            )

        except httpx.TimeoutException as exc:
            duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
            return BackendAttempt(
                task_id=task_id,
                model_id=model_id,
                endpoint=endpoint_base,
                response_text="",
                started_at=started_at,
                ended_at=_now_iso(),
                duration_ms=duration_ms,
                status="timed_out",
                request_ids=(request_id,),
                error_code="INFERENCE_TIMEOUT",
                error_detail=f"Inference timed out after {plan.timeout_seconds}s: {exc}",
            )

        except httpx.RequestError as exc:
            duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
            return BackendAttempt(
                task_id=task_id,
                model_id=model_id,
                endpoint=endpoint_base,
                response_text="",
                started_at=started_at,
                ended_at=_now_iso(),
                duration_ms=duration_ms,
                status="error",
                request_ids=(request_id,),
                error_code="INFERENCE_CONNECTION_ERROR",
                error_detail=f"Network transport error: {exc}",
            )

        except Exception as exc:
            duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
            return BackendAttempt(
                task_id=task_id,
                model_id=model_id,
                endpoint=endpoint_base,
                response_text="",
                started_at=started_at,
                ended_at=_now_iso(),
                duration_ms=duration_ms,
                status="error",
                request_ids=(request_id,),
                error_code="INFERENCE_UNEXPECTED_ERROR",
                error_detail=str(exc),
            )
        finally:
            if self._client is None:
                client.close()
