#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebAI-to-API Minimal TUI Client (cross-platform)

- Talks to a local OpenAI-compatible server (default http://localhost:6969)
- Multiline input: Ctrl+J inserts a newline, Enter sends (Gemini CLI feel)
- Slash commands: /help, /new, /models, /providers, /set model <m>, /set provider <p>, /save <f>, /load <f>, /quit
- Attach files with tokens like @path/file.txt or @notes/*.md (globs supported) — inlined into the next user prompt
- Agentic (if told): understands special "tool" blocks from the model and asks before:
    * write_file  → create/overwrite files
    * edit_file   → replace file content (shows a diff first)
    * run         → run a command (PowerShell on Windows, bash -lc on Linux)
  For each request it asks (y / n / a) where:
    y = allow once, n = deny, a = always allow that tool for the rest of the session.

- Optional --thinking flag shows any 'reasoning' text if present in the response.
- Streaming with --stream.

IMPORTANT: To avoid this source breaking out of Markdown code fences, example tool blocks below use [[tool]] ... [[/tool]].
The client ALSO supports the common fence form used by many agents (three backticks + 'tool') at runtime.

Example tool messages the assistant might send back:
  [[tool]]
  {"tool":"write_file","path":"out.txt","content":"Hello"}
  [[/tool]]

  [[tool]]
  {"tool":"edit_file","path":"app.py","patch":"...full new file content..."}
  [[/tool]]

  [[tool]]
  {"tool":"run","cmd":"pytest -q"}
  [[/tool]]
"""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

console = Console()

# Defaults (override with env or flags)
DEFAULT_URL = os.getenv("WAI_API_URL", "http://192.168.50.100:6969")
DEFAULT_MODEL = os.getenv("WAI_MODEL", "gemini-2.5-pro")
DEFAULT_PROVIDER = os.getenv("WAI_PROVIDER", "")  # only needed for gpt4free mode

HELP_TEXT = (
    "[bold]Commands[/bold]\n"
    "/help                              Show this help\n"
    "/new                               Start a new conversation\n"
    "/models                            List available models  (GET /v1/models)\n"
    "/providers                         List available providers (GET /v1/providers)\n"
    "/set model <name>                  Set the active model\n"
    "/set provider <name>               Set the active provider (gpt4free mode)\n"
    "/save <file.jsonl>                 Save conversation to JSONL\n"
    "/load <file.jsonl>                 Load conversation from JSONL\n"
    "/quit                              Exit\n\n"
    "[bold]Input tips[/bold]\n"
    "- Enter sends; Ctrl+J inserts a newline (Gemini CLI style).\n"
    "- Attach files by typing @path/file.txt or globs like @notes/*.md; they are inlined into your next message.\n\n"
    "[bold]Agentic actions[/bold]\n"
    "Assistant may respond with a 'tool' block containing JSON. Example:\n"
    "[[tool]]\n"
    '{"tool":"write_file","path":"out.txt","content":"Hello"}\n'
    "[[/tool]]\n"
)

# Permission memory for current session
TOOL_ALWAYS_ALLOW: Dict[str, bool] = {
    "write_file": False,
    "edit_file": False,
    "run": False,
}


def parse_args(argv: List[str]) -> Dict[str, Any]:
    p = argparse.ArgumentParser(description="WebAI-to-API Minimal TUI Client")
    p.add_argument(
        "-u", "--url", default=DEFAULT_URL, help="Base URL (default: %(default)s)"
    )
    p.add_argument(
        "-m", "--model", default=DEFAULT_MODEL, help="Model name (default: %(default)s)"
    )
    p.add_argument(
        "-p",
        "--provider",
        default=DEFAULT_PROVIDER,
        help="Provider name (optional; gpt4free mode)",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--webai", action="store_true", help="Target WebAI (Gemini) endpoint"
    )
    mode.add_argument("--g4f", action="store_true", help="Target gpt4free endpoint")
    p.add_argument(
        "-s", "--stream", action="store_true", help="Stream responses (default off)"
    )
    p.add_argument(
        "-t", "--thinking", action="store_true", help="Show 'reasoning' if present"
    )
    p.add_argument(
        "--history",
        default=str(Path.home() / ".wai_cli_history"),
        help="Path to input history file",
    )
    return vars(p.parse_args(argv))


def kb_for_multiline() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("c-j")  # Ctrl+J -> newline, Enter submits
    def _(event):
        event.current_buffer.insert_text("\n")

    return kb


def openai_chat_url(base: str) -> str:
    return f"{base.rstrip('/')}/v1/chat/completions"


def list_models(base: str) -> Any:
    try:
        resp = requests.get(f"{base.rstrip('/')}/v1/models", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        console.print(f"[red]Error listing models:[/red] {e}")
        return None


def list_providers(base: str) -> Any:
    try:
        resp = requests.get(f"{base.rstrip('/')}/v1/providers", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        console.print(f"[red]Error listing providers:[/red] {e}")
        return None


def expand_attachments(user_text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Finds @path tokens, expands globs, and reads files.
    Returns cleaned_text, [(filepath, content), ...]
    """
    attachments: List[Tuple[str, str]] = []

    def repl(match: re.Match) -> str:
        token = match.group(0)  # includes leading '@'
        pattern = token[1:]
        files = sorted(glob.glob(pattern, recursive=True))
        for fp in files:
            try:
                p = Path(fp)
                if p.is_file():
                    txt = p.read_text(encoding="utf-8", errors="replace")
                    attachments.append((fp, txt))
            except Exception as e:
                attachments.append((fp, f"<<error reading file: {e}>>"))
        return ""  # strip token; we'll inline separately

    cleaned = re.sub(r"@[\w\-/\\\.\*\?\[\]\{\}]+", repl, user_text)
    return cleaned.strip(), attachments


def build_prompt_with_attachments(text: str, atts: List[Tuple[str, str]]) -> str:
    if not atts:
        return text
    parts: List[str] = [text, "", "### Attachments"]
    for fp, content in atts:
        # Intentionally avoid Markdown fences that could break shells or note tools
        parts.append(
            "\n---\n[FILE] " + fp + "\n" + "BEGIN_FILE\n" + content + "\nEND_FILE"
        )
    return "\n".join(parts)


def stream_chat(url: str, payload: Dict[str, Any]):
    with requests.post(url, json=payload, stream=True) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data:"):
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
                except Exception:
                    yield line + "\n"


def post_chat(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    resp = requests.post(url, json=payload, timeout=300)
    resp.raise_for_status()
    return resp.json()


def extract_reasoning(obj: Dict[str, Any]) -> Optional[str]:
    # Best-effort: try common shapes seen in some servers
    try:
        ch = obj.get("choices", [{}])[0]
        msg = ch.get("message", {})
        if "reasoning" in msg:
            r = msg["reasoning"]
            if isinstance(r, dict) and isinstance(r.get("tokens"), str):
                return r["tokens"]
            if isinstance(r, str):
                return r
        if "reasoning" in ch and isinstance(ch["reasoning"], str):
            return ch["reasoning"]
    except Exception:
        pass
    return None


# Build a pattern for three backticks without writing them literally in source (prevents Markdown fence breakage)
BACKTICKS = "`" * 3
TOOL_BLOCK_RE = re.compile(
    rf"{re.escape(BACKTICKS)}tool\s+([\s\S]*?){re.escape(BACKTICKS)}", re.IGNORECASE
)
ALT_TOOL_BLOCK_RE = re.compile(
    r"\[\[tool\]\]\s*([\s\S]*?)\s*\[\[/tool\]\]", re.IGNORECASE
)


def parse_tools(text: str) -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []
    for m in TOOL_BLOCK_RE.finditer(text):
        blob = m.group(1).strip()
        try:
            tools.append(json.loads(blob))
        except Exception:
            pass
    for m in ALT_TOOL_BLOCK_RE.finditer(text):
        blob = m.group(1).strip()
        try:
            tools.append(json.loads(blob))
        except Exception:
            pass
    return tools


def confirm_tool(kind: str, summary: str) -> bool:
    if TOOL_ALWAYS_ALLOW.get(kind):
        return True
    console.print(
        Panel.fit(
            f"[bold yellow]Tool request: {kind}[/bold yellow]\n{summary}\nAllow? [y]es / [n]o / allow [a]lways",
            title="Permission",
        )
    )
    while True:
        ans = input("(y/n/a) > ").strip().lower()
        if ans == "y":
            return True
        if ans == "n":
            return False
        if ans == "a":
            TOOL_ALWAYS_ALLOW[kind] = True
            return True


def tool_write_file(path: str, content: str):
    p = Path(path)
    summary = f"write_file → {p} ({len(content)} bytes)"
    if not confirm_tool("write_file", summary):
        console.print("[red]Denied.[/red]")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    console.print(f"[green]Wrote[/green] {p}")


def tool_edit_file(path: str, new_content: str):
    p = Path(path)
    old = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    diff = "\n".join(
        difflib.unified_diff(
            old.splitlines(),
            new_content.splitlines(),
            fromfile=f"{p} (old)",
            tofile=f"{p} (new)",
            lineterm="",
        )
    )
    if not diff:
        diff = "(no changes)"
    summary = f"edit_file → {p}\n[diff]\n{diff[:10000]}"
    if not confirm_tool("edit_file", summary):
        console.print("[red]Denied.[/red]")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new_content, encoding="utf-8")
    console.print(f"[green]Updated[/green] {p}")


def tool_run(cmd: str):
    # Run via pwsh on Windows; bash -lc on POSIX to honor shell features & PATH
    if platform.system().lower().startswith("win"):
        full = ["pwsh", "-NoLogo", "-NoProfile", "-Command", cmd]
        nice = f"pwsh -NoLogo -NoProfile -Command {cmd}"
    else:
        full = ["/bin/bash", "-lc", cmd]
        nice = f"/bin/bash -lc {cmd}"
    if not confirm_tool("run", f"run → {nice}"):
        console.print("[red]Denied.[/red]")
        return
    try:
        proc = subprocess.run(full, capture_output=True, text=True, timeout=3600)
        console.print(
            Panel.fit(
                f"exit={proc.returncode}\n\n[stdout]\n{proc.stdout[:8000]}\n\n[stderr]\n{proc.stderr[:8000]}",
                title="run result",
            )
        )
    except Exception as e:
        console.print(f"[red]run failed:[/red] {e}")


def apply_tools(text: str):
    tools = parse_tools(text)
    for t in tools:
        name = t.get("tool")
        if name == "write_file":
            tool_write_file(t.get("path", "out.txt"), t.get("content", ""))
        elif name == "edit_file":
            tool_edit_file(t.get("path", "file.txt"), t.get("patch", ""))
        elif name == "run":
            tool_run(t.get("cmd", ""))
        # Unknown tools are ignored silently


def save_jsonl(path: str, msgs: List[Dict[str, Any]]):
    with open(path, "w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    console.print(f"[green]Saved[/green] {path}")


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    msgs: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                msgs.append(json.loads(line))
    console.print(f"[green]Loaded[/green] {path} ({len(msgs)} messages)")
    return msgs


def main():
    args = parse_args(sys.argv[1:])
    base = args["url"]
    model = args["model"]
    provider = args["provider"].strip() or None
    stream = args["stream"]
    thinking = args["thinking"]

    chat_url = openai_chat_url(base)
    session = PromptSession(
        history=FileHistory(args["history"]), key_bindings=kb_for_multiline()
    )

    console.print(
        Panel.fit(
            f"[bold]WebAI-to-API Client[/bold]\nURL: {base}\nModel: {model}\nProvider: {provider or '(none)'}\n"
            f"Stream: {stream}\nThinking: {thinking}\n\nType /help for commands.",
            title="Ready",
        )
    )

    # System prompt inviting tool JSON (no markdown fences inside to avoid breaking notes)
    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are an assistant. If you need to take real actions, respond with a block labeled 'tool' "
                "containing JSON of one of the forms: "
                '{"tool":"write_file","path":"...","content":"..."}, '
                '{"tool":"edit_file","path":"...","patch":"..."}, '
                '{"tool":"run","cmd":"..."} '
                "Otherwise, reply normally."
            ),
        }
    ]

    completer = WordCompleter(
        ["/help", "/new", "/models", "/providers", "/set", "/save", "/load", "/quit"],
        ignore_case=True,
    )

    while True:
        try:
            text = session.prompt("> ", completer=completer)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Bye.[/yellow]")
            break

        if not text.strip():
            continue

        # Slash commands
        if text.startswith("/"):
            parts = shlex.split(text)
            cmd = parts[0].lower()
            if cmd == "/help":
                console.print(Markdown(HELP_TEXT))
            elif cmd == "/new":
                messages = messages[:1]
                console.print("[green]Started a new conversation.[/green]")
            elif cmd == "/models":
                data = list_models(base)
                console.print_json(data=data)
            elif cmd == "/providers":
                data = list_providers(base)
                console.print_json(data=data)
            elif cmd == "/set":
                if len(parts) >= 3 and parts[1].lower() == "model":
                    model = parts[2]
                    console.print(f"[green]Model set:[/green] {model}")
                elif len(parts) >= 3 and parts[1].lower() == "provider":
                    provider = parts[2]
                    console.print(f"[green]Provider set:[/green] {provider}")
                else:
                    console.print(
                        "[yellow]Usage:[/yellow] /set model <name>  |  /set provider <name>"
                    )
            elif cmd == "/save" and len(parts) >= 2:
                save_jsonl(parts[1], messages)
            elif cmd == "/load" and len(parts) >= 2:
                try:
                    messages = load_jsonl(parts[1])
                except Exception as e:
                    console.print(f"[red]Load failed:[/red] {e}")
            elif cmd == "/quit":
                break
            else:
                console.print("[yellow]Unknown command. Try /help.[/yellow]")
            continue

        # Attachments via @path tokens
        cleaned, atts = expand_attachments(text)
        final_text = build_prompt_with_attachments(cleaned, atts)
        messages.append({"role": "user", "content": final_text})

        payload: Dict[str, Any] = {"model": model, "messages": messages}
        if provider:
            payload["provider"] = provider  # needed by gpt4free mode per server docs
        if stream:
            payload["stream"] = True

        try:
            if stream:
                console.print("[dim]Streaming...[/dim]")
                buff: List[str] = []
                for chunk in stream_chat(chat_url, payload):
                    buff.append(chunk)
                    console.print(chunk, end="")
                console.print()
                text_out = "".join(buff)
                messages.append({"role": "assistant", "content": text_out})
                apply_tools(text_out)
            else:
                resp = post_chat(chat_url, payload)
                if thinking:
                    rsn = extract_reasoning(resp)
                    if rsn:
                        console.print(
                            Panel(rsn, title="thinking", subtitle="(from response)")
                        )
                content = (
                    resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
                if content:
                    # If response includes markdown code, render nicely; otherwise plain
                    console.print(Markdown(content) if ("```" in content) else content)
                    messages.append({"role": "assistant", "content": content})
                    apply_tools(content)
                else:
                    console.print_json(data=resp)
        except requests.HTTPError as e:
            try:
                console.print_json(data=e.response.json())
            except Exception:
                console.print(f"[red]HTTP error:[/red] {e}")
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")


if __name__ == "__main__":
    main()
