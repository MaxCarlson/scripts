# File: scripts/modules/code_tools/rgcodeblock_cli.py
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

try:
    from .rgcodeblock_lib.language_defs import LANGUAGE_DEFINITIONS, get_language_type_from_filename
    from .rgcodeblock_lib import (
        extract_python_block_ast,
        extract_brace_block,
        extract_json_block,
        extract_yaml_block,
        extract_xml_block,
        extract_ruby_block,
        extract_lua_block,
    )
except ImportError:
    from rgcodeblock_lib.language_defs import LANGUAGE_DEFINITIONS, get_language_type_from_filename
    from rgcodeblock_lib import (
        extract_python_block_ast,
        extract_brace_block,
        extract_json_block,
        extract_yaml_block,
        extract_xml_block,
        extract_ruby_block,
        extract_lua_block,
    )

RESET = "\x1b[0m"; BOLD = "\x1b[1m"; RED = "\x1b[31m"

@dataclass
class MatchEvent:
    path: Path
    line_number: int
    lines_text: str
    submatches: List[Tuple[int, int, str]]

def run_ripgrep(pattern: str, path: str | Path, extra_args: List[str]) -> Iterator['MatchEvent']:
    if shutil.which("rg") is None:
        raise RuntimeError("ripgrep (rg) not found on PATH. Please install ripgrep.")
    cmd = ["rg", "--json", "-nH", pattern, str(path)] + (extra_args or [])
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line or not line.startswith("{"): continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "match":
            data = obj["data"]
            p = Path(data["path"]["text"])
            ln = data.get("line_number")
            ltxt = data["lines"]["text"]
            subs = []
            for sm in data.get("submatches", []):
                subs.append((sm["start"], sm["end"], sm["match"]["text"]))
            yield MatchEvent(path=p, line_number=ln, lines_text=ltxt, submatches=subs)

def highlight(text: str, needle: str) -> str:
    return text.replace(needle, f"{BOLD}{RED}{needle}{RESET}")

def extract_block_for_file(file_text: str, filename: Path, line_no: int) -> Tuple[int, int, str, str]:
    language, _ = get_language_type_from_filename(filename)
    block = None
    if language == "python": block = extract_python_block_ast(file_text, line=line_no)
    elif language == "brace": block = extract_brace_block(file_text, line=line_no)
    elif language == "json": block = extract_json_block(file_text, line=line_no)
    elif language == "yaml": block = extract_yaml_block(file_text, line=line_no)
    elif language == "xml": block = extract_xml_block(file_text, line=line_no)
    elif language == "ruby": block = extract_ruby_block(file_text, line=line_no)
    elif language == "lua": block = extract_lua_block(file_text, line=line_no)
    if block:
        lines = file_text.splitlines()
        snip = "\n".join(lines[block.start-1:block.end])
        return (block.start, block.end, snip, language)
    ctx = 5
    lines = file_text.splitlines()
    s = max(1, line_no - ctx)
    e = min(len(lines), line_no + ctx)
    snip = "\n".join(lines[s-1:e])
    return (s, e, snip, language)

def search_and_extract(pattern: str, root: str | Path,
                       include_ext: Optional[List[str]] = None,
                       exclude_ext: Optional[List[str]] = None,
                       globs: Optional[List[str]] = None,
                       extra_args: Optional[List[str]] = None,
                       output_format: str = "text",
                       collect_stats: bool = True) -> Dict:
    include_ext = include_ext or []
    exclude_ext = exclude_ext or []
    extra_args = extra_args or []
    globs = globs or []

    built = []
    for g in globs: built += ["-g", g]
    if include_ext:
        for ext in include_ext:
            e = ext if ext.startswith(".") else f".{ext}"
            built += ["-g", f"*{e}"]
    if exclude_ext:
        for ext in exclude_ext:
            e = ext if ext.startswith(".") else f".{ext}"
            built += ["-g", f"!*{e}"]

    events = list(run_ripgrep(pattern, root, built + extra_args))
    by_file: Dict[Path, List[MatchEvent]] = defaultdict(list)
    for ev in events: by_file[ev.path].append(ev)

    results = []
    stats = {"total_matches": len(events), "files_processed": len(by_file), "unique_blocks": 0,
             "language_breakdown": defaultdict(int), "truncations": 0}
    for path, evs in by_file.items():
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        seen_ranges: set[tuple[int,int]] = set()
        for ev in evs:
            start, end, snippet, lang = extract_block_for_file(text, path, ev.line_number)
            rng = (start, end)
            if rng in seen_ranges: continue
            seen_ranges.add(rng)
            stats["unique_blocks"] += 1
            stats["language_breakdown"][lang] += 1
            hsnip = snippet
            if ev.submatches:
                hsnip = highlight(snippet, ev.submatches[0][2])
            results.append({
                "file": str(path),
                "line_range": [start, end],
                "language": lang,
                "block": hsnip,
            })

    if output_format == "json":
        return {"results": results, "stats": {**stats, "language_breakdown": dict(stats["language_breakdown"])}}  # type: ignore
    else:
        text_out = []
        for r in results:
            text_out.append(f"=== {r['file']}:{r['line_range'][0]}-{r['line_range'][1]} (lang={r['language']}) ===\n{r['block']}\n")
        if collect_stats:
            text_out.append("--- STATS ---")
            import json as _json
            text_out.append(_json.dumps({**stats, "language_breakdown": dict(stats["language_breakdown"])}, indent=2))
        return {"text": "\n".join(text_out), "stats": {**stats, "language_breakdown": dict(stats["language_breakdown"])}}  # type: ignore

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="ripgrep-powered code block extractor (rgcodeblock)")
    ap.add_argument("pattern", nargs="?", help="Search pattern for ripgrep")
    ap.add_argument("path", nargs="?", default=".", help="Path to search (default: current directory)")
    ap.add_argument("-f", "--format", choices=["text", "json"], default="text")
    ap.add_argument("-i", "--include_ext", action="append")
    ap.add_argument("-e", "--exclude_ext", action="append")
    ap.add_argument("-g", "--glob", action="append")
    ap.add_argument("-a", "--rg_arg", action="append")
    ap.add_argument("-L", "--list_languages", action="store_true", help="List supported languages and exit")
    args = ap.parse_args(argv)

    if args.list_languages:
        for lang, meta in LANGUAGE_DEFINITIONS.items():
            exts = ", ".join(meta.get("extensions", []))
            print(f"{lang}: {exts}")
        return 0

    if not args.pattern:
        ap.error("pattern is required when not using --list_languages")
        return 2

    try:
        result = search_and_extract(args.pattern, args.path, include_ext=args.include_ext, exclude_ext=args.exclude_ext,
                                    globs=args.glob, extra_args=args.rg_arg, output_format=args.format, collect_stats=True)
        if args.format == "json":
            import json as _json
            print(_json.dumps(result, indent=2))
        else:
            print(result["text"])
        return 0
    except Exception as e:
        print(f"[ERROR] {e}")
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
