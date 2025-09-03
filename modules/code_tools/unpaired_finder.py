# File: scripts/modules/code_tools/unpaired_finder.py
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

OPENERS = "([{"
CLOSERS = ")]}"
PAIR = {')': '(', ']': '[', '}': '{'}

@dataclass
class BraceIssue:
    kind: str
    line: int
    col: int
    got: str
    expected: str | None = None

def scan_text_for_unpaired(text: str) -> Tuple[List[BraceIssue], List[int]]:
    issues: List[BraceIssue] = []
    stack: List[Tuple[str, int, int]] = []
    line = 1; col = 0
    for ch in text:
        if ch == '\n':
            line += 1; col = 0; continue
        col += 1
        if ch in OPENERS:
            stack.append((ch, line, col))
        elif ch in CLOSERS:
            if not stack:
                issues.append(BraceIssue('unpaired_close', line, col, ch))
            else:
                open_ch, open_line, open_col = stack.pop()
                if PAIR[ch] != open_ch:
                    issues.append(BraceIssue('mismatch', line, col, ch, PAIR[ch]))
    unpaired_open_lines = sorted({ln for _, ln, _ in stack})
    for open_ch, ln, c in stack:
        issues.append(BraceIssue('unpaired_open', ln, c, open_ch))
    return issues, unpaired_open_lines

def scan_file_for_unpaired(path: Path) -> Tuple[List[BraceIssue], List[int]]:
    text = path.read_text(encoding='utf-8', errors='ignore')
    return scan_text_for_unpaired(text)

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Find unpaired/mismatched braces in a file.")
    ap.add_argument("file")
    args = ap.parse_args(argv)
    try:
        issues, unpaired_open_lines = scan_file_for_unpaired(Path(args.file))
        if not issues:
            print("No brace issues found."); return 0
        for iss in issues:
            if iss.kind == 'mismatch' and iss.expected:
                print(f"Mismatch at {iss.line}:{iss.col}: got '{iss.got}', expected closing for '{iss.expected}'.")
            elif iss.kind == 'unpaired_close':
                print(f"Unpaired close at {iss.line}:{iss.col}: '{iss.got}'.")
            elif iss.kind == 'unpaired_open':
                print(f"Unpaired open at {iss.line}:{iss.col}: '{iss.got}'.")
        if unpaired_open_lines:
            print("Lines with unpaired openings: " + ", ".join(map(str, unpaired_open_lines)))
        return 1
    except FileNotFoundError:
        print("[ERROR] File not found."); return 2
    except Exception as e:
        print(f"[ERROR] {e}"); return 3

if __name__ == "__main__":
    raise SystemExit(main())
