from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from lmstui.api import LmStudioApi
from lmstui.formatting import safe_get


@dataclass
class ReplState:
    model: str
    system: str | None = None
    temperature: float = 0.7
    max_tokens: int = -1
    stream: bool = True


def _print_flush(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def run_chat_repl(api: LmStudioApi, state: ReplState) -> int:
    messages: List[Dict[str, str]] = []
    if state.system:
        messages.append({"role": "system", "content": state.system})

    _print_flush(
        "\n".join(
            [
                "",
                "lmstui chat (type /help)",
                f"  model: {state.model}",
                f"  stream: {state.stream}",
                "",
            ]
        )
    )

    while True:
        try:
            user_in = input("> ").rstrip("\n")
        except (EOFError, KeyboardInterrupt):
            _print_flush("\n")
            return 0

        if not user_in:
            continue

        if user_in.startswith("/"):
            cmd = user_in.strip().lower()
            if cmd in ("/q", "/quit", "/exit"):
                return 0
            if cmd in ("/r", "/reset"):
                messages = ([{"role": "system", "content": state.system}] if state.system else [])
                _print_flush("(reset)\n")
                continue
            if cmd in ("/h", "/help"):
                _print_flush(
                    "\n".join(
                        [
                            "Commands:",
                            "  /help           show this",
                            "  /reset          reset conversation",
                            "  /exit           quit",
                            "",
                        ]
                    )
                )
                continue
            _print_flush(f"(unknown command) {cmd}\n")
            continue

        messages.append({"role": "user", "content": user_in})

        if state.stream:
            try:
                lines = api.chat_rest(
                    model=state.model,
                    messages=messages,
                    temperature=state.temperature,
                    max_tokens=state.max_tokens,
                    stream=True,
                )
                _print_flush("assistant> ")
                buf: List[str] = []
                for piece in api.iter_stream_text_from_lines(lines):
                    buf.append(piece)
                    _print_flush(piece)
                _print_flush("\n")
                messages.append({"role": "assistant", "content": "".join(buf)})
                continue
            except Exception:
                pass

        resp = api.chat_rest(
            model=state.model,
            messages=messages,
            temperature=state.temperature,
            max_tokens=state.max_tokens,
            stream=False,
        )

        content = safe_get(resp, "choices", default=[{}])[0].get("message", {}).get("content", "")
        if content:
            _print_flush(f"assistant> {content}\n")
            messages.append({"role": "assistant", "content": content})

        stats = resp.get("stats") if isinstance(resp, dict) else None
        if isinstance(stats, dict) and stats:
            tps = stats.get("tokens_per_second")
            ttft = stats.get("time_to_first_token")
            _print_flush(f"(stats) tps={tps} ttft={ttft}\n")

    return 0
