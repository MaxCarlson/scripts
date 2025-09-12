# agt/completion.py
from __future__ import annotations
import os, glob
from pathlib import Path
from typing import Iterable, List, Tuple

from prompt_toolkit.completion import Completer, Completion

SLASH_COMMANDS: List[Tuple[str, str]] = [
    ("/help", "show help"),
    ("/new", "start a new conversation"),
    ("/models", "list server models (if supported)"),
    ("/providers", "list server providers (if supported)"),
    ("/set", "set model/provider:  /set model <m> | /set provider <p>"),
    ("/save", "save chat to JSONL: /save path.jsonl"),
    ("/load", "load chat from JSONL: /load path.jsonl"),
    ("/cp", "copy last result to clipboard: /cp [n]"),
    ("/stats", "show token stats"),
    ("/quit", "exit"),
]

class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return
        prefix = text
        for cmd, desc in SLASH_COMMANDS:
            if cmd.startswith(prefix):
                yield Completion(
                    cmd,
                    start_position=-len(prefix),
                    display=cmd,
                    display_meta=desc,
                )

def _iter_path_candidates(prefix: str) -> Iterable[str]:
    """Yield file/dir candidates for a path-like prefix."""
    # Expand ~
    if prefix.startswith("~"):
        prefix = os.path.expanduser(prefix)

    # If it's a directory, list inside; otherwise glob
    p = Path(prefix)
    if p.is_dir():
        for child in sorted(p.iterdir()):
            yield str(child) + (os.sep if child.is_dir() else "")
        return

    # Try globbing (supports **)
    # If user typed nothing after @, offer current dir files
    pattern = prefix if prefix else "*"
    for match in sorted(glob.iglob(pattern, recursive=True)):
        m = Path(match)
        yield str(m) + (os.sep if m.is_dir() else "")

class AtPathCompleter(Completer):
    """Complete @path … including folders and globs."""
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        # Find the last token that begins with '@'
        # Split on whitespace; support multi-line
        tokens = text.split()
        if not tokens:
            return
        last = tokens[-1]
        if not last.startswith("@"):
            return
        raw = last[1:]
        for cand in _iter_path_candidates(raw):
            # Replace just the @token
            yield Completion(
                "@" + cand,
                start_position=-(len(last)),
                display="@" + cand,
                display_meta="path",
            )

class CombinedCompleter(Completer):
    def __init__(self):
        self._slash = SlashCompleter()
        self._at = AtPathCompleter()
    def get_completions(self, document, complete_event):
        # Try slash first
        for c in self._slash.get_completions(document, complete_event) or []:
            yield c
        # Then @path
        for c in self._at.get_completions(document, complete_event) or []:
            yield c
