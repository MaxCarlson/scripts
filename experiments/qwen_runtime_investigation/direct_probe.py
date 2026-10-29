"""Run one sanitized direct LM Studio reasoning-effort probe.

The prompt and generated text are intentionally never written to disk. Each
invocation sends one deterministic request to the exact loaded Qwen GGUF.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid


MODEL_KEY = "qwen38_23GB"
EXPECTED_MODEL_ID = "qwen38-27b-q4km"
PROMPT = "What is 19 multiplied by 23? Reply with only the integer."
EXPECTED_ANSWER = "437"


def run_probe(*, effort: str | None, max_tokens: int, output: Path,
              base_url: str, stream: bool = False) -> dict:
    endpoint = base_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": MODEL_KEY,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "seed": 17,
        "stream": stream,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    if effort is not None:
        payload["reasoning_effort"] = effort
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    record = {
        "schema_version": 1,
        "attempt_id": str(uuid.uuid4()),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model_key": MODEL_KEY,
        "expected_runtime_model_id": EXPECTED_MODEL_ID,
        "endpoint_path": "/v1/chat/completions",
        "request": {
            "model": MODEL_KEY,
            "max_tokens": max_tokens,
            "temperature": 0,
            "seed": 17,
            "stream": stream,
            "reasoning_effort": effort,
            "reasoning_effort_present": effort is not None,
            "root_field_names": sorted(payload),
            "message_count": len(payload["messages"]),
            "message_roles": [item["role"] for item in payload["messages"]],
        },
        "response": {},
    }
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            record["response"]["http_status"] = response.status
            if stream:
                _read_stream(response, record, started)
                data = None
            else:
                data = json.loads(response.read())
        if not stream:
            choices = data.get("choices") or []
            choice = choices[0] if choices else {}
            message = choice.get("message") or {}
            content = message.get("content")
            reasoning = message.get("reasoning_content")
            if isinstance(content, list):
                content_text = "".join(str(part.get("text", "")) for part in content
                                        if isinstance(part, dict))
            else:
                content_text = content if isinstance(content, str) else ""
            usage = data.get("usage") or {}
            details = usage.get("completion_tokens_details") or {}
            record["response"].update({
                "provider_model_id": data.get("model"),
                "finish_reason": choice.get("finish_reason"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": details.get("reasoning_tokens"),
                "reasoning_content_present": bool(reasoning),
                "reasoning_content_char_count": len(reasoning) if isinstance(reasoning, str) else None,
                "ordinary_content_present": bool(content_text),
                "ordinary_content_char_count": len(content_text),
                "answer_correct": content_text.strip().strip("` ") == EXPECTED_ANSWER,
                "tool_call_count": len(message.get("tool_calls") or []),
            })
    except urllib.error.HTTPError as error:
        record["response"].update({
            "http_status": error.code,
            "error_type": "http_error",
        })
        # Do not persist provider error bodies; they can include request data.
        error.close()
    except Exception as error:  # Capture only type to avoid leaking URL/body details.
        record["response"].update({"error_type": type(error).__name__})
    record["ended_at"] = datetime.now(timezone.utc).isoformat()
    record["wall_seconds"] = round(time.monotonic() - started, 3)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _read_stream(response, record: dict, started: float) -> None:
    """Count safe SSE delivery facts without retaining event payload text."""
    response_data = record["response"]
    response_data.update({"stream_event_count": 0, "reasoning_delta_count": 0,
                          "reasoning_char_count": 0, "ordinary_delta_count": 0,
                          "ordinary_char_count": 0, "tool_call_delta_count": 0})
    answer_fragments: list[str] = []
    first_event = None
    finished_at = None
    done_marker_seen = False
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        data_text = line[5:].strip()
        if data_text == "[DONE]":
            done_marker_seen = True
            continue
        try:
            event = json.loads(data_text)
        except json.JSONDecodeError:
            response_data["malformed_event_count"] = response_data.get("malformed_event_count", 0) + 1
            continue
        if first_event is None:
            first_event = time.monotonic()
        response_data["stream_event_count"] += 1
        response_data.setdefault("provider_model_id", event.get("model"))
        choices = event.get("choices") or []
        if choices:
            choice = choices[0]
            delta = choice.get("delta") or {}
            reasoning = delta.get("reasoning_content")
            content = delta.get("content")
            if isinstance(reasoning, str) and reasoning:
                response_data["reasoning_delta_count"] += 1
                response_data["reasoning_char_count"] += len(reasoning)
            if isinstance(content, str) and content:
                response_data["ordinary_delta_count"] += 1
                response_data["ordinary_char_count"] += len(content)
                answer_fragments.append(content)
            response_data["tool_call_delta_count"] += len(delta.get("tool_calls") or [])
            if choice.get("finish_reason") is not None:
                response_data["finish_reason"] = choice.get("finish_reason")
        usage = event.get("usage")
        if isinstance(usage, dict):
            details = usage.get("completion_tokens_details") or {}
            response_data.update({
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": details.get("reasoning_tokens"),
            })
        finished_at = time.monotonic()
    response_data.update({
        "first_event_seconds": round(first_event - started, 3) if first_event is not None else None,
        "reasoning_content_present": response_data["reasoning_char_count"] > 0,
        "ordinary_content_present": response_data["ordinary_char_count"] > 0,
        "answer_correct": "".join(answer_fragments).strip().strip("` ") == EXPECTED_ANSWER,
        "tool_call_count": response_data["tool_call_delta_count"],
        "stream_completed": done_marker_seen,
        "last_event_seconds": round(finished_at - started, 3) if finished_at is not None else None,
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--effort", choices=("low", "medium", "xhigh", "none", "off", "on"))
    parser.add_argument("--max-tokens", type=int, choices=(8192, 16384), default=8192)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_probe(effort=args.effort, max_tokens=args.max_tokens,
                       output=args.output, base_url=args.base_url, stream=args.stream)
    print(json.dumps(result, sort_keys=True))
    return 0 if "error_type" not in result["response"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
