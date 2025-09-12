# Textual-based TUI for agt, with slash commands, @path completion,
# expandable dropdown, and robust status/logging.
from __future__ import annotations

import asyncio
import glob
import io
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple

from rich.markdown import Markdown
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, Label, ListItem, ListView, Static, TextLog

# ---- logging ---------------------------------------------------------------

LOG = logging.getLogger("agt.tui")
if not LOG.handlers:
    # If caller configured logging already, don't touch it.
    level = os.environ.get("AGT_TUI_LOGLEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s: %(message)s",
    )
LOG.debug("==== agt.tui logger initialized ====")

# ---- client (lazy import, avoid hard dependency at import time) ------------

DEFAULT_BASE = os.environ.get("WAI_API_URL", "http://localhost:6969")

try:
    from .client import WebAIClient  # type: ignore
except Exception:  # pragma: no cover - fallback stub
    WebAIClient = None  # will error at runtime if actually used


# ---- helpers ----------------------------------------------------------------


@dataclass
class IngestSpec:
    display: List[str]
    blocks: List[Tuple[str, str]]  # (path, text_content)


SLASH_COMMANDS: List[Tuple[str, str]] = [
    ("/help", "show help"),
    ("/clear", "clear the screen and conversation history"),
    ("/about", "show version info"),
]


def iter_path_candidates(prefix: str) -> Iterable[str]:
    """
    Return candidate paths for a partial after '@'.
    If a directory, append '/' to indicate that.
    """
    if prefix.startswith("~/"):
        base = Path.home() / prefix[2:]
    else:
        base = Path(prefix)

    # Expand parent and list entries
    parent = base.parent if base.name else base
    pattern = str((parent if parent.exists() else Path(".")) / (base.name + "*"))
    for p in sorted(glob.glob(pattern)):
        try:
            if os.path.isdir(p):
                yield p.rstrip(os.sep) + os.sep
            else:
                yield p
        except Exception:
            continue


def gather_ingest_from_tokens(message: str, cwd: Path | None = None) -> IngestSpec:
    """
    Find tokens that start with '@' and resolve them to files/folders.
    - '@file' ingests the file
    - '@dir/' ingests all files under dir recursively
    - globs like '@src/*.py' are supported
    """
    cwd = cwd or Path.cwd()
    display: List[str] = []
    blocks: List[Tuple[str, str]] = []

    for raw in message.split():
        if not raw.startswith("@"):
            continue
        pat = raw[1:]
        # If it's clearly a directory token with trailing slash, expand recursively
        candidates: List[str] = []
        if pat.endswith(os.sep) or pat.endswith("/"):
            root = (cwd / pat).expanduser()
            if root.is_dir():
                candidates = [str(p) for p in root.rglob("*") if p.is_file()]
        else:
            candidates = glob.glob(str((cwd / pat).expanduser()))

        for path in sorted(set(candidates)):
            try:
                p = Path(path)
                if p.is_file():
                    # Limit each file to ~100 KB
                    with io.open(p, "r", encoding="utf-8", errors="ignore") as fh:
                        text = fh.read(100_000)
                    display.append(str(p))
                    blocks.append((str(p), text))
            except Exception as e:  # keep UI resilient
                LOG.warning("Failed to read %s: %s", path, e)

    return IngestSpec(display=display, blocks=blocks)


def render_ingest_summary(ing: IngestSpec) -> str:
    if not ing.display:
        return ""
    lines = ["### Attached files", ""]
    for p in ing.display:
        lines.append(f"- `{p}`")
    lines.append("")
    return "\n".join(lines)


def render_ingest_blocks(ing: IngestSpec) -> str:
    if not ing.blocks:
        return ""
    out: List[str] = ["", "---"]
    for path, text in ing.blocks:
        out.append(f"#### BEGIN FILE: {path}")
        out.append("```text")
        out.append(text)
        out.append("```")
        out.append(f"#### END FILE: {path}")
        out.append("")
    out.append("---")
    return "\n".join(out)


# ---- TUI --------------------------------------------------------------------


class TUIApp(App):
    """Interactive chat UI with dropdown completion for '/' and '@'."""

    CSS = """
    #root {
        height: 100%;
    }
    #history {
        height: 1fr;
        border: tall $secondary;
        padding: 1 1;
    }
    #input-row {
        height: 3;
    }
    #status {
        padding-left: 1;
        color: $text-muted;
    }
    #dropdown {
        dock: bottom;
        height: auto;
        max-height: 12;
        border: round $accent;
        background: $panel;
        padding: 0;
        offset-y: -3;     /* hover over input */
        visibility: hidden;
    }
    """

    BINDINGS = [
        Binding("ctrl+j", "newline", "newline"),
        Binding("escape", "cancel", "cancel"),
    ]

    # reactive state
    busy: bool = reactive(False, init=False)
    server_down: bool = reactive(False, init=False)
    prompt_tokens: int = reactive(0, init=False)
    completion_tokens: int = reactive(0, init=False)

    def __init__(
        self, base_url: str | None = None, model: str = "gemini-2.0-flash"
    ) -> None:
        super().__init__()
        self.base_url = base_url or DEFAULT_BASE
        self.model = model
        self.client = None
        if WebAIClient:
            try:
                self.client = WebAIClient(self.base_url)
            except Exception as e:
                LOG.warning("Failed to construct WebAIClient: %s", e)

        # dropdown state
        self._dropdown_kind: Optional[str] = None  # "slash" | "at" | None
        self._dropdown_prefix: str = ""
        self._cancel_requested = False

    # ----- composition and mount -----

    def compose(self) -> ComposeResult:
        # Top status note
        yield Label("accepting edits (shift + tab to toggle)")

        # Conversation area
        with Vertical(id="root"):
            yield TextLog(id="history", highlight=True, markup=True, wrap=True)

            with Horizontal(id="input-row"):
                yield Input(
                    placeholder="Type your message or @path/to/file", id="input"
                )
                yield Label(self._status_text(), id="status")

        # Dropdown overlay (initially hidden)
        yield Static(id="dropdown")

    async def on_mount(self) -> None:
        self.query_one(Input).focus()
        LOG.debug("TUI mounted; probing server health…")
        ok, detail = (False, "no client")
        if self.client:
            try:
                ok, detail = self.client.health_detail()
            except Exception as e:
                ok, detail = False, f"health probe failed: {e}"
        self.server_down = not ok
        LOG.debug("Server health: ok=%s detail=%s", ok, detail)
        self._status_refresh()

    # ----- UI helpers -----

    def _status_text(self) -> str:
        parts = [
            f"model={self.model}",
            f"tokens: prompt={self.prompt_tokens}, completion={self.completion_tokens}",
        ]
        if self.busy:
            parts.append("[thinking…]")
        if self.server_down:
            parts.append("[SERVER?]")
        return "  •  ".join(parts)

    def _status_refresh(self) -> None:
        try:
            self.query_one("#status", Label).update(self._status_text())
        except Exception:
            pass

    def watch_busy(self, busy: bool) -> None:
        self._status_refresh()

    def watch_server_down(self, server_down: bool) -> None:
        self._status_refresh()

    def watch_prompt_tokens(self, _: int) -> None:
        self._status_refresh()

    def watch_completion_tokens(self, _: int) -> None:
        self._status_refresh()

    # ----- dropdown logic -----

    def _dropdown(self) -> Static:
        return self.query_one("#dropdown", Static)

    def _history(self) -> TextLog:
        return self.query_one("#history", TextLog)

    def _input(self) -> Input:
        return self.query_one("#input", Input)

    def _rebuild_dropdown(self, items: List[str]) -> None:
        dd = self._dropdown()
        dd.remove_children()
        if not items:
            dd.styles.visibility = "hidden"
            return
        lst = ListView(*[ListItem(Label(it)) for it in items])
        dd.mount(lst)
        dd.styles.visibility = "visible"

    def _hide_dropdown(self) -> None:
        dd = self._dropdown()
        dd.remove_children()
        dd.styles.visibility = "hidden"

    def _update_dropdown(self, text: str, cursor: int) -> None:
        """Recompute dropdown based on token at the cursor."""
        try:
            prefix_space = text[:cursor]
            token = prefix_space.split()[-1] if prefix_space.split() else ""
            items: List[str] = []

            if token.startswith("/"):
                self._dropdown_kind = "slash"
                self._dropdown_prefix = token
                items = [
                    cmd for (cmd, _desc) in SLASH_COMMANDS if cmd.startswith(token)
                ]
            elif token.startswith("@"):
                self._dropdown_kind = "at"
                self._dropdown_prefix = token
                raw = token[1:]
                items = ["@" + p for p in iter_path_candidates(raw)]
            else:
                self._dropdown_kind = None
                self._dropdown_prefix = ""
                self._hide_dropdown()
                return

            self._rebuild_dropdown(items)
        except Exception as e:
            LOG.exception("_update_dropdown failed: %s", e)
            self._hide_dropdown()

    # ----- events -----

    def action_newline(self) -> None:
        """Insert newline into the input."""
        inp = self._input()
        val = inp.value
        cur = getattr(inp, "cursor_position", len(val))
        inp.value = val[:cur] + "\n" + val[cur:]
        inp.cursor_position = cur + 1

    def action_cancel(self) -> None:
        """Cancel any in-flight streaming."""
        self._cancel_requested = True
        self.busy = False
        self._status_refresh()

    @on(Input.Changed)
    def on_input_changed(self, ev: Input.Changed) -> None:
        """Update dropdown on every keystroke."""
        try:
            inp = self._input()
            cursor = getattr(inp, "cursor_position", None)
            if cursor is None:
                cursor = getattr(ev, "caret_position", 0)  # some Textual builds
            self._update_dropdown(ev.value, int(cursor or 0))
        except Exception as e:
            LOG.exception("on_input_changed failed: %s", e)

    @on(Input.Submitted)
    async def on_input_submitted(self, ev: Input.Submitted) -> None:
        text = ev.value.strip()
        if not text:
            return
        # Handle slash commands locally
        if text.startswith("/"):
            handled = await self._handle_slash(text)
            if handled:
                self._input().value = ""
                self._hide_dropdown()
                return

        await self._send_message(text)
        self._input().value = ""
        self._hide_dropdown()

    @on(ListView.Selected)
    async def on_list_view_selected(self, ev: ListView.Selected) -> None:
        """Insert the selected dropdown item at the cursor."""
        try:
            lbl = ev.item.query_one(Label)
            selection = str(getattr(lbl, "renderable", "")).strip()
            if not selection:
                return
            inp = self._input()
            text = inp.value
            cursor = int(getattr(inp, "cursor_position", len(text)))
            before = text[:cursor]
            # Replace current token
            token = before.split()[-1] if before.split() else ""
            start = cursor - len(token)
            new_value = text[:start] + selection + text[cursor:]
            inp.value = new_value
            inp.cursor_position = start + len(selection)
            self._hide_dropdown()
            LOG.debug("Dropdown insert: %r", selection)
        except Exception as e:
            LOG.exception("on_list_view_selected failed: %s", e)

    # ----- high level actions -----

    async def _handle_slash(self, text: str) -> bool:
        cmd = text.strip().split()[0]
        hist = self._history()

        if cmd == "/help":
            items = "\n".join([f"- {c} — {d}" for (c, d) in SLASH_COMMANDS])
            hist.write(Markdown(f"### Commands\n\n{items}"))
            return True

        if cmd == "/about":
            hist.write(Markdown("**agt** TUI • Textual UI for WebAI-to-API"))
            return True

        if cmd == "/clear":
            hist.clear()
            return True

        return False

    async def _send_message(self, text: str) -> None:
        """Send a message to the server; stream result to the history."""
        hist = self._history()

        # Ingest files referenced with '@'
        ingest = gather_ingest_from_tokens(text)
        preface = render_ingest_summary(ingest) + render_ingest_blocks(ingest)
        full_prompt = text
        if preface:
            full_prompt = f"{text}\n\n{preface}"

        # Show user message
        hist.write(Markdown(f"**You**\n\n{Text.from_markup(full_prompt)}"))
        self.busy = True
        self._cancel_requested = False

        if not self.client:
            hist.write(Markdown("_No client available; cannot contact server._"))
            self.busy = False
            return

        try:
            # Stream events (the client returns a simple two-event sequence if streaming unsupported)
            content_chunks: List[str] = []
            hist.write(Markdown("**Assistant**\n\n_Thinking…_"))
            async for event in self._stream_events_async(full_prompt):
                if self._cancel_requested:
                    break
                if event.get("event") == "content":
                    content_chunks.append(event.get("text", ""))
                    # Update last line
                    hist.write(Markdown("".join(content_chunks)))
                elif event.get("event") == "usage":
                    usage = event.get("usage", {})
                    self.prompt_tokens = int(
                        usage.get("prompt_tokens", self.prompt_tokens)
                    )
                    self.completion_tokens = int(
                        usage.get("completion_tokens", self.completion_tokens)
                    )
            self.busy = False
        except Exception as e:
            LOG.exception("Chat failed: %s", e)
            self.busy = False
            hist.write(Markdown(f"_Error: {e}_"))

    async def _stream_events_async(self, prompt: str) -> Iterator[dict]:
        """
        Async wrapper around the sync client to keep the UI responsive.
        """
        loop = asyncio.get_running_loop()

        def _sync_iter():
            try:
                msgs = [{"role": "user", "content": prompt}]
                for ev in self.client.chat_stream_events(msgs, model=self.model):  # type: ignore[attr-defined]
                    yield ev
            except Exception as e:
                LOG.exception("stream failed: %s", e)
                yield {"event": "content", "text": f"(stream error: {e})"}
                yield {"event": "done"}

        it = _sync_iter()

        # Bridge a blocking iterator into async iteration
        while True:
            ev = await loop.run_in_executor(None, lambda: next(it, None))
            if ev is None:
                break
            yield ev


# ---- convenience runner ------------------------------------------------------


def run_tui(base_url: Optional[str] = None, model: str = "gemini-2.0-flash") -> None:
    """Entry point used by CLI."""
    app = TUIApp(base_url=base_url or DEFAULT_BASE, model=model)
    app.run()
