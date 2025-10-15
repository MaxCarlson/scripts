#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import json
import queue
import threading
import time
from pathlib import Path
from typing import Dict, Generator, Iterable, Optional, TextIO

from .aebndl import parse_line as parse_aebndl_line
from .yt_dlp import parse_line as parse_ytdlp_line
from .rsync import parse_line as parse_rsync_line
from .rclone import parse_line as parse_rclone_line
from .scp import parse_line as parse_scp_line
from .utils import sanitize_line

Parser = callable

def _reader_to_queue(f: TextIO, q: "queue.Queue[str]", stop: threading.Event) -> None:
    """
    Read character-by-character so we see carriage-returns too.
    Push chunks terminated by either '\n' or '\r' into the queue.
    """
    buf: list[str] = []
    try:
        while not stop.is_set():
            ch = f.read(1)
            if not ch:
                # EOF; flush remaining buffer
                if buf:
                    q.put("".join(buf))
                    buf.clear()
                break
            if ch in ("\n", "\r"):
                buf.append(ch)
                q.put("".join(buf))
                buf.clear()
            else:
                buf.append(ch)
    except Exception:
        # On any I/O trouble, flush what we have so far
        if buf:
            q.put("".join(buf))

def _pick_parser(tool: str):
    if tool == "yt-dlp":
        return parse_ytdlp_line
    if tool == "aebndl":
        return parse_aebndl_line
    if tool == "rsync":
        return parse_rsync_line
    if tool == "rclone":
        return parse_rclone_line
    if tool == "scp":
        return parse_scp_line
    raise ValueError(f"Unknown tool '{tool}'")

def iter_parsed_events(
    tool: str,
    stream: TextIO,
    raw_log_path: Optional[Path] = None,
    heartbeat_secs: float = 0.5,
) -> Generator[Dict, None, None]:
    """
    Yield normalized event dicts for the given tool by watching the stream.
    Handles progress lines that only end with '\r' (no newline).

    Also yields a heartbeat if no other event arrived within `heartbeat_secs`:
      {'event':'heartbeat','tool':tool,'last_line': '...'}
    """
    parser = _pick_parser(tool)
    raw_f: Optional[TextIO] = None
    if raw_log_path:
        raw_log_path.parent.mkdir(parents=True, exist_ok=True)
        raw_f = raw_log_path.open("a", encoding="utf-8", buffering=1)

    q: "queue.Queue[str]" = queue.Queue()
    stop = threading.Event()
    t = threading.Thread(target=_reader_to_queue, args=(stream, q, stop), daemon=True)
    t.start()

    last_event_time = time.monotonic()
    last_line_text = ""
    try:
        while True:
            try:
                chunk = q.get(timeout=heartbeat_secs)
            except queue.Empty:
                # no new chunk -> heartbeat
                now = time.monotonic()
                if now - last_event_time >= heartbeat_secs:
                    yield {"event": "heartbeat", "tool": tool, "last_line": last_line_text}
                    last_event_time = now
                continue

            if raw_f:
                raw_f.write(chunk)

            # Treat both \r and \n as separators; sanitize
            s = sanitize_line(chunk)
            last_line_text = s

            evt = parser(s)
            if evt:
                yield evt
                last_event_time = time.monotonic()
    finally:
        stop.set()
        t.join(timeout=1)
        if raw_f:
            raw_f.flush()
            raw_f.close()

def events_to_ndjson(events: Iterable[Dict]) -> Iterable[str]:
    for e in events:
        yield json.dumps(e, ensure_ascii=False)
