# file: agt/tools.py
from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------- Permission registry ----------------

@dataclass
class SubjectPolicy:
    """Per-subject policy, e.g. per path or per program name."""
    always: bool = False


@dataclass
class ToolPolicy:
    """Per-tool registry of subject -> policy."""
    subjects: Dict[str, SubjectPolicy] = field(default_factory=dict)

    def is_allowed(self, subject: str) -> bool:
        pol = self.subjects.get(subject)
        return bool(pol and pol.always)

    def allow_always(self, subject: str) -> None:
        self.subjects.setdefault(subject, SubjectPolicy()).always = True


@dataclass
class PermissionRegistry:
    """Holds allow-always decisions for this chat/session."""
    edit_file: ToolPolicy = field(default_factory=ToolPolicy)
    run_command: ToolPolicy = field(default_factory=ToolPolicy)
    browse_url: ToolPolicy = field(default_factory=ToolPolicy)

    def tool_policy(self, tool_name: str) -> ToolPolicy:
        if tool_name == "edit_file":
            return self.edit_file
        if tool_name == "run_command":
            return self.run_command
        if tool_name == "browse_url":
            return self.browse_url
        raise KeyError(f"unknown tool {tool_name}")


# ---------------- File editing ----------------

def write_text_file(path: str | Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def read_text_file(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _parse_unified_diff(diff_text: str) -> List[Tuple[str, str]]:
    """
    Parse a minimal subset of unified diff and return list of (path, patch_for_that_path).
    We keep per-file chunks grouped by '--- a/..' '+++ b/..'. Caller applies each one.
    This is intentionally lightweight (best-effort). If parsing fails, return empty.
    """
    files: List[Tuple[str, str]] = []
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("--- "):
            # path on '+++ ' line wins (destination)
            src = lines[i][4:].strip()
            i += 1
            if i < len(lines) and lines[i].startswith("+++ "):
                dst = lines[i][4:].strip()
                # normalize 'a/foo'/'b/foo' → 'foo'
                def norm(s: str) -> str:
                    s = s.split("\t", 1)[0]
                    s = s.strip()
                    if s.startswith("a/") or s.startswith("b/"):
                        s = s[2:]
                    return s
                path = norm(dst) or norm(src)
                # collect until next file or end
                start = i - 1  # keep the ---/+++ and hunks
                i += 1
                while i < len(lines) and not lines[i].startswith("--- "):
                    i += 1
                chunk = "\n".join(lines[start:i]) + "\n"
                files.append((path, chunk))
            else:
                # malformed; skip
                i += 1
        else:
            i += 1
    return files


def _apply_one_unified_patch(original: str, patch: str) -> Optional[str]:
    """
    Very small/forgiving unified diff applier:
    - Supports @@ -l,c +l,c @@ hunks
    - Accepts context but doesn't strictly validate counts
    On failure returns None.
    """
    out: List[str] = original.splitlines(keepends=False)
    patch_lines = patch.splitlines()
    i = 0
    # Skip the +++/--- headers if present
    while i < len(patch_lines) and not patch_lines[i].startswith("@@"):
        i += 1

    def parse_range(spec: str) -> Tuple[int, int]:
        # "-12,3" or "+12,3" or "-12" → (start, count)
        spec = spec.strip()
        if spec[0] in "+-":
            spec = spec[1:]
        if "," in spec:
            a, b = spec.split(",", 1)
            return int(a), int(b)
        return int(spec), 1

    cursor = 0
    while i < len(patch_lines):
        if not patch_lines[i].startswith("@@"):
            # malformed
            return None
        # @@ -l,c +l,c @@ optional text
        m = re.match(r"@@\s+(-\d+(?:,\d+)?)\s+\+(\d+(?:,\d+)?)\s+@@", patch_lines[i])
        if not m:
            return None
        _src, dst = m.groups()
        dst_start, _dst_count = parse_range(dst)
        # Move cursor to dst_start-1 (convert to 0-based)
        cursor = dst_start - 1
        i += 1
        # Collect hunk operations
        while i < len(patch_lines) and not patch_lines[i].startswith("@@"):
            line = patch_lines[i]
            if not line:
                i += 1
                continue
            tag = line[0]
            payload = line[1:] if len(line) > 0 else ""
            if tag == " ":
                # context line, accept and advance
                cursor += 1
            elif tag == "+":
                out.insert(cursor, payload)
                cursor += 1
            elif tag == "-":
                # delete at cursor (if matching, otherwise best-effort drop)
                if 0 <= cursor < len(out):
                    out.pop(cursor)
                # do not advance cursor
            else:
                # unknown marker → fail
                return None
            i += 1
    return "\n".join(out) + ("\n" if original.endswith("\n") else "")


def apply_unified_diff(diff_text: str, root: str | Path = ".") -> List[Tuple[str, bool, Optional[str]]]:
    """
    Apply a unified diff to files under root.
    Returns list of tuples: (path, ok, error_message)
    """
    results: List[Tuple[str, bool, Optional[str]]] = []
    root = str(root)
    for rel_path, patch in _parse_unified_diff(diff_text):
        p = Path(root) / rel_path
        if p.exists():
            original = p.read_text(encoding="utf-8")
        else:
            original = ""
        new_text = _apply_one_unified_patch(original, patch)
        if new_text is None:
            results.append((rel_path, False, "patch failed"))
            continue
        write_text_file(p, new_text)
        results.append((rel_path, True, None))
    return results


# ---------------- Command / URL tools ----------------

def run_command(cmd: str, cwd: Optional[str] = None, timeout: Optional[int] = None) -> Tuple[int, str, str]:
    """
    Run a shell command. Returns (exit_code, stdout, stderr).
    """
    args = cmd if isinstance(cmd, str) else shlex.join(cmd)
    proc = subprocess.Popen(
        args, shell=True, cwd=cwd or os.getcwd(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return 124, out, err or "timeout"
    return proc.returncode, out, err


def browse_url(url: str) -> Tuple[bool, str]:
    """
    Open a URL with the best available opener on this system.
    Termux: termux-open-url ; Linux: xdg-open ; macOS: open ; Windows: start
    """
    candidates = [
        ("termux-open-url", f"termux-open-url {shlex.quote(url)}"),
        ("xdg-open", f"xdg-open {shlex.quote(url)}"),
        ("open", f"open {shlex.quote(url)}"),
        ("start", f'start "" {shlex.quote(url)}'),
    ]
    for exe, cmd in candidates:
        if shutil_which(exe):
            code, out, err = run_command(cmd)
            ok = (code == 0)
            return ok, out if ok else (err or out)
    return False, "no opener available"


def shutil_which(exe: str) -> bool:
    from shutil import which
    return which(exe) is not None
