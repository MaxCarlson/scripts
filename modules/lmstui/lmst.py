#!/usr/bin/env python3
"""
lmst.py - LM Studio OpenAI-compatible client + CLI with streaming support.

Works against LM Studio's OpenAI-compatible server (default http://localhost:1234/v1).

Examples:
    # List models
    python lmst.py models

    # Stream a chat response
    python lmst.py chat -m <MODEL_ID> -p "Hello there" --stream

    # Non-stream chat (prints once)
    python lmst.py chat -m <MODEL_ID> -p "Summarize KV cache" --no-stream

    # Use /v1/responses streaming (if enabled in your LM Studio version)
    python lmst.py responses -m <MODEL_ID> -p "Write a limerick about GPUs" --stream

    # Remote desktop usage via SSH tunnel (run this on your laptop/phone):
    #   ssh -L 1234:127.0.0.1:1234 user@desktop
    # Then run:
    #   python lmst.py chat -m <MODEL_ID> -p "hi" --stream
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple

import httpx


@dataclass(frozen=True)
class ClientConfig:
    base_url: str
    timeout_seconds: float
    api_key: Optional[str]
    verbose: bool


class LMStudioClient:
    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._base_v1 = _normalize_base_v1(config.base_url)

        headers: Dict[str, str] = {
            "Accept": "application/json",
        }
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        self._client = httpx.Client(
            base_url=self._base_v1,
            headers=headers,
            timeout=httpx.Timeout(config.timeout_seconds),
        )

    def close(self) -> None:
        self._client.close()

    def list_models(self) -> Dict[str, Any]:
        return self._request_json("GET", "/models", None)

    def chat_completions(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: Optional[int],
        stream: bool,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any] | Generator[Dict[str, Any], None, None]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)

        if stream:
            return self._request_sse("POST", "/chat/completions", payload)
        return self._request_json("POST", "/chat/completions", payload)

    def responses(
        self,
        model: str,
        input_text: str,
        temperature: float,
        max_output_tokens: Optional[int],
        stream: bool,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any] | Generator[Dict[str, Any], None, None]:
        payload: Dict[str, Any] = {
            "model": model,
            "input": input_text,
            "temperature": temperature,
            "stream": stream,
        }
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        if extra:
            payload.update(extra)

        if stream:
            return self._request_sse("POST", "/responses", payload)
        return self._request_json("POST", "/responses", payload)

    def _request_json(self, method: str, path: str, json_body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        url = path
        if self._config.verbose:
            _eprint(f"[lmst] {method} {self._base_v1}{path}")
            if json_body is not None:
                _eprint(f"[lmst] body: {json.dumps(json_body, ensure_ascii=False)}")

        resp = self._client.request(method, url, json=json_body)
        if self._config.verbose:
            _eprint(f"[lmst] status: {resp.status_code}")

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(_format_http_error(e, resp)) from e

        try:
            return resp.json()
        except Exception as e:
            raise RuntimeError(f"Failed to parse JSON from {method} {path}: {e}") from e

    def _request_sse(self, method: str, path: str, json_body: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
        url = path
        if self._config.verbose:
            _eprint(f"[lmst] {method} {self._base_v1}{path} (stream)")
            _eprint(f"[lmst] body: {json.dumps(json_body, ensure_ascii=False)}")

        with self._client.stream(method, url, json=json_body) as resp:
            if self._config.verbose:
                _eprint(f"[lmst] status: {resp.status_code}")

            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                body_preview = ""
                try:
                    body_preview = resp.read().decode("utf-8", errors="replace")
                except Exception:
                    body_preview = "<unable to read body>"
                raise RuntimeError(_format_http_error(e, resp, body_preview=body_preview)) from e

            yield from _iter_sse_json(resp.iter_lines())


def _normalize_base_v1(base_url: str) -> str:
    """
    Accepts:
      - http://host:1234
      - http://host:1234/
      - http://host:1234/v1
      - http://host:1234/v1/
    Returns: http://host:1234/v1
    """
    b = base_url.strip().rstrip("/")
    if b.endswith("/v1"):
        return b
    return f"{b}/v1"


def _iter_sse_json(lines: Iterable[str]) -> Generator[Dict[str, Any], None, None]:
    """
    Minimal SSE parser:
      - Collects 'data:' lines
      - Blank line ends an event
      - If data is '[DONE]' => stop
      - Otherwise parse data as JSON and yield dict
    """
    data_lines: List[str] = []

    def flush_event() -> Optional[Dict[str, Any]]:
        nonlocal data_lines
        if not data_lines:
            return None
        data = "\n".join(data_lines).strip()
        data_lines = []
        if not data:
            return None
        if data == "[DONE]":
            raise StopIteration
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            # Some servers may send non-JSON; ignore quietly.
            return None

    for raw in lines:
        line = raw.rstrip("\r")
        if not line:
            try:
                evt = flush_event()
            except StopIteration:
                return
            if evt is not None:
                yield evt
            continue

        if line.startswith(":"):
            # Comment/keepalive
            continue

        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
            continue

        # Ignore other SSE fields: event:, id:, retry:, etc.

    # Flush any trailing event if stream ends without a blank line
    try:
        evt = flush_event()
    except StopIteration:
        return
    if evt is not None:
        yield evt


def _extract_text_from_chat_json(obj: Dict[str, Any]) -> str:
    """
    Non-stream chat completions:
      { choices: [ { message: { content: "..." } } ] }
    """
    try:
        choices = obj.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content")
            if isinstance(content, str):
                return content
    except Exception:
        pass
    return ""


def _extract_delta_text_from_chat_event(evt: Dict[str, Any]) -> str:
    """
    Stream chat event:
      { choices: [ { delta: { content: "..." } } ] }
    Sometimes LM Studio may include other fields; we only pull text deltas.
    """
    try:
        choices = evt.get("choices", [])
        if not choices:
            return ""
        delta = choices[0].get("delta", {})
        content = delta.get("content")
        if isinstance(content, str):
            return content
    except Exception:
        pass
    return ""


def _extract_text_from_responses_json(obj: Dict[str, Any]) -> str:
    """
    Responses API can vary by server version; try a few common layouts.
    """
    # Common: output -> [{ content -> [{ type:"output_text", text:"..." }] }]
    try:
        output = obj.get("output")
        if isinstance(output, list) and output:
            parts = output[0].get("content")
            if isinstance(parts, list):
                texts: List[str] = []
                for p in parts:
                    if isinstance(p, dict) and isinstance(p.get("text"), str):
                        texts.append(p["text"])
                if texts:
                    return "".join(texts)
    except Exception:
        pass

    # Sometimes: "text" at top-level
    txt = obj.get("text")
    if isinstance(txt, str):
        return txt

    return ""


def _extract_delta_text_from_responses_event(evt: Dict[str, Any]) -> str:
    """
    Streaming Responses API events can arrive as different types.
    We attempt to pull any obvious text fields.
    """
    # Some servers emit: { type: "...", delta: "..."} or { type:"response.output_text.delta", delta:"..." }
    delta = evt.get("delta")
    if isinstance(delta, str):
        return delta

    # Or nested: { output: [ { content: [ { text: "..." } ] } ] } (less common in delta form)
    try:
        output = evt.get("output")
        if isinstance(output, list) and output:
            parts = output[0].get("content")
            if isinstance(parts, list) and parts:
                p0 = parts[0]
                if isinstance(p0, dict) and isinstance(p0.get("text"), str):
                    return p0["text"]
    except Exception:
        pass

    return ""


def _format_http_error(e: httpx.HTTPStatusError, resp: httpx.Response, body_preview: str = "") -> str:
    try:
        text = resp.text
    except Exception:
        text = ""
    preview = body_preview or text
    preview = preview.strip()
    if len(preview) > 2000:
        preview = preview[:2000] + "…"
    return f"HTTP error: {e} | status={resp.status_code} | body={preview}"


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _read_stdin_text() -> str:
    if sys.stdin.isatty():
        return ""
    return sys.stdin.read()


def _write_stream_text(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _parse_kv_pairs(pairs: List[str]) -> Dict[str, Any]:
    """
    Parse simple key=value pairs (best-effort JSON for values).
    Examples:
      --extra top_p=0.9 presence_penalty=0.2
      --extra response_format={"type":"json_object"}
    """
    out: Dict[str, Any] = {}
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"Invalid extra '{item}'. Expected key=value.")
        k, v = item.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            raise ValueError(f"Invalid extra '{item}'. Empty key.")
        # Try JSON decode for values, else treat as string.
        try:
            out[k] = json.loads(v)
        except Exception:
            out[k] = v
    return out


def _cmd_models(client: LMStudioClient, args: argparse.Namespace) -> int:
    data = client.list_models()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    models = data.get("data", [])
    if not isinstance(models, list):
        print("No models found.")
        return 0

    for m in models:
        if isinstance(m, dict):
            mid = m.get("id")
            if isinstance(mid, str):
                print(mid)
    return 0


def _cmd_chat(client: LMStudioClient, args: argparse.Namespace) -> int:
    prompt = args.prompt or _read_stdin_text()
    if not prompt:
        raise SystemExit("No prompt provided. Use -p/--prompt or pipe text via stdin.")

    messages: List[Dict[str, str]] = []
    if args.system_prompt:
        messages.append({"role": "system", "content": args.system_prompt})
    messages.append({"role": "user", "content": prompt})

    extra = _parse_kv_pairs(args.extra) if args.extra else None

    if args.stream:
        gen = client.chat_completions(
            model=args.model,
            messages=messages,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            stream=True,
            extra=extra,
        )
        assert not isinstance(gen, dict)

        if args.raw_events:
            for evt in gen:
                print(json.dumps(evt, ensure_ascii=False))
            return 0

        text_out: List[str] = []
        for evt in gen:
            delta = _extract_delta_text_from_chat_event(evt)
            if delta:
                text_out.append(delta)
                _write_stream_text(delta)

        if args.output_file:
            _write_text_file(args.output_file, "".join(text_out))
        if args.newline:
            print()
        return 0

    obj = client.chat_completions(
        model=args.model,
        messages=messages,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        stream=False,
        extra=extra,
    )
    assert isinstance(obj, dict)

    if args.json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return 0

    text = _extract_text_from_chat_json(obj)
    print(text)
    if args.output_file:
        _write_text_file(args.output_file, text)
    return 0


def _cmd_responses(client: LMStudioClient, args: argparse.Namespace) -> int:
    prompt = args.prompt or _read_stdin_text()
    if not prompt:
        raise SystemExit("No prompt provided. Use -p/--prompt or pipe text via stdin.")

    extra = _parse_kv_pairs(args.extra) if args.extra else None

    if args.stream:
        gen = client.responses(
            model=args.model,
            input_text=prompt,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
            stream=True,
            extra=extra,
        )
        assert not isinstance(gen, dict)

        if args.raw_events:
            for evt in gen:
                print(json.dumps(evt, ensure_ascii=False))
            return 0

        text_out: List[str] = []
        for evt in gen:
            delta = _extract_delta_text_from_responses_event(evt)
            if delta:
                text_out.append(delta)
                _write_stream_text(delta)

        if args.output_file:
            _write_text_file(args.output_file, "".join(text_out))
        if args.newline:
            print()
        return 0

    obj = client.responses(
        model=args.model,
        input_text=prompt,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
        stream=False,
        extra=extra,
    )
    assert isinstance(obj, dict)

    if args.json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return 0

    text = _extract_text_from_responses_json(obj)
    print(text)
    if args.output_file:
        _write_text_file(args.output_file, text)
    return 0


def _write_text_file(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lmst",
        description="LM Studio OpenAI-compatible CLI (models/chat/responses) with SSE streaming.",
    )
    p.add_argument(
        "--base_url",
        "-b",
        default="http://localhost:1234/v1",
        help="Base URL for LM Studio server. Accepts http://host:1234 or http://host:1234/v1 (default: http://localhost:1234/v1).",
    )
    p.add_argument(
        "--timeout_seconds",
        "-t",
        type=float,
        default=300.0,
        help="HTTP timeout in seconds (default: 300).",
    )
    p.add_argument(
        "--api_key",
        "-k",
        default=None,
        help="Optional API key (Bearer token). LM Studio often doesn't require this.",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose debug output to stderr.",
    )

    sub = p.add_subparsers(dest="command", required=True)

    pm = sub.add_parser("models", help="List available models.")
    pm.add_argument("--json", "-j", action="store_true", help="Print raw JSON.")
    pm.set_defaults(func=_cmd_models)

    pc = sub.add_parser("chat", help="Chat Completions API (/v1/chat/completions).")
    pc.add_argument("--model", "-m", required=True, help="Model id from 'models'.")
    pc.add_argument("--prompt", "-p", default=None, help="User prompt. If omitted, read from stdin.")
    pc.add_argument("--system_prompt", "-s", default=None, help="System prompt.")
    pc.add_argument("--temperature", "-T", type=float, default=0.7, help="Sampling temperature (default: 0.7).")
    pc.add_argument("--max_tokens", "-n", type=int, default=None, help="Max tokens to generate (optional).")
    pc.add_argument("--stream", "-S", action="store_true", help="Stream tokens live (SSE).")
    pc.add_argument("--no-stream", "-N", dest="stream", action="store_false", help="Disable streaming.")
    pc.set_defaults(stream=True)
    pc.add_argument("--newline", "-l", action="store_true", help="Print a newline after streaming completes.")
    pc.add_argument("--json", "-j", action="store_true", help="Print raw JSON (non-stream only).")
    pc.add_argument("--raw_events", "-r", action="store_true", help="Print raw SSE events (stream only).")
    pc.add_argument("--output_file", "-o", default=None, help="Write final text output to a file.")
    pc.add_argument(
        "--extra",
        "-x",
        nargs="*",
        default=None,
        help="Extra JSON-ish key=value pairs forwarded into the request body (best-effort JSON parsing for values).",
    )
    pc.set_defaults(func=_cmd_chat)

    pr = sub.add_parser("responses", help="Responses API (/v1/responses).")
    pr.add_argument("--model", "-m", required=True, help="Model id from 'models'.")
    pr.add_argument("--prompt", "-p", default=None, help="Prompt text. If omitted, read from stdin.")
    pr.add_argument("--temperature", "-T", type=float, default=0.7, help="Sampling temperature (default: 0.7).")
    pr.add_argument("--max_output_tokens", "-n", type=int, default=None, help="Max output tokens (optional).")
    pr.add_argument("--stream", "-S", action="store_true", help="Stream tokens live (SSE).")
    pr.add_argument("--no-stream", "-N", dest="stream", action="store_false", help="Disable streaming.")
    pr.set_defaults(stream=True)
    pr.add_argument("--newline", "-l", action="store_true", help="Print a newline after streaming completes.")
    pr.add_argument("--json", "-j", action="store_true", help="Print raw JSON (non-stream only).")
    pr.add_argument("--raw_events", "-r", action="store_true", help="Print raw SSE events (stream only).")
    pr.add_argument("--output_file", "-o", default=None, help="Write final text output to a file.")
    pr.add_argument(
        "--extra",
        "-x",
        nargs="*",
        default=None,
        help="Extra JSON-ish key=value pairs forwarded into the request body (best-effort JSON parsing for values).",
    )
    pr.set_defaults(func=_cmd_responses)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = ClientConfig(
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        api_key=args.api_key,
        verbose=args.verbose,
    )
    client = LMStudioClient(config)
    try:
        return int(args.func(client, args))
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
