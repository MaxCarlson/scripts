# agt/tui.py
from __future__ import annotations

import json, threading, re
from typing import Any, Dict, List, Optional

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.widgets import TextArea, Frame, Label
from prompt_toolkit.styles import Style
from prompt_toolkit.shortcuts import prompt
from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import has_focus

# Clipboard: best-effort
try:  # pragma: no cover
    from cross_platform.clipboard_utils import set_clipboard  # type: ignore
except Exception:  # pragma: no cover
    def set_clipboard(text: str) -> None:
        try:
            import pyperclip  # type: ignore
            pyperclip.copy(text)
        except Exception:
            pass

from .completion import CombinedCompleter
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
    Gemini-like two-pane TUI:
      - Top: scrollable output (history stays visible)
      - Bottom: input with completions
    Behavior:
      • Tab-completion for /commands and @paths (files, folders, globs)
      • Streaming runs in the background — you can keep typing
      • ESC cancels the current generation (does NOT exit)
      • Always asks before tools that write/edit/run
        - 'a' remembers per resource (e.g., “run → python” remembers python only)
    """

    # How many lines of a diff to show automatically / expand chunk size
    DIFF_SHOW = 30
    DIFF_EXPAND = 50

    def __init__(self, client: WebAIClient, *, model: Optional[str], provider: Optional[str],
                 stream: bool = True, thinking: bool = True, verbose: bool = False):
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

        # Remembered permissions
        self._allow_write_paths: set[str] = set()
        self._allow_edit_paths: set[str] = set()
        self._allow_run_bins: set[str] = set()

        self._busy = False
        self._cancel = False

        self.output = TextArea(
            text="accepting edits (shift + tab to toggle)\n",
            scrollbar=True,
            wrap_lines=True,
            read_only=True,
            focusable=False,
        )
        self.input = TextArea(
            height=3,
            prompt="> ",
            multiline=True,
            wrap_lines=True,
            completer=CombinedCompleter(),
            complete_while_typing=True,
        )
        self.status = Label(text=self._status_text())

        self.container = HSplit([Frame(self.output, title="Conversation"),
                                 Frame(self.input, title="Message"),
                                 self.status])
        self.kb = self._bindings()
        self.app = Application(layout=Layout(self.container),
                               key_bindings=self.kb,
                               full_screen=True,
                               mouse_support=False,
                               style=self._style())

        # Let Enter send
        self.input.accept_handler = self._on_submit

        # Initial health probe (non-fatal)
        try:
            ok, detail = self.client.health_detail()
            if not ok:
                self.server_down = True
                self._append_output(f"[warning] Server appears DOWN: {detail}")
                self._refresh_status()
        except Exception:
            self.server_down = True
            self._refresh_status()

    # --- Styling / status -----------------------------------------------------

    def _style(self) -> Style:
        return Style.from_dict({
            "frame.border": "#5f5f5f",
            "frame.label": "bold",
        })

    def _status_text(self) -> str:
        base = (f"Enter=send • Ctrl+J=newline • ESC=cancel "
                f"• model={self.model or '(unset)'} "
                f"• tokens: prompt={self.prompt_tokens_total}, completion={self.completion_tokens_total}")
        if self._busy: base += "  |  [thinking…]"
        if self.server_down: base += "  |  [SERVER DOWN]"
        return base

    def _refresh_status(self):
        self.status.text = self._status_text()

    # --- Key bindings ---------------------------------------------------------

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("enter", filter=has_focus(self.input))
        def _(event):
            # Non-blocking: handler will spawn a worker thread
            event.app.layout.current_buffer.validate_and_handle()

        @kb.add("c-j", filter=has_focus(self.input))
        def _(event):
            self.input.buffer.insert_text("\n")

        @kb.add("escape")
        def _(event):
            # ESC cancels the current run but leaves the app alive
            if self._busy:
                self._cancel = True
                self._append_output("[cancel] Stopping…")
            else:
                # No active job: treat as a no-op (Gemini keeps the UI open)
                pass
            self._refresh_status()

        @kb.add("c-c")
        def _(event):
            # Hard exit
            event.app.exit()

        return kb

    # --- Output helpers -------------------------------------------------------

    def _append_output(self, text: str):
        self.output.text += (text if text.endswith("\n") else text + "\n")
        self.output.buffer.cursor_position = len(self.output.text)

    # --- Permission prompts ---------------------------------------------------

    def _remember_key(self, kind: str, summary: str) -> str:
        """
        Extract a resource key for 'allow always' decisions.
          run → /usr/bin/python …  → key: run:/usr/bin/python
          write_file → /path/file  → key: write:/path/file
          edit_file → /path/file   → key: edit:/path/file
        """
        # summary styles from agent:
        #  "write_file → /p/file (N bytes)"
        #  "edit_file → /p/file\n<diff…>"
        #  "run → /bin/cmd args…"
        m = re.match(r"^(write_file|edit_file|run)\s+→\s+([^\s]+)", summary)
        if not m:
            return f"{kind}:*"
        tool, target = m.group(1), m.group(2)
        if tool == "run":
            # Remember by binary only
            target = target.split()[0]
            return f"run:{target}"
        if tool == "write_file":
            return f"write:{target}"
        if tool == "edit_file":
            return f"edit:{target}"
        return f"{kind}:{target}"

    def _ask_permission(self, kind: str, summary: str) -> bool:
        key = self._remember_key(kind, summary)
        allowed_sets = {
            "run": self._allow_run_bins,
            "write_file": self._allow_write_paths,
            "edit_file": self._allow_edit_paths,
        }
        # fast path: previously allowed
        bucket = allowed_sets.get(kind)
        if bucket and key.split(":", 1)[1] in bucket:
            return True

        # pretty, with expandable preview (Ctrl+S metaphor: here 's' expands)
        preview = summary
        lines = summary.splitlines()
        if len(lines) > self.DIFF_SHOW:
            preview = "\n".join(lines[:self.DIFF_SHOW]) + f"\n… ({len(lines)-self.DIFF_SHOW} more; press 's' to show more)"

        app = get_app()
        result = {"ans": "n"}

        def ask():
            print(f"\n? {kind} {key}\n{preview}\n")
            while True:
                ans = prompt("Allow? [y]es / [n]o / [a]lways / [s]how-all > ").strip().lower() or "n"
                if ans in {"y", "n", "a"}:
                    result["ans"] = ans
                    break
                if ans == "s":
                    print("\n" + summary + "\n")
                else:
                    print("Please answer y/n/a or s.")

        app.run_in_terminal(ask)

        ans = result["ans"]
        if ans == "a":
            # stash in per-kind bucket
            if bucket is not None:
                bucket.add(key.split(":", 1)[1])
            return True
        return ans == "y"

    # --- Send flow ------------------------------------------------------------

    def _send_background(self, user_text: str):
        """
        Background worker: runs streaming request and updates the UI.
        """
        self._busy = True
        self._cancel = False
        self._refresh_status()

        # Build final prompt with attachments
        cleaned, atts = expand_attachments(user_text)
        final_text = build_prompt_with_attachments(cleaned, atts)
        self.messages.append({"role": "user", "content": final_text})
        self._append_output("> " + (cleaned if cleaned else "(attachments)"))

        # account tokens
        preview_msgs = self.messages[:]  # already includes the new user msg
        self.prompt_tokens_total += count_messages_tokens(preview_msgs, self.model)
        self._refresh_status()

        try:
            if self.stream or self.thinking:
                agg: List[str] = []

                for evt in self.client.chat_stream_events(self.messages, model=self.model, provider=self.provider):  # type: ignore[arg-type]
                    if self._cancel:
                        break
                    event = evt.get("event")
                    if event == "content":
                        part = evt.get("text", "")
                        if part:
                            agg.append(part)
                            self._append_output(part)
                    elif event == "reasoning" and self.thinking:
                        self._append_output("[thinking] " + evt.get("text", ""))
                    elif event == "usage":
                        u = evt.get("usage", {})
                        self.prompt_tokens_total += int(u.get("prompt_tokens", 0))
                        self.completion_tokens_total += int(u.get("completion_tokens", 0))
                        self._refresh_status()

                content = "".join(agg) if not self._cancel else ""
                if content:
                    self.completion_tokens_total += count_text_tokens(content, self.model)
                    self.messages.append({"role": "assistant", "content": content})
                    self.outputs.append(content)
                    for outcome in apply_tools(content, self._ask_permission):
                        self._append_output(outcome)

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

        except Exception as e:
            self._append_output(f"[error] {e}")
            self.server_down = True
        finally:
            self._busy = False
            self._refresh_status()

    def _on_submit(self, buf) -> bool:
        text = self.input.text.strip()
        self.input.text = ""
        if not text:
            return True

        # Slash commands handled synchronously
        if text.startswith("/"):
            parts = text.split()
            cmd = parts[0].lower()
            args = parts[1:]
            if cmd == "/help":
                self._append_output(
                    "Commands: /help  /new  /models  /providers  /set model <m>  /set provider <p>\n"
                    "/save <file.jsonl>  /load <file.jsonl>  /cp [n]  /stats  /quit"
                )
            elif cmd == "/new":
                self.messages = self.messages[:1]
                self._append_output("Started a new conversation.")
            elif cmd == "/models":
                try:
                    data = self.client.list_models()
                    self._append_output(json.dumps(data, ensure_ascii=False, indent=2))
                except Exception as e:
                    self._append_output(f"Error: {e}")
            elif cmd == "/providers":
                try:
                    data = self.client.list_providers()
                    self._append_output(json.dumps(data, ensure_ascii=False, indent=2))
                except Exception as e:
                    self._append_output(f"Error: {e}")
            elif cmd == "/set" and len(args) >= 2:
                if args[0].lower() == "model":
                    self.model = args[1]; self._append_output(f"Model set: {self.model}")
                elif args[0].lower() == "provider":
                    self.provider = args[1]; self._append_output(f"Provider set: {self.provider}")
                else:
                    self._append_output("Usage: /set model <name>  |  /set provider <name>")
                self._refresh_status()
            elif cmd == "/save" and args:
                path = args[0]
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        for m in self.messages:
                            f.write(json.dumps(m, ensure_ascii=False) + "\n")
                    self._append_output(f"Saved {path}")
                except Exception as e:
                    self._append_output(f"Save failed: {e}")
            elif cmd == "/load" and args:
                path = args[0]
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
            elif cmd == "/cp":
                n = int(args[0]) if args else 1
                if not self.outputs:
                    self._append_output("Nothing to copy.")
                else:
                    try:
                        set_clipboard(self.outputs[-n])
                        self._append_output("Copied to clipboard.")
                    except Exception as e:
                        self._append_output(f"Copy failed: {e}")
            elif cmd == "/stats":
                self._append_output(self._status_text())
            elif cmd == "/quit":
                get_app().exit()
            else:
                self._append_output("Unknown command. Try /help.")
            return True

        # Spawn streaming worker; UI stays interactive
        if not self._busy:
            threading.Thread(target=self._send_background, args=(text,), daemon=True).start()
        else:
            self._append_output("[busy] Please wait or press ESC to cancel.")
        return True

    def run(self):
        # full-screen “Gemini-like” start
        from os import system, name
        system("cls" if name == "nt" else "clear")
        self.app.run()
