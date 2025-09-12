#!/usr/bin/env python3
"""
UOCS v2 applier (Python focus)

- Parses a single UOCS v2 JSON document from a file or stdin.
- Applies unit-level edits to Python files using AST-first matching
  with text fallbacks (anchors), plus basic file ops.
- Dry-run by default; write only with --confirm.

Env targets: Windows 11 (PS/WSL), Termux, WSL2.

Stdlib only. Optional: if LIBCST is installed, we could preserve formatting,
but this reference keeps zero-dep semantics-focused behavior.
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import json
import logging
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

# ------------------------
# Logging
# ------------------------
logger = logging.getLogger("uocs_v2")

# ------------------------
# Datamodel
# ------------------------

@dataclasses.dataclass
class Meta:
    id: str
    author: Optional[str] = None
    created: Optional[str] = None
    description: Optional[str] = None

@dataclasses.dataclass
class Anchor:
    by: str
    value: str
    max_lines: int = 5

@dataclasses.dataclass
class UnitRef:
    kind: str  # "function" | "method" | "class"
    qualified: str
    class_name: Optional[str] = None  # fully-qualified class name
    sig_old: Optional[str] = None
    old_hash: Optional[str] = None

@dataclasses.dataclass
class NewDef:
    sig: str
    code: str

@dataclasses.dataclass
class Where:
    insert: str  # "top"|"bottom"|"before_symbol"|"after_symbol"
    symbol: Optional[str] = None

@dataclasses.dataclass
class UnitOp:
    op: str  # "replace"|"insert"|"delete"
    unit: UnitRef
    new: Optional[NewDef] = None
    where: Optional[Where] = None
    anchor: Optional[Anchor] = None

@dataclasses.dataclass
class FileEdit:
    op: str  # "edit"
    path: str
    language: str
    unit_ops: List[UnitOp]

@dataclasses.dataclass
class NewFile:
    op: str  # "new_file"
    path: str
    language: str
    content: str

@dataclasses.dataclass
class DeleteFile:
    op: str  # "delete_file"
    path: str

@dataclasses.dataclass
class RenameFile:
    op: str  # "rename_file"
    from_path: str
    to_path: str

UOCSFileOp = Union[FileEdit, NewFile, DeleteFile, RenameFile]

@dataclasses.dataclass
class UOCSDoc:
    uocs_version: str
    meta: Optional[Meta]
    files: List[UOCSFileOp]

# ------------------------
# Utilities
# ------------------------

def sha256_normalized_block(text: str) -> str:
    """
    Normalize code by stripping comments/blank lines and collapsing whitespace.
    Heuristic (python only).
    """
    lines = []
    for line in text.splitlines():
        # naive: strip trailing inline comments not inside quotes
        if "#" in line:
            # very rough check: if hash appears before any quote
            qpos_candidates = [i for i in (line.find("'"), line.find('"')) if i >= 0]
            first_quote = min(qpos_candidates) if qpos_candidates else 10**9
            hashpos = line.find("#")
            if hashpos >= 0 and hashpos < first_quote:
                line = line[:hashpos]
        if line.strip():
            # collapse inner whitespace
            lines.append(" ".join(line.strip().split()))
    normalized = "\n".join(lines).strip()
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def load_json(path: Optional[str]) -> Dict[str, Any]:
    data = sys.stdin.read() if (not path or path == "-") else Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON: {e}")

def ensure_dirs(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""

def write_text(path: Path, text: str) -> None:
    ensure_dirs(path)
    # Ensure trailing newline for POSIX friendliness
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8", newline="\n")

# ------------------------
# AST helpers (Python)
# ------------------------

@dataclasses.dataclass
class NodeSpan:
    start_line: int
    end_line: int
    indent: str

def parse_python_ast(src: str) -> ast.AST:
    return ast.parse(src)

def _infer_indent(text: str, lineno: int) -> str:
    lines = text.splitlines(True)
    if 1 <= lineno <= len(lines):
        m = re.match(r"[ \t]*", lines[lineno-1])
        return m.group(0) if m else ""
    return ""

def _slice_by_span(text: str, span: NodeSpan) -> Tuple[str, str, str]:
    """Return (head, mid, tail) where mid is the span slice (line-based)."""
    lines = text.splitlines(True)
    head = "".join(lines[:span.start_line-1])
    mid  = "".join(lines[span.start_line-1:span.end_line])
    tail = "".join(lines[span.end_line:])
    return head, mid, tail

def _replace_span(text: str, span: NodeSpan, new_block: str) -> str:
    head, _mid, tail = _slice_by_span(text, span)
    if new_block and not new_block.endswith("\n"):
        new_block += "\n"
    return head + new_block + tail

def _find_class_node(text: str, tree: ast.AST, qual: str) -> Optional[Tuple[ast.ClassDef, NodeSpan]]:
    # Qual may include module path; we only need the simple name for Python.
    _, _, simple = qual.rpartition(".")
    target = simple or qual
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == target:
            span = NodeSpan(node.lineno, getattr(node, "end_lineno", node.lineno), _infer_indent(text, node.lineno))
            return node, span
    return None

def _find_function_node(text: str, tree: ast.AST, qual: str, class_name: Optional[str]) -> Optional[Tuple[ast.AST, NodeSpan]]:
    _, _, simple = qual.rpartition(".")
    fn = simple or qual

    if class_name:
        c = _find_class_node(text, tree, class_name)
        if not c:
            return None
        cls, _ = c
        for node in cls.body:
            if isinstance(node, ast.FunctionDef) and node.name == fn:
                span = NodeSpan(node.lineno, getattr(node, "end_lineno", node.lineno), _infer_indent(text, node.lineno))
                return node, span
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fn:
            span = NodeSpan(node.lineno, getattr(node, "end_lineno", node.lineno), _infer_indent(text, node.lineno))
            return node, span
    return None

# ------------------------
# Applier
# ------------------------

@dataclasses.dataclass
class OpResult:
    status: str  # applied|skipped|failed|noop
    reason: Optional[str]
    path: str
    op_index: int
    before_hash: Optional[str] = None
    after_hash: Optional[str] = None

class UOCSApplicator:
    def __init__(self, root: Path, dry_run: bool = True):
        self.root = root
        self.dry_run = dry_run
        self.results: List[OpResult] = []

    # ---------- public entry ----------

    def apply(self, doc: Dict[str, Any]) -> List[OpResult]:
        if doc.get("uocs_version") != "2.0":
            raise SystemExit("uocs_version must be '2.0'")
        files = doc.get("files", [])
        for entry_index, entry in enumerate(files):
            op = entry.get("op")
            if op == "new_file":
                self._new_file(entry, entry_index)
            elif op == "delete_file":
                self._delete_file(entry, entry_index)
            elif op == "rename_file":
                self._rename_file(entry, entry_index)
            elif op == "edit":
                self._edit(entry, entry_index)
            else:
                self.results.append(OpResult("failed", f"unknown op {op}", entry.get("path", "?"), entry_index))
        return self.results

    # ---------- file ops ----------

    def _new_file(self, e: Dict[str, Any], idx: int) -> None:
        path = self.root / e["path"]
        if path.exists():
            self.results.append(OpResult("failed", "file exists", str(path), idx))
            return
        if not self.dry_run:
            write_text(path, e.get("content", ""))
        self.results.append(OpResult("applied", None, str(path), idx))

    def _delete_file(self, e: Dict[str, Any], idx: int) -> None:
        path = self.root / e["path"]
        if not path.exists():
            self.results.append(OpResult("noop", "missing", str(path), idx))
            return
        if not self.dry_run:
            path.unlink()
        self.results.append(OpResult("applied", None, str(path), idx))

    def _rename_file(self, e: Dict[str, Any], idx: int) -> None:
        src = self.root / e["from"]
        dst = self.root / e["to"]
        if not src.exists():
            self.results.append(OpResult("failed", "source missing", str(src), idx))
            return
        if dst.exists():
            self.results.append(OpResult("failed", "dest exists", str(dst), idx))
            return
        if not self.dry_run:
            ensure_dirs(dst)
            src.replace(dst)
        self.results.append(OpResult("applied", None, f"{src} -> {dst}", idx))

    # ---------- edit ops ----------

    def _edit(self, e: Dict[str, Any], idx: int) -> None:
        path = self.root / e["path"]
        lang = e.get("language", "python")
        if lang != "python":
            self.results.append(OpResult("failed", f"unsupported language {lang}", str(path), idx))
            return
        text = read_text(path)

        try:
            tree = parse_python_ast(text)
        except SyntaxError as se:
            self.results.append(OpResult("failed", f"syntax error parsing file: {se}", str(path), idx))
            return

        unit_ops = e.get("unit_ops", [])
        for uidx, u in enumerate(unit_ops):
            res = self._apply_unit_op(text, tree, path, u, uidx)
            self.results.append(res)
            if res.status == "applied" and not self.dry_run:
                # Refresh after write
                text = read_text(path)
                try:
                    tree = parse_python_ast(text)
                except SyntaxError:
                    # leave parsing error for optional validation
                    pass

    def _apply_unit_op(self, text: str, tree: ast.AST, path: Path, u: Dict[str, Any], op_index: int) -> OpResult:
        op = u.get("op")
        unit = u.get("unit", {})
        unit_ref = UnitRef(
            kind=unit.get("kind"),
            qualified=unit.get("qualified"),
            class_name=unit.get("class"),
            sig_old=unit.get("sig_old"),
            old_hash=unit.get("old_hash"),
        )
        anchor = Anchor(**u["anchor"]) if u.get("anchor") else None
        where = Where(**u["where"]) if u.get("where") else None
        newdef = NewDef(**u["new"]) if u.get("new") else None

        try:
            if op == "replace":
                return self._op_replace(path, text, tree, unit_ref, newdef, anchor, op_index)
            elif op == "insert":
                return self._op_insert(path, text, tree, unit_ref, newdef, where, op_index)
            elif op == "delete":
                return self._op_delete(path, text, tree, unit_ref, anchor, op_index)
            else:
                return OpResult("failed", f"unknown unit op {op}", str(path), op_index)
        except Exception as ex:
            logger.exception("unit op failed")
            return OpResult("failed", f"exception: {ex}", str(path), op_index)

    # ---------- matching ----------

    def _match_unit(self, text: str, tree: ast.AST, ref: UnitRef, anchor: Optional[Anchor]) -> Optional[NodeSpan]:
        """
        Ladder: AST by symbol → AST by kind/name → unique text anchor.
        Returns NodeSpan if matched; None otherwise.
        """
        # 1) AST by symbol
        if ref.kind == "class":
            found = _find_class_node(text, tree, ref.qualified)
        else:
            found = _find_function_node(text, tree, ref.qualified, ref.class_name)

        if found:
            node, span = found
            # Verify header if provided
            head, mid, _tail = _slice_by_span(text, span)
            if ref.sig_old:
                first_line = (mid.splitlines(True)[0] if mid else "").strip()
                if ref.sig_old.strip() not in first_line:
                    # Allow via old_hash if provided and matches
                    if ref.old_hash and sha256_normalized_block(mid) == ref.old_hash:
                        return span
                    return None
            if ref.old_hash and sha256_normalized_block(mid) != ref.old_hash:
                return None
            return span

        # 2) Unique text anchor fallback
        if anchor and anchor.by == "text":
            snippet = anchor.value
            # Limit lines
            if snippet.count("\n") + 1 > anchor.max_lines:
                return None
            # Count all matches to ensure uniqueness
            matches = list(re.finditer(re.escape(snippet), text))
            if len(matches) != 1:
                return None
            m = matches[0]
            # Compute 1-based line numbers
            start_idx = m.start()
            pre_lines = text[:start_idx].splitlines(True)
            start_line = len(pre_lines) + 1
            end_line = start_line + (snippet.count("\n") or 0)
            return NodeSpan(start_line, end_line, _infer_indent(text, start_line))

        return None

    # ---------- ops ----------

    def _op_replace(self, path: Path, text: str, tree: ast.AST, ref: UnitRef, new: Optional[NewDef],
                    anchor: Optional[Anchor], op_index: int) -> OpResult:
        if not new or not new.code or not new.sig:
            return OpResult("failed", "missing new definition", str(path), op_index)

        span = self._match_unit(text, tree, ref, anchor)
        if not span:
            return OpResult("skipped", "no unique match", str(path), op_index)

        head, mid, tail = _slice_by_span(text, span)
        before_hash = sha256_normalized_block(mid)

        # Idempotency
        if sha256_normalized_block(new.code) == before_hash:
            return OpResult("noop", "already applied", str(path), op_index, before_hash, before_hash)

        # Basic header guard
        first_line = new.code.splitlines(True)[0] if new.code else ""
        if new.sig.strip() not in first_line:
            return OpResult("failed", "new.sig does not match code header", str(path), op_index)

        updated = _replace_span(text, span, new.code)
        if not self.dry_run:
            write_text(path, updated)

        after_hash = sha256_normalized_block(new.code)
        return OpResult("applied", None, str(path), op_index, before_hash, after_hash)

    def _op_insert(self, path: Path, text: str, tree: ast.AST, ref: UnitRef,
                   new: Optional[NewDef], where: Optional[Where], op_index: int) -> OpResult:
        if not new or not new.code or not new.sig:
            return OpResult("failed", "missing new definition", str(path), op_index)
        if not where:
            return OpResult("failed", "missing where", str(path), op_index)

        lines = text.splitlines(True)

        def insert_at_line(idx: int) -> str:
            block = new.code
            if not block.endswith("\n"):
                block += "\n"
            return "".join(lines[:idx]) + block + "".join(lines[idx:])

        updated = None
        if where.insert == "top":
            updated = insert_at_line(0)
        elif where.insert == "bottom":
            updated = insert_at_line(len(lines))
        elif where.insert in ("before_symbol", "after_symbol"):
            if not where.symbol:
                return OpResult("failed", "where.symbol required", str(path), op_index)
            # Determine symbol kind heuristically from ref.kind
            sym_kind = "method" if ref.kind == "method" else "function"
            sym_ref = UnitRef(kind=sym_kind, qualified=where.symbol, class_name=None)
            span = self._match_unit(text, tree, sym_ref, None)
            if not span:
                return OpResult("skipped", "symbol anchor not found", str(path), op_index)
            target_line = span.start_line - 1 if where.insert == "before_symbol" else span.end_line
            updated = insert_at_line(target_line)
        else:
            return OpResult("failed", f"unsupported where.insert {where.insert}", str(path), op_index)

        if not self.dry_run:
            write_text(path, updated)
        return OpResult("applied", None, str(path), op_index)

    def _op_delete(self, path: Path, text: str, tree: ast.AST, ref: UnitRef,
                   anchor: Optional[Anchor], op_index: int) -> OpResult:
        span = self._match_unit(text, tree, ref, anchor)
        if not span:
            return OpResult("skipped", "no unique match", str(path), op_index)
        head, mid, tail = _slice_by_span(text, span)
        updated = head + tail
        if not self.dry_run:
            write_text(path, updated)
        return OpResult("applied", None, str(path), op_index, sha256_normalized_block(mid), None)

# ------------------------
# CLI
# ------------------------

def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="uocs-v2",
        description="Apply UOCS v2 unit-level changes (Python focus).",
    )
    p.add_argument("--root", type=str, default=".", help="Repository root (default: current dir)")
    p.add_argument("--uocs", type=str, default="-", help="Path to UOCS JSON (or '-' for stdin)")
    p.add_argument("--confirm", "-y", action="store_true", help="Write changes to disk")
    p.add_argument("--quiet", "-q", action="store_true", help="Less logging")
    p.add_argument("--verbose", "-v", action="store_true", help="More logging")
    p.add_argument("--format", choices=["text", "json"], default="text", help="Result output format")
    p.add_argument("--validate", action="store_true", help="Run 'python -m py_compile' on changed Python files")
    return p

def main(argv: Optional[List[str]] = None) -> int:
    args = build_argparser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else (logging.WARNING if args.quiet else logging.INFO),
        format="%(levelname)s: %(message)s",
    )
    doc = load_json(args.uocs)
    app = UOCSApplicator(root=Path(args.root).resolve(), dry_run=not args.confirm)
    results = app.apply(doc)

    # Output
    if args.format == "json":
        print(json.dumps([dataclasses.asdict(r) for r in results], indent=2))
    else:
        for r in results:
            msg = f"{r.status.upper()} [{r.path}] op#{r.op_index}"
            if r.reason:
                msg += f" :: {r.reason}"
            print(msg)

    # Optional validation
    if args.validate and args.confirm:
        try:
            import compileall  # stdlib
            ok = compileall.compile_dir(args.root, quiet=1)
            if not ok:
                logging.error("Validation failed (py_compile).")
                return 2
        except Exception as ex:
            logging.error("Validation error: %s", ex)
            return 2

    if any(r.status == "failed" for r in results):
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
