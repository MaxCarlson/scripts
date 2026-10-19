from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from lmstui.api import LMStudioAPI
from lmstui.formatting import safe_get
from lmstui.sse import extract_delta_text, extract_usage_from_chunk


@dataclass
class ReplState:
    model: str
    system: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = True
    stats: bool = False
    silent: bool = False


def _print_flush(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def _print_stats(usage: Optional[Dict[str, Any]], duration: float, tps: Optional[float] = None) -> None:
    parts = ["[stats]"]
    if usage:
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        reasoning_tokens = safe_get(usage, "completion_tokens_details", "reasoning_tokens")
        if reasoning_tokens is None:
            reasoning_tokens = usage.get("reasoning_tokens")
        total_tokens = usage.get("total_tokens")

        if prompt_tokens is not None:
            parts.append(f"  Prompt tokens:     {prompt_tokens}")
        if completion_tokens is not None:
            parts.append(f"  Completion tokens: {completion_tokens}")
        if reasoning_tokens is not None:
            parts.append(f"  Reasoning tokens:  {reasoning_tokens}")
        if total_tokens is not None:
            parts.append(f"  Total tokens:      {total_tokens}")

    parts.append(f"  Duration:          {duration:.2f}s")
    if tps is not None:
        parts.append(f"  Tokens/sec:        {tps:.2f}")
    elif usage and usage.get("completion_tokens") and duration > 0:
        calc_tps = usage["completion_tokens"] / duration
        parts.append(f"  Tokens/sec:        {calc_tps:.2f}")

    print("\n".join(parts), file=sys.stderr, flush=True)


def run_chat_repl(api: LMStudioAPI, state: ReplState) -> int:
    messages: List[Dict[str, str]] = []
    if state.system:
        messages.append({"role": "system", "content": state.system})

    if not state.silent:
        _print_flush(
            "\n".join(
                [
                    "",
                    "lmst chat (type /help for commands, Ctrl+C to exit)",
                    f"  model:  {state.model}",
                    f"  stream: {state.stream}",
                    "",
                ]
            )
        )

    while True:
        try:
            user_in = input("> ").rstrip("\r\n")
        except (EOFError, KeyboardInterrupt):
            _print_flush("\n")
            return 0

        if not user_in.strip():
            continue

        if user_in.startswith("/"):
            cmd = user_in.strip().lower()
            if cmd in ("/q", "/quit", "/exit"):
                return 0
            if cmd in ("/r", "/reset"):
                messages = [{"role": "system", "content": state.system}] if state.system else []
                _print_flush("(conversation reset)\n")
                continue
            if cmd in ("/stats", "/stat"):
                state.stats = not state.stats
                _print_flush(f"(stats toggled: {'on' if state.stats else 'off'})\n")
                continue
            if cmd in ("/h", "/help"):
                _print_flush(
                    "\n".join(
                        [
                            "Commands:",
                            "  /help           show this help",
                            "  /reset          reset conversation history",
                            "  /stats          toggle statistics display",
                            "  /exit, /quit    quit chat",
                            "",
                        ]
                    )
                )
                continue
            _print_flush(f"(unknown command: {cmd})\n")
            continue

        messages.append({"role": "user", "content": user_in})

        t0 = time.time()
        last_usage: Optional[Dict[str, Any]] = None
        tps: Optional[float] = None

        if state.stream:
            _print_flush("assistant> ")
            buf: List[str] = []
            try:
                gen = api.chat_completions(
                    model=state.model,
                    messages=messages,
                    temperature=state.temperature,
                    max_tokens=state.max_tokens,
                    stream=True,
                )
                for chunk in gen:
                    delta = extract_delta_text(chunk)
                    if delta:
                        buf.append(delta)
                        _print_flush(delta)
                    u = extract_usage_from_chunk(chunk)
                    if u:
                        last_usage = u
            except KeyboardInterrupt:
                _print_flush(" ^C (interrupted)\n")
                if buf:
                    messages.append({"role": "assistant", "content": "".join(buf)})
                continue
            except Exception as e:
                _print_flush(f"\nError during streaming: {e}\n")
                continue

            _print_flush("\n")
            t1 = time.time()
            assistant_reply = "".join(buf)
            messages.append({"role": "assistant", "content": assistant_reply})

            if state.stats:
                _print_stats(last_usage, t1 - t0, tps)
            continue

        # Non-streaming turn
        try:
            resp = api.chat_completions(
                model=state.model,
                messages=messages,
                temperature=state.temperature,
                max_tokens=state.max_tokens,
                stream=False,
            )
            t1 = time.time()
            assert isinstance(resp, dict)
            content = safe_get(resp, "choices", default=[{}])[0].get("message", {}).get("content", "")
            _print_flush(f"assistant> {content}\n")
            messages.append({"role": "assistant", "content": content})

            if state.stats:
                usage = resp.get("usage")
                stats = resp.get("stats") or {}
                tps = stats.get("tokens_per_second")
                _print_stats(usage, t1 - t0, tps)
        except Exception as e:
            _print_flush(f"Error: {e}\n")

    return 0
