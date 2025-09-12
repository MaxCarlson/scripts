#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.widgets import TextArea, Frame, Label
from prompt_toolkit.styles import Style
from prompt_toolkit.shortcuts import prompt
from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import has_focus

# Clipboard: prefer cross_platform; fallback to pyperclip/no-op.
try:  # pragma: no cover
    from cross_platform.clipboard_utils import set_clipboard  # type: ignore
except Exception:  # pragma: no cover
    def set_clipboard(text: str) -> None:
        try:
            import pyperclip  # type: ignore
            pyperclip.copy(text)
        except Exception:
            pass

from .agent import (
    apply_tools,
    build_prompt_with_attachments,
    expand_attachments,
    extract_reasoning,
)
from .client import WebAIClient
from .tokens import count_messages_tokens, count_text_tokens


class TUI:
    """
    Two-pane TUI:
      - Top: scrollable output
      - Bottom: input box

    Controls:
      - Enter: send message  (Termux-friendly)
      - Ctrl+J: insert newline
    """

    def __init__(self, client: WebAIClient, *, model: Optional[str], provider: Optional[str],
                 stream: bool, thinking: bool, verbose: bool = False):
        self.client = client
        self.model = model
        self.provider = provider
        self.stream = stream
        self.thinking = thinking
        self.verbose = verbose

        self.messages: List[Dict[str, str]] = [
            {"role": "system", "content": "You are a helpful assistant. Return tool JSON when acting."}
        ]
        self.outputs: List[str] = []
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.server_down = False

        self.output = TextArea(
            text="WebAI-to-API Client\nType /help for commands.\n",
            scrollbar=True,
            wrap_lines=True,
            read_only=True,
            focusable=False,
        )
        self.input = TextArea(height=3, prompt="> ", multiline=True, wrap_lines=True)
        self.status = Label(text=self._status_text())

        self.container = HSplit([Frame(self.output, title="Conversation"),
                                 Frame(self.input, title="Message"),
                                 self.status])
        self.kb = self._bindings()
        self.app = Application(layout=Layout(self.container),
                               key_bindings=self.kb,
                               full_screen=False,
                               mouse_support=False,
                               style=self._style())

        # Enter sends:
        self.input.accept_handler = self._on_submit

        # Initial health check
        ok, detail = self.client.health_detail()
        if not ok:
            self.server_down = True
            self._append_output(f"[warning] Server appears DOWN: {detail}")
            self._refresh_status()
        elif self.verbose:
            self._append_output("[debug] Health OK")

    def _style(self) -> Style:
        return Style.from_dict({
            "frame.border": "#5f5f5f",
            "frame.label": "bold",
        })

    def _status_text(self) -> str:
        base = (f"Enter=send | Ctrl+J=new line | /help | "
                f"model={self.model or '(unset)'} | "
                f"tokens: prompt={self.prompt_tokens_total}, completion={self.completion_tokens_total}")
        if self.server_down:
            base += "  |  [SERVER DOWN]"
        return base

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("enter", filter=has_focus(self.input))   # Enter = send
        def _(event):
            event.app.layout.current_buffer.validate_and_handle()

        @kb.add("c-j", filter=has_focus(self.input))     # Ctrl+J = newline
        def _(event):
            self.input.buffer.insert_text("\n")

        @kb.add("c-c")
        @kb.add("escape")
        def _(event):
            event.app.exit()

        return kb

    def _append_output(self, text: str):
        self.output.text += (text if text.endswith("\n") else text + "\n")
        self.output.buffer.cursor_position = len(self.output.text)

    def _refresh_status(self):
        self.status.text = self._status_text()

    def _ask_permission(self, kind: str, summary: str) -> bool:
        app = get_app()
        result = {"ans": "n"}

        def ask():
            s = f"[{kind}] {summary}\nAllow? (y/n/a) > "
            ans = prompt(s).strip().lower()
            result["ans"] = ans or "n"

        app.run_in_terminal(ask)

        if result["ans"] == "a":
            setattr(self, f"_allow_{kind}", True)
            return True
        if getattr(self, f"_allow_{kind}", False):
            return True
        return result["ans"] == "y"

    # ----- slash commands -----
    def _cmd_help(self):
        self._append_output(
            "Commands: /help  /new  /models  /providers  /set model <m>  /set provider <p>\n"
            "/save <file.jsonl>  /load <file.jsonl>  /cp [n]  /stats  /quit"
        )

    def _cmd_models(self):
        try:
            data = self.client.list_models()
            self._append_output(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            self._append_output(f"Error: {e}")

    def _cmd_providers(self):
        try:
            data = self.client.list_providers()
            self._append_output(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            self._append_output(f"Error: {e}")

    def _cmd_set(self, args: List[str]):
        if len(args) >= 2 and args[0].lower() == "model":
            self.model = args[1]
            self._append_output(f"Model set: {self.model}")
        elif len(args) >= 2 and args[0].lower() == "provider":
            self.provider = args[1]
            self._append_output(f"Provider set: {self.provider}")
        else:
            self._append_output("Usage: /set model <name>  |  /set provider <name>")
        self._refresh_status()

    def _cmd_save(self, path: str):
        try:
            with open(path, "w", encoding="utf-8") as f:
                for m in self.messages:
                    f.write(json.dumps(m, ensure_ascii=False) + "\n")
            self._append_output(f"Saved {path}")
        except Exception as e:
            self._append_output(f"Save failed: {e}")

    def _cmd_load(self, path: str):
        try:
            msgs: List[Dict[str, str]] = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        msgs.append(json.loads(line))
            self.messages = msgs
            self._append_output(f"Loaded {path} ({len(msgs)} messages)")
        except Exception as e:
            self._append_output(f"Load failed: {e}")

    def _cmd_cp(self, n: int = 1):
        idx = -n
        if not self.outputs:
            self._append_output("Nothing to copy.")
            return
        try:
            text = self.outputs[idx]
        except Exception:
            self._append_output(f"No output #{n}.")
            return
        set_clipboard(text)
        self._append_output("Copied to clipboard.")

    def _cmd_stats(self):
        self._append_output(self._status_text())

    # ----- message flow -----
    def _on_submit(self, buf) -> bool:
        text = self.input.text.strip()
        self.input.text = ""

        if not text:
            return True

        if text.startswith("/"):
            parts = text.split()
            cmd = parts[0].lower()
            args = parts[1:]
            if cmd == "/help":
                self._cmd_help()
            elif cmd == "/new":
                self.messages = self.messages[:1]
                self._append_output("Started a new conversation.")
            elif cmd == "/models":
                self._cmd_models()
            elif cmd == "/providers":
                self._cmd_providers()
            elif cmd == "/set":
                self._cmd_set(args)
            elif cmd == "/save" and args:
                self._cmd_save(args[0])
            elif cmd == "/load" and args:
                self._cmd_load(args[0])
            elif cmd == "/cp":
                n = int(args[0]) if args else 1
                self._cmd_cp(n)
            elif cmd == "/stats":
                self._cmd_stats()
            elif cmd == "/quit":
                get_app().exit()
            else:
                self._append_output("Unknown command. Try /help.")
            return True

        if self.verbose:
            self._append_output(f"[debug] sending -> url={self.client.base_url} model={self.model or self.client.model} provider={self.provider or self.client.provider}")

        preview_msgs = self.messages + [{"role": "user", "content": text}]
        self.prompt_tokens_total += count_messages_tokens(preview_msgs, self.model)
        self._refresh_status()

        cleaned, atts = expand_attachments(text)
        final_text = build_prompt_with_attachments(cleaned, atts)
        self.messages.append({"role": "user", "content": final_text})
        self._append_output("> " + (cleaned if cleaned else "(attachments)"))

        try:
            if self.stream or self.thinking:
                agg: List[str] = []
                for evt in self.client.chat_stream_events(self.messages, model=self.model, provider=self.provider):  # type: ignore[arg-type]
                    event = evt.get("event")
                    if event == "content":
                        part = evt.get("text", "")
                        agg.append(part)
                        self._append_output(part)
                    elif event == "reasoning" and self.thinking:
                        self._append_output("[thinking] " + evt.get("text", ""))
                    elif event == "usage":
                        u = evt.get("usage", {})
                        self.prompt_tokens_total += int(u.get("prompt_tokens", 0))
                        self.completion_tokens_total += int(u.get("completion_tokens", 0))
                        self._refresh_status()
                content = "".join(agg)
                if content:
                    self.completion_tokens_total += count_text_tokens(content, self.model)
                self._refresh_status()
                self.messages.append({"role": "assistant", "content": content})
                self.outputs.append(content)
                for outcome in apply_tools(content, self._ask_permission):
                    self._append_output(outcome)
                if self.server_down:
                    self.server_down = False
                    self._refresh_status()
            else:
                resp = self.client.chat_once(self.messages, model=self.model, provider=self.provider, stream=False)  # type: ignore[arg-type]
                rsn = extract_reasoning(resp) if self.thinking else None
                if rsn:
                    self._append_output("[thinking]\n" + rsn)
                content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not content:
                    self._append_output(json.dumps(resp, ensure_ascii=False, indent=2))
                else:
                    self._append_output(content)
                    self.messages.append({"role": "assistant", "content": content})
                    self.outputs.append(content)
                    for outcome in apply_tools(content, self._ask_permission):
                        self._append_output(outcome)
                usage = resp.get("usage", {})
                self.prompt_tokens_total += int(usage.get("prompt_tokens", 0))
                self.completion_tokens_total += int(usage.get("completion_tokens", 0))
                if not usage and content:
                    self.completion_tokens_total += count_text_tokens(content, self.model)
                if self.server_down:
                    self.server_down = False
                self._refresh_status()
        except Exception as e:
            self._append_output(f"[error] {e}")
            self.server_down = True
            self._refresh_status()

        return True

    def run(self):
        self.app.run()

