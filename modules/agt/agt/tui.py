# file: agt/tui.py
from __future__ import annotations

import glob
import logging
import os
import re
import threading
from pathlib import Path
from typing import List, Optional, Tuple

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import Input, Label, ListItem, ListView, Static

# Prefer RichLog (newer Textual); fall back to Log for older installs.
try:
    from textual.widgets import RichLog as _LogWidget
except Exception:  # pragma: no cover
    from textual.widgets import Log as _LogWidget

from .client import WebAIClient


# ---------------- helpers ----------------

_SLASH_COMMANDS = [
    ("help", "Show help for commands"),
    ("about", "Show version info"),
    ("clear", "Clear the screen and conversation history"),
]

def _filter_cmds(prefix: str):
    p = prefix.lower()
    return [c for c in _SLASH_COMMANDS if c[0].startswith(p)]

def _safe_read_file(p: Path, max_bytes: int = 120_000) -> str:
    try:
        b = p.read_bytes()
    except Exception as e:  # pragma: no cover
        return f"<<error reading {p}: {e}>>"
    tail = ""
    if len(b) > max_bytes:
        b = b[:max_bytes]
        tail = "\n\n[...truncated...]"
    try:
        txt = b.decode("utf-8", errors="replace")
    except Exception:
        txt = b.decode("latin-1", errors="replace")
    return txt + tail

def _files_from_at_expr(expr: str) -> List[Path]:
    # Support @file, @dir/, and @glob/**/*.py
    expr = os.path.expandvars(os.path.expanduser(expr))
    p = Path(expr)
    out: List[Path] = []
    if p.exists() and p.is_dir():
        for fp in p.rglob("*"):
            if fp.is_file():
                out.append(fp)
        return out
    for g in glob.glob(expr, recursive=True):
        gp = Path(g)
        if gp.is_file():
            out.append(gp)
    return out

def _log_write(widget: _LogWidget, text: str) -> None:
    # RichLog has write(); older Log had write_line()
    if hasattr(widget, "write"):
        widget.write(text)
    elif hasattr(widget, "write_line"):  # pragma: no cover
        widget.write_line(text)
    else:  # pragma: no cover
        widget.log(text)


# ---------------- TUI ----------------

class TUI(App):
    """Interactive terminal UI for agt."""

    CSS = """
    #main {
        height: 100%;
    }
    #history {
        height: 1fr;
        border: round $primary;
        padding: 1 1;
    }
    #status {
        dock: bottom;
        padding: 0 1;
        height: 1;
    }
    #input {
        dock: bottom;
    }
    #dropdown {
        dock: bottom;
        height: auto;
        max-height: 8;
        border: round $accent;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("enter", "send", "send"),
        ("ctrl+j", "newline", "newline"),
        ("escape", "cancel", "cancel/thinking"),
        ("tab", "complete", "complete"),
        ("ctrl+tab", "complete", "complete"),
        ("right", "complete_if_dropdown", "accept dropdown"),
        ("ctrl+l", "clear", "clear"),
        ("up", "dropdown_up", "select up"),
        ("down", "dropdown_down", "select down"),
    ]

    busy: bool = reactive(False)
    server_down: bool = reactive(False)
    prompt_tokens: int = reactive(0)
    completion_tokens: int = reactive(0)

    def __init__(
        self,
        client: WebAIClient,
        model: str = "gemini-2.0-flash",
        log_file: Optional[str] = None,
        **_ignore,   # swallow extra CLI kwargs (provider/stream/thinking/verbose/etc.)
    ) -> None:
        super().__init__()  # don't pass CLI kwargs to App
        self.client = client
        self.model = model

        # lifecycle / race guards
        self._mounted = False

        # dropdown state
        self._dropdown_mode: str = ""  # "slash" | "at" | ""
        self._at_prefix: str = ""
        self._slash_prefix: str = ""

        # streaming / cancel
        self._cancel_requested = False
        self._send_thread: Optional[threading.Thread] = None

        # logging
        self._log = logging.getLogger("agt.tui")
        self._configure_logging(log_file)

    # ---------- logging ----------
    def _configure_logging(self, log_file: Optional[str]) -> None:
        self._log.setLevel(logging.DEBUG)
        if log_file:
            abspath = os.path.abspath(log_file)
            if not any(
                isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == abspath
                for h in self._log.handlers
            ):
                fh = logging.FileHandler(abspath, encoding="utf-8")
                fh.setLevel(logging.DEBUG)
                fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s: %(message)s")
                fh.setFormatter(fmt)
                self._log.addHandler(fh)
        self._log.debug("==== agt.tui logger initialized ====")

    # ---------- compose / mount ----------
    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                _LogWidget(id="history"),
                ListView(id="dropdown"),
                Input(
                    placeholder="Type your message or @path/to/file (Tab to complete)  —  / for commands",
                    id="input",
                ),
                Label(self._status_text(), id="status"),
                id="main",
            )
        )

    def on_mount(self) -> None:
        self.query_one("#dropdown", ListView).display = False
        _log = self.query_one("#history", _LogWidget)
        _log_write(_log, "accepting edits (shift + tab to toggle)")
        # probe server
        ok, detail = (True, "unknown")
        try:
            ok, detail = self.client.health_detail()
        except Exception as e:  # pragma: no cover
            ok, detail = False, f"{type(e).__name__}: {e}"
        self.server_down = not ok
        self._log.debug("TUI mounted; probing server health…")
        self._log.debug("Server health: ok=%s detail=%s", ok, detail)
        self._mounted = True
        self._update_status()
        # focus input
        try:
            self.query_one(Input).focus()
        except Exception:  # pragma: no cover
            pass

    # ---------- status ----------
    def _status_text(self) -> str:
        parts = [
            f"model={self.model}",
            f"tokens: prompt={self.prompt_tokens}, completion={self.completion_tokens}",
        ]
        if self.busy:
            parts.append("[thinking…]")
        if self.server_down:
            parts.append("[SERVER DOWN]")
        return "  •  ".join(parts)

    def _update_status(self) -> None:
        # Guard: during early compose, status label may not exist yet
        try:
            self.query_one("#status", Label).update(self._status_text())
        except Exception:
            pass

    def watch_busy(self, busy: bool) -> None:
        if not self._mounted:
            return
        self._update_status()

    def watch_server_down(self, down: bool) -> None:
        if not self._mounted:
            return
        self._update_status()

    # ---------- dropdown helpers ----------
    def _update_dropdown(self, value: str, caret: int) -> None:
        dd = self.query_one("#dropdown", ListView)
        dd.clear()
        dd.display = False
        self._dropdown_mode = ""
        self._at_prefix = ""
        self._slash_prefix = ""

        # `/command` completion (only at line start)
        if value.startswith("/"):
            prefix = value[1:caret - 1 if caret > 1 else 1]
            self._slash_prefix = prefix
            matches = _filter_cmds(prefix)
            if matches:
                for name, desc in matches[:20]:
                    dd.append(ListItem(Static(f"[b]{name}[/b] — {desc}")))
                dd.index = 0
                dd.display = True
                self._dropdown_mode = "slash"
            return

        # `@path` completion — find last @ before caret
        left = value[:caret]
        m = re.search(r"@([^\s]*)$", left)
        if m:
            tail = m.group(1)
            self._at_prefix = tail
            base = os.path.expanduser(os.path.expandvars(tail or "."))
            dirname = base if base.endswith(os.sep) else (os.path.dirname(base) or ".")
            try:
                for entry in sorted(os.listdir(dirname))[:200]:
                    cand = os.path.join(dirname, entry)
                    if tail and not cand.startswith(base):
                        continue
                    label = cand + (os.sep if os.path.isdir(cand) else "")
                    dd.append(ListItem(Static(label)))
                if dd.children:
                    dd.index = 0
                    dd.display = True
                    self._dropdown_mode = "at"
            except Exception as e:
                self._log.debug("dropdown os.listdir error for %r: %s", dirname, e)

    # ---------- input events ----------
    @on(Input.Changed)
    def _on_input_changed(self, ev: Input.Changed) -> None:
        # Some Textual builds omit cursor_position on Changed; fall back gracefully.
        caret = getattr(ev, "cursor_position", None)
        if caret is None:
            caret = getattr(ev, "caret_position", None)
        if caret is None:
            caret = len(ev.value)
        self._log.debug("input changed; caret=%s value=%r", caret, ev.value)
        self._update_dropdown(ev.value, int(caret))

    @on(Input.Submitted)
    def _on_input_submitted(self, _ev: Input.Submitted) -> None:
        # Ensure Enter sends even if Input consumes the key.
        self.action_send()

    # Intercept keys so Tab does NOT move focus when dropdown is open,
    # and Right Arrow can accept completion.
    def on_key(self, event: Key) -> None:  # type: ignore[override]
        try:
            dd = self.query_one("#dropdown", ListView)
        except Exception:
            dd = None
        if event.key == "tab":
            if dd and dd.display and dd.children:
                event.stop()
                self.action_complete()
        elif event.key == "ctrl+tab":
            if dd and dd.display and dd.children:
                event.stop()
                self.action_complete()
        elif event.key == "right":
            if dd and dd.display and dd.children:
                event.stop()
                self.action_complete()

    # ---------- actions ----------
    def action_newline(self) -> None:
        # Insert newline at caret (works across Textual versions)
        inp = self.query_one(Input)
        val = inp.value
        pos = getattr(inp, "cursor_position", len(val))
        new_val = (val[:pos] if pos else val) + "\n" + (val[pos:] if pos is not None else "")
        inp.value = new_val
        try:
            inp.cursor_position = (pos or 0) + 1
        except Exception:
            pass

    def action_clear(self) -> None:
        h = self.query_one("#history", _LogWidget)
        try:
            h.clear()
        except Exception:  # pragma: no cover
            _log_write(h, "\n" * 50)
        self._update_status()

    def action_cancel(self) -> None:
        # Request cancel of an in-flight stream
        self._cancel_requested = True
        self.busy = False
        self._update_status()

    def action_dropdown_up(self) -> None:
        dd = self.query_one("#dropdown", ListView)
        if dd.display and dd.children:
            try:
                dd.index = max(0, dd.index - 1)
            except Exception:  # pragma: no cover
                pass

    def action_dropdown_down(self) -> None:
        dd = self.query_one("#dropdown", ListView)
        if dd.display and dd.children:
            try:
                dd.index = min(len(dd.children) - 1, dd.index + 1)
            except Exception:  # pragma: no cover
                pass

    def action_complete_if_dropdown(self) -> None:
        dd = self.query_one("#dropdown", ListView)
        if dd.display and dd.children:
            self.action_complete()

    def action_complete(self) -> None:
        dd = self.query_one("#dropdown", ListView)
        if not dd.display or not dd.children:
            return
        selected = dd.index or 0
        # Extract text from the ListItem -> Static
        try:
            text = str(dd.children[selected].query_one(Static).renderable)
        except Exception:  # pragma: no cover
            text = ""
        if not text:
            return
        inp = self.query_one(Input)
        val = inp.value
        caret = inp.cursor_position

        if self._dropdown_mode == "slash":
            new = "/" + text.split(" —", 1)[0]
            newval = new + val[caret:]
            inp.value = newval
            inp.cursor_position = len(new)
            dd.display = False

        elif self._dropdown_mode == "at":
            left = val[:caret]
            right = val[caret:]
            left = re.sub(r"@([^\s]*)$", "@" + text, left)
            inp.value = left + right
            inp.cursor_position = len(left)
            if text.endswith(os.sep):
                self._update_dropdown(inp.value, inp.cursor_position)
            else:
                dd.display = False

    # ---------- send ----------
    def _append_history(self, text: str) -> None:
        _log_write(self.query_one("#history", _LogWidget), text)

    def _render_ingest_summary(self, files: List[Path]) -> str:
        if not files:
            return ""
        lines = []
        lines.append("✓ ReadManyFiles will attempt to read and concatenate…\n")
        lines.append("### ReadManyFiles Result\n")
        lines.append(f"Successfully read and concatenated content from **{len(files)} file(s)**.\n")
        lines.append("**Processed Files:**")
        for fp in files[:50]:
            lines.append(f"- `{fp.as_posix()}`")
        if len(files) > 50:
            lines.append(f"- …(+{len(files)-50} more)")
        lines.append("")
        return "\n".join(lines)

    def _extract_at_refs(self, text: str) -> Tuple[str, List[Path]]:
        refs = re.findall(r"@([^\s]+)", text)
        files: List[Path] = []
        for r in refs:
            files.extend(_files_from_at_expr(r))
        cleaned = re.sub(r"@([^\s]+)", "", text).strip()
        return cleaned, files

    def _handle_slash_local(self, text: str) -> bool:
        """Return True if the slash command was handled locally."""
        cmd = text.strip().split()[0].lstrip("/")
        if cmd == "help":
            items = "\n".join([f"- /{name} — {desc}" for name, desc in _SLASH_COMMANDS])
            self._append_history("### Commands\n\n" + items + "\n")
            return True
        if cmd == "about":
            self._append_history("**agt** TUI — Textual UI for WebAI-to-API\n")
            return True
        if cmd == "clear":
            self.action_clear()
            return True
        return False

    def action_send(self) -> None:
        inp = self.query_one(Input)
        text = inp.value.strip()
        if not text:
            return

        # slash commands handled locally
        if text.startswith("/") and self._handle_slash_local(text):
            inp.value = ""
            self.query_one("#dropdown", ListView).display = False
            return

        # show user message
        self._append_history(f"> {text}\n")
        self._log.debug("send: %r", text)

        # collect @file/@dir/glob attachments
        clean_text, files = self._extract_at_refs(text)
        attach_blobs: List[str] = []
        for fp in files:
            attach_blobs.append(f"\n\n# File: {fp.name}\n```\n{_safe_read_file(fp)}\n```")
        messages = [{"role": "user", "content": clean_text + "".join(attach_blobs)}]

        # thinking + stream in background
        self.busy = True
        self._cancel_requested = False
        self._update_status()
        if files:
            self._append_history(self._render_ingest_summary(files))
        self._append_history("**Assistant**\n\n_Thinking…_\n")

        def _worker():
            try:
                for event in self.client.chat_stream_events(messages, model=self.model):
                    if self._cancel_requested:
                        break
                    et = event.get("event")
                    if et == "content":
                        chunk = event.get("text", "")
                        self.call_from_thread(self._append_history, chunk)
                    elif et == "usage":
                        usage = event.get("usage", {})
                        self.prompt_tokens = int(usage.get("prompt_tokens", self.prompt_tokens))
                        self.completion_tokens = int(usage.get("completion_tokens", self.completion_tokens))
                        self.call_from_thread(self._update_status)
            except Exception as e:
                self._log.exception("send error")
                self.call_from_thread(self._append_history, f"\n\n❌ Error: {type(e).__name__}: {e}\n")
            finally:
                self.busy = False
                self.call_from_thread(self._update_status)
                # reset input & dropdown in UI thread
                def _reset():
                    inp.value = ""
                    self.query_one("#dropdown", ListView).display = False
                self.call_from_thread(_reset)

        self._send_thread = threading.Thread(target=_worker, daemon=True)
        self._send_thread.start()
