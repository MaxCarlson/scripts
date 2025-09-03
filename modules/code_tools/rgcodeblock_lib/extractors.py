# File: scripts/modules/code_tools/rgcodeblock_lib/extractors.py
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class Block:
    start: int  # 1-based inclusive
    end: int    # 1-based inclusive
    name: Optional[str] = None
    kind: Optional[str] = None
    language: Optional[str] = None

def _lines(text: str) -> list[str]:
    return text.splitlines()

def extract_python_block_ast(text: str, *, name: Optional[str] = None, line: Optional[int] = None) -> Optional[Block]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    candidates: list[tuple[ast.AST, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            candidates.append((node, "function"))
        elif isinstance(node, ast.ClassDef):
            candidates.append((node, "class"))
    if name:
        for node, kind in candidates:
            if getattr(node, "name", None) == name and hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                return Block(node.lineno, node.end_lineno or node.lineno, name=name, kind=kind, language="python")
    if line:
        for node, kind in candidates:
            if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                if node.lineno <= line <= (node.end_lineno or node.lineno):
                    return Block(node.lineno, node.end_lineno or node.lineno, getattr(node, "name", None), kind, "python")
    return None

def _find_enclosing_brace_block(lines: list[str], start_line_idx: int) -> Optional[tuple[int, int]]:
    open_line = None
    for i in range(start_line_idx, -1, -1):
        if "{" in lines[i]:
            open_line = i
            break
    if open_line is None:
        return None
    depth = 0
    end_line = None
    for j in range(open_line, len(lines)):
        depth += lines[j].count("{")
        depth -= lines[j].count("}")
        if depth == 0:
            end_line = j
            break
    if end_line is None:
        return None
    return open_line + 1, end_line + 1

def _find_named_brace_block(lines: list[str], name: str) -> Optional[tuple[int, int]]:
    pattern = re.compile(r"\b" + re.escape(name) + r"\b\s*\(.*?\)\s*\{|\bclass\s+" + re.escape(name) + r"\b\s*\{", re.S)
    text = "\n".join(lines)
    m = pattern.search(text)
    if not m: return None
    brace_pos = text.find("{", m.start(), m.end())
    if brace_pos == -1: return None
    start_line = text[:brace_pos].count("\n")
    return _find_enclosing_brace_block(lines, start_line)

def extract_brace_block(text: str, *, name: Optional[str] = None, line: Optional[int] = None) -> Optional[Block]:
    lines = _lines(text)
    if name:
        rng = _find_named_brace_block(lines, name)
        if rng: return Block(rng[0], rng[1], name=name, language="brace")
    if line:
        rng = _find_enclosing_brace_block(lines, line - 1)
        if rng: return Block(rng[0], rng[1], language="brace")
    return None

def extract_json_block(text: str, *, line: Optional[int] = None) -> Optional[Block]:
    if not line: return None
    lines = _lines(text)
    idx = line - 1
    flat = "\n".join(lines)
    pos = sum(len(l)+1 for l in lines[:idx])
    start = max(flat.rfind("{", 0, pos), flat.rfind("[", 0, pos))
    if start == -1: return None
    depth_curly = 0; depth_square = 0; end = None
    for i, ch in enumerate(flat[start:], start):
        if ch == "{": depth_curly += 1
        elif ch == "}": depth_curly -= 1
        elif ch == "[": depth_square += 1
        elif ch == "]": depth_square -= 1
        if depth_curly == 0 and depth_square == 0:
            end = i; break
    if end is None: return None
    start_line = flat[:start].count("\n") + 1
    end_line = flat[:end].count("\n") + 1
    return Block(start_line, end_line, kind="object", language="json")

def extract_yaml_block(text: str, *, line: Optional[int] = None, name: Optional[str] = None) -> Optional[Block]:
    if not line: return None
    lines = _lines(text)
    idx = line - 1
    cur = lines[idx]
    indent = len(cur) - len(cur.lstrip(" "))
    start = idx
    while start > 0 and (len(lines[start-1]) - len(lines[start-1].lstrip(" "))) >= indent:
        start -= 1
    end = idx
    while end + 1 < len(lines) and (len(lines[end+1]) - len(lines[end+1].lstrip(" "))) >= indent:
        end += 1
    return Block(start+1, end+1, kind="section", language="yaml")

def extract_xml_block(text: str, *, line: Optional[int] = None, name: Optional[str] = None) -> Optional[Block]:
    if not line: return None
    lines = _lines(text)
    idx = line - 1
    flat = "\n".join(lines)
    pos = sum(len(l)+1 for l in lines[:idx])
    open_m = None
    for m in re.finditer(r"<([A-Za-z_][\w\-\.:]*)[^>]*?>", flat):
        if m.start() <= pos: open_m = m
        else: break
    if not open_m: return None
    tag = open_m.group(1)
    token = flat[open_m.start():open_m.end()]
    if token.endswith("/>"):
        start_line = flat[:open_m.start()].count("\n") + 1
        end_line = flat[:open_m.end()].count("\n") + 1
        return Block(start_line, end_line, kind=tag, language="xml")
    depth = 0; end_pos = None
    tag_open_pat = re.compile(fr"<\s*{re.escape(tag)}(\s|>|/)")
    tag_close_pat = re.compile(fr"</\s*{re.escape(tag)}\s*>")
    for m in re.finditer(r"<(/?)[A-Za-z_][\w\-\.:]*[^>]*?>", flat[open_m.start():]):
        token = flat[open_m.start():][m.start():m.end()]
        if tag_open_pat.match(token) and not token.endswith("/>"): depth += 1
        if tag_close_pat.match(token):
            depth -= 1
            if depth == 0:
                end_pos = open_m.start() + m.end()
                break
    if end_pos is None: return None
    start_line = flat[:open_m.start()].count("\n") + 1
    end_line = flat[:end_pos].count("\n") + 1
    return Block(start_line, end_line, kind=tag, language="xml")

def _extract_keyword_pair_block(text: str, *, line: Optional[int] = None, name: Optional[str] = None,
                                start_keywords: tuple[str, ...] = ("def",), end_keyword: str = "end") -> Optional[Block]:
    lines = _lines(text)
    if name:
        pat = re.compile(r"\b(" + "|".join(map(re.escape, start_keywords)) + r")\b\s+" + re.escape(name) + r"\b")
        for i, ln in enumerate(lines):
            if pat.search(ln):
                return _count_keyword_block(lines, i, start_keywords, end_keyword)
        return None
    if line:
        i = line - 1
        start_i = None
        for j in range(i, -1, -1):
            if _starts_with_any(lines[j], start_keywords):
                start_i = j; break
        if start_i is None: return None
        return _count_keyword_block(lines, start_i, start_keywords, end_keyword)
    return None

def _starts_with_any(s: str, kws: tuple[str, ...]) -> bool:
    s2 = s.lstrip()
    for kw in kws:
        if s2.startswith(kw + " ") or s2.startswith(kw + "\t") or s2 == kw:
            return True
    return False

def _count_keyword_block(lines: list[str], start_i: int, start_keywords: tuple[str, ...], end_keyword: str) -> Optional[Block]:
    depth = 0
    for k in range(start_i, len(lines)):
        s = lines[k].lstrip()
        if any(s.startswith(kw + " ") or s == kw for kw in start_keywords): depth += 1
        if s.startswith(end_keyword):
            depth -= 1
            if depth == 0: return Block(start_i + 1, k + 1)
    return None

def extract_ruby_block(text: str, *, name: Optional[str] = None, line: Optional[int] = None) -> Optional[Block]:
    return _extract_keyword_pair_block(text, line=line, name=name,
                                       start_keywords=("def", "class", "module", "do", "begin"),
                                       end_keyword="end")

def extract_lua_block(text: str, *, name: Optional[str] = None, line: Optional[int] = None) -> Optional[Block]:
    return _extract_keyword_pair_block(text, line=line, name=name,
                                       start_keywords=("function", "do", "then"),
                                       end_keyword="end")
