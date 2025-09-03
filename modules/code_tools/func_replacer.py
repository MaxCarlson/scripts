# File: scripts/modules/code_tools/func_replacer.py
from __future__ import annotations

import argparse
import shutil
import sys
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import pyperclip  # optional
except Exception:
    pyperclip = None  # type: ignore

from .rgcodeblock_lib.language_defs import get_language_type_from_filename
from .rgcodeblock_lib import (
    extract_python_block_ast,
    extract_brace_block,
    extract_json_block,
    extract_yaml_block,
    extract_xml_block,
    extract_ruby_block,
    extract_lua_block,
)

@dataclass
class ReplacePlan:
    target_path: Path
    backup_path: Optional[Path]
    start_line: int
    end_line: int
    new_block: str
    detected_name: Optional[str]
    language: str

def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")

def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")

def _infer_name_from_block(code: str, language: str) -> Optional[str]:
    first_nonempty = None
    for ln in code.splitlines():
        s = ln.strip()
        if s:
            first_nonempty = s; break
    if not first_nonempty:
        return None
    if language == "python":
        m = re.match(r"(async\s+def|def)\s+([A-Za-z_][\w]*)\s*\(", first_nonempty)
        if m: return m.group(2)
        m = re.match(r"class\s+([A-Za-z_][\w]*)\s*\(", first_nonempty)
        if m: return m.group(1)
    elif language == "ruby":
        m = re.match(r"def\s+([A-Za-z_][\w!?=]*)", first_nonempty)
        if m: return m.group(1)
        m = re.match(r"class\s+([A-Za-z_][\w:]*)", first_nonempty)
        if m: return m.group(1)
    elif language == "lua":
        m = re.match(r"function\s+([A-Za-z_][\w\.:]*)\s*\(", first_nonempty)
        if m: return m.group(1)
    elif language == "brace":
        m = re.search(r"\b([A-Za-z_][\w:]*)\s*\(.*\)\s*\{", code)
        if m: return m.group(1)
        m = re.search(r"\bclass\s+([A-Za-z_][\w:]*)\s*\{", code)
        if m: return m.group(1)
    return None

def _find_block_range(text: str, language: str, *, name: Optional[str], line: Optional[int]):
    block = None
    if language == "python": block = extract_python_block_ast(text, name=name, line=line)
    elif language == "brace": block = extract_brace_block(text, name=name, line=line)
    elif language == "json": block = extract_json_block(text, line=line)
    elif language == "yaml": block = extract_yaml_block(text, line=line, name=name)
    elif language == "xml": block = extract_xml_block(text, line=line, name=name)
    elif language == "ruby": block = extract_ruby_block(text, line=line, name=name)
    elif language == "lua": block = extract_lua_block(text, line=line, name=name)
    if block:
        return block.start, block.end, block.name
    return None

def _indent_of_line(text: str, line_no_1based: int) -> str:
    lines = text.splitlines()
    if 1 <= line_no_1based <= len(lines):
        ln = lines[line_no_1based - 1]
        return ln[: len(ln) - len(ln.lstrip())]
    return ""

def _reindent_block(block: str, indent: str) -> str:
    lines = block.splitlines()
    while lines and not lines[0].strip(): lines.pop(0)
    min_indent = None
    for ln in lines:
        if ln.strip():
            leading = len(ln) - len(ln.lstrip())
            min_indent = leading if min_indent is None else min(min_indent, leading)
    if min_indent is None: min_indent = 0
    normalized = [ln[min_indent:] if len(ln) >= min_indent else ln for ln in lines]
    return "\n".join((indent + ln if ln.strip() else ln) for ln in normalized)

def plan_replacement(target_path: Path, new_code: str, *, entity_name: Optional[str] = None, approx_line: Optional[int] = None,
                     backup: bool = True) -> ReplacePlan:
    target_text = _read_text(target_path)
    language, _ = get_language_type_from_filename(target_path)
    inferred = _infer_name_from_block(new_code, language) or entity_name
    rng = _find_block_range(target_text, language, name=inferred, line=approx_line)
    if not rng:
        raise ValueError(f"Could not locate target block in {target_path} using name={inferred!r} line={approx_line!r}")
    start, end, found_name = rng
    indent = _indent_of_line(target_text, start)
    reindented = _reindent_block(new_code, indent)
    backup_path = target_path.with_suffix(target_path.suffix + ".bak") if backup else None
    return ReplacePlan(target_path, backup_path, start, end, reindented, found_name or inferred, language)

def apply_replacement(plan: ReplacePlan, *, assume_yes: bool = False) -> None:
    content = _read_text(plan.target_path)
    lines = content.splitlines()
    before = lines[: plan.start_line - 1]
    after = lines[plan.end_line :]
    new_text = "\n".join(before + [plan.new_block] + after)
    if not assume_yes:
        print(f"About to replace lines {plan.start_line}-{plan.end_line} in {plan.target_path} (lang={plan.language}).\n"
              f"Detected entity: {plan.detected_name or '<unknown>'}. Proceed? [y/N] ", end="")
        ans = sys.stdin.readline().strip().lower()
        if ans not in {"y", "yes"}:
            print("Aborted.")
            return
    if plan.backup_path:
        shutil.copy2(plan.target_path, plan.backup_path)
    _write_text(plan.target_path, new_text)
    print(f"Replaced lines {plan.start_line}-{plan.end_line} in {plan.target_path}.")
    if plan.backup_path:
        print(f"Backup saved to {plan.backup_path}.")

def _read_source_code(args: argparse.Namespace) -> str:
    if args.source:
        p = Path(args.source)
        if not p.exists():
            raise FileNotFoundError(f"Source file not found: {p}")
        return _read_text(p)
    if pyperclip is None:
        raise RuntimeError("pyperclip not available. Install it or use --source to specify a file.")
    try:
        return pyperclip.paste()
    except Exception as e:
        raise RuntimeError(f"Failed to read clipboard: {e}")

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replace a function/class/block in a code file with new content.")
    ap.add_argument("target")
    ap.add_argument("-s", "--source")
    ap.add_argument("-n", "--entity_name")
    ap.add_argument("-l", "--line", type=int)
    ap.add_argument("-y", "--yes", action="store_true")
    ap.add_argument("-b", "--backup", action="store_true")
    ap.add_argument("-B", "--no-backup", dest="no_backup", action="store_true")
    args = ap.parse_args(argv)
    try:
        new_code = _read_source_code(args)
        backup = False if args.no_backup else True
        plan = plan_replacement(Path(args.target), new_code, entity_name=args.entity_name, approx_line=args.line, backup=backup)
        apply_replacement(plan, assume_yes=args.yes)
        return 0
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
