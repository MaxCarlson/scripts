"""Searchable command metadata for system_manager."""

from __future__ import annotations

import difflib
import re
from typing import Dict, List


COMMANDS: List[Dict[str, str]] = [
    {
        "command": "sm proc find",
        "description": "Find processes by name, command line, executable path, regex, or fuzzy match.",
        "example": "sm proc find -q gemini -C --cmdline",
    },
    {
        "command": "sm proc tree",
        "description": "Show a process subtree rooted at a PID.",
        "example": "sm proc tree -p 76028",
    },
    {
        "command": "sm proc parents",
        "description": "Show the parent chain for a process.",
        "example": "sm proc parents -p 77828",
    },
    {
        "command": "sm proc children",
        "description": "Show child processes for a PID, optionally recursive.",
        "example": "sm proc children -p 76028 -R --recursive",
    },
    {
        "command": "sm proc pause",
        "description": "Suspend one or more matched processes.",
        "example": "sm proc pause -q gemini -C --cmdline",
    },
    {
        "command": "sm proc resume",
        "description": "Resume one or more suspended processes.",
        "example": "sm proc resume -q gemini -C --cmdline",
    },
    {
        "command": "sm proc stop",
        "description": "Terminate matched processes after confirmation.",
        "example": "sm proc stop -q gemini -C --cmdline -y --confirm",
    },
    {
        "command": "sm proc kill",
        "description": "Force-kill matched processes after confirmation.",
        "example": "sm proc kill -p 34944 -F --force -y --confirm",
    },
    {
        "command": "sm proc stop-tree",
        "description": "Terminate a process subtree child-first after confirmation.",
        "example": "sm proc stop-tree -p 76028 -y --confirm",
    },
    {
        "command": "sm proc restart",
        "description": "Restart a matched process from its command line after confirmation.",
        "example": "sm proc restart -p 34944 -y --confirm",
    },
    {
        "command": "sm proc stats",
        "description": "Sample CPU, memory, IO, thread, per-core system CPU, and open-file roots for a process.",
        "example": "sm proc stats -p 34944 -i 1 --interval 1 -s 60 --samples 60",
    },
    {
        "command": "sm proc stats-tree",
        "description": "Sample aggregate resource usage for a process and descendants.",
        "example": "sm proc stats-tree -p 76028 -i 1 --interval 1 -s 60 --samples 60",
    },
    {
        "command": "sm help-search",
        "description": "Search system_manager command names, descriptions, and examples.",
        "example": "sm help-search -q pause -f --fuzzy",
    },
]


def search_commands(query: str, *, regex: bool = False, fuzzy: bool = False) -> List[Dict[str, str]]:
    """Search command metadata."""
    results = []
    for item in COMMANDS:
        text = f"{item['command']} {item['description']} {item['example']}"
        if regex and re.search(query, text, flags=re.IGNORECASE):
            results.append(item)
        elif query.lower() in text.lower():
            results.append(item)
        elif fuzzy and difflib.SequenceMatcher(None, query.lower(), text.lower()).ratio() >= 0.45:
            results.append(item)
    return results
