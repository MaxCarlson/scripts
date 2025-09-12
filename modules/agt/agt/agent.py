#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import difflib
import glob
import json
import platform
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# -------- Attachments (@path / globs) --------
def expand_attachments(user_text: str) -> Tuple[str, List[Tuple[str, str]]]:
    attachments: List[Tuple[str, str]] = []

    def repl(match: re.Match) -> str:
        token = match.group(0)
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
        return ""

    cleaned = re.sub(r"@[\w\-/\\\.\*\?\[\]\{\}]+", repl, user_text)
    return cleaned.strip(), attachments


def build_prompt_with_attachments(text: str, atts: List[Tuple[str, str]]) -> str:
    if not atts:
        return text
    parts: List[str] = [text, "", "### Attachments"]
    for fp, content in atts:
        parts.append("\n---\n[FILE] " + fp + "\n" + "BEGIN_FILE\n" + content + "\nEND_FILE")
    return "\n".join(parts)


# -------- Tool block parsing (supports ```tool and [[tool]]) --------
BACKTICKS = "`" * 3
TOOL_BLOCK_RE = re.compile(
    rf"{re.escape(BACKTICKS)}tool\s+([\s\S]*?){re.escape(BACKTICKS)}", re.IGNORECASE
)
ALT_TOOL_BLOCK_RE = re.compile(r"\[\[tool\]\]\s*([\s\S]*?)\s*\[\[/tool\]\]", re.IGNORECASE)


def parse_tools(text: str) -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []
    for m in TOOL_BLOCK_RE.finditer(text or ""):
        blob = m.group(1).strip()
        try:
            tools.append(json.loads(blob))
        except Exception:
            pass
    for m in ALT_TOOL_BLOCK_RE.finditer(text or ""):
        blob = m.group(1).strip()
        try:
            tools.append(json.loads(blob))
        except Exception:
            pass
    return tools


PermissionPrompt = Callable[[str, str], bool]


def _confirm_default(_: str, __: str) -> bool:
    return False


def run_tool_write_file(path: str, content: str, ask: PermissionPrompt = _confirm_default) -> str:
    p = Path(path)
    summary = f"write_file → {p} ({len(content)} bytes)"
    if not ask("write_file", summary):
        return "Denied write_file."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {p}"


def run_tool_edit_file(path: str, new_content: str, ask: PermissionPrompt = _confirm_default) -> str:
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
    preview = diff[:10000] or "(no changes)"
    if not ask("edit_file", f"edit_file → {p}\n{preview}"):
        return "Denied edit_file."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new_content, encoding="utf-8")
    return f"Updated {p}"


def run_tool_run(cmd: str, ask: PermissionPrompt = _confirm_default) -> str:
    if platform.system().lower().startswith("win"):
        full = ["pwsh", "-NoLogo", "-NoProfile", "-Command", cmd]
        nice = f"pwsh -NoProfile -Command {cmd}"
    else:
        full = ["/bin/bash", "-lc", cmd]
        nice = f"/bin/bash -lc {cmd}"
    if not ask("run", f"run → {nice}"):
        return "Denied run."
    try:
        proc = subprocess.run(full, capture_output=True, text=True, timeout=3600)
        return f"exit={proc.returncode}\n[stdout]\n{proc.stdout}\n[stderr]\n{proc.stderr}"
    except Exception as e:
        return f"run failed: {e}"


def apply_tools(text: str, ask: PermissionPrompt = _confirm_default) -> List[str]:
    outcomes: List[str] = []
    for t in parse_tools(text):
        name = t.get("tool")
        if name == "write_file":
            outcomes.append(run_tool_write_file(t.get("path", "out.txt"), t.get("content", ""), ask))
        elif name == "edit_file":
            outcomes.append(run_tool_edit_file(t.get("path", "file.txt"), t.get("patch", ""), ask))
        elif name == "run":
            outcomes.append(run_tool_run(t.get("cmd", ""), ask))
    return outcomes


def extract_reasoning(resp_obj: Dict[str, Any]) -> str | None:
    try:
        ch = resp_obj.get("choices", [{}])[0]
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

