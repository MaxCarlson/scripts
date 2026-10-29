"""Fresh, bounded Python AST outlines and task-specific repository maps."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import keyword
from pathlib import Path
import re
import tokenize
from typing import Any

from .core import (
    MAX_FILE_BYTES,
    MAX_TOTAL_SCAN_BYTES,
    RetrievalError,
    _candidate_paths,
    _git_paths,
    MAX_DISCOVERY_PATHS,
    _positive,
    _resolve_file,
    _response,
    _workspace,
)

MAX_SYMBOLS_PER_FILE = 2000
MAX_FILES = 200
MAX_RESULTS = 500
MAX_TOKENS = 16_000


def _words(value: str) -> set[str]:
    pieces = re.findall(r"[A-Za-z0-9_]+", value)
    result: set[str] = set()
    for piece in pieces:
        result.update(part.casefold() for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)|\d+", piece))
        result.add(piece.casefold())
    return result - set(keyword.kwlist)


def _read_python(path: Path) -> tuple[bytes, str | None]:
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        return b"", str(exc)[:200]
    if len(data) > MAX_FILE_BYTES:
        return b"", f"File exceeds {MAX_FILE_BYTES} bytes"
    if b"\0" in data:
        return b"", "Binary file"
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        data.decode(encoding)
    except (SyntaxError, UnicodeError):
        return b"", "Source is not valid Python text"
    return data, None


def _decode_python(data: bytes) -> str:
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return data.decode(encoding)


def _definitions(source: str) -> tuple[list[dict[str, Any]], bool]:
    tree = ast.parse(source)
    lines = source.splitlines()
    result: list[dict[str, Any]] = []

    def add(kind: str, name: str, qualified: str, node: ast.AST) -> None:
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        item: dict[str, Any] = {
            "kind": kind,
            "name": name,
            "qualified_name": qualified,
            "start_line": start,
            "end_line": end,
        }
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_start = node.body[0].lineno if node.body else end + 1
            signature = "\n".join(lines[start - 1:body_start - 1]).strip()
            if len(signature.encode("utf-8")) > 2048:
                signature = signature.encode("utf-8")[:2045].decode("utf-8", errors="ignore") + "…"
            item["signature"] = signature
            item["async"] = isinstance(node, ast.AsyncFunctionDef)
        elif isinstance(node, ast.ClassDef):
            item["signature"] = lines[start - 1].strip()[:2048] if start <= len(lines) else ""
        result.append(item)

    def visit(body: list[ast.stmt], parent: str = "") -> None:
        for node in body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    result.append({"kind": "import", "name": name, "qualified_name": name,
                                   "start_line": node.lineno, "end_line": node.end_lineno})
            elif isinstance(node, ast.ImportFrom):
                prefix = "." * node.level + (node.module or "")
                for alias in node.names:
                    name = f"{prefix}:{alias.name}"
                    result.append({"kind": "import", "name": name, "qualified_name": name,
                                   "start_line": node.lineno, "end_line": node.end_lineno})
            elif isinstance(node, ast.ClassDef):
                qualified = f"{parent}.{node.name}" if parent else node.name
                add("class", node.name, qualified, node)
                visit(node.body, qualified)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{parent}.{node.name}" if parent else node.name
                add("method" if parent else "function", node.name, qualified, node)
                nested = [child for child in node.body if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
                visit(nested, qualified)

    visit(tree.body)
    result.sort(key=lambda item: (item["start_line"], item["end_line"], item["qualified_name"], item["kind"]))
    return result[:MAX_SYMBOLS_PER_FILE], len(result) > MAX_SYMBOLS_PER_FILE


def symbols(
    workspace: str | Path,
    path: str,
    *,
    max_output_bytes: int = 12 * 1024,
) -> dict[str, Any]:
    """Return a line-exact AST outline for one workspace-relative Python file."""
    root = _workspace(workspace)
    max_output_bytes = _positive("max_output_bytes", max_output_bytes, 1024 * 1024)
    candidates, _, _ = _candidate_paths(root, [path], 1)
    if not candidates:
        raise RetrievalError("No source path selected")
    relative, source_path = candidates[0]
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    data, error = _read_python(source_path)
    if error:
        errors.append({"code": "binary_file" if error == "Binary file" else "read_error", "path": relative, "message": error})
    else:
        text = _decode_python(data)
        try:
            outline, symbols_truncated = _definitions(text)
        except SyntaxError as exc:
            errors.append({"code": "syntax_error", "path": relative,
                           "message": f"{exc.msg} at line {exc.lineno}"[:200]})
        except RecursionError:
            errors.append({"code": "ast_depth", "path": relative, "message": "Python syntax tree is too deeply nested"})
        else:
            source_result = {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "symbol_count": len(outline),
                "symbols_truncated": symbols_truncated,
                "symbols": outline,
            }
            while True:
                response = _response(
                    "symbols", root, results=[source_result], errors=errors,
                    truncated=source_result["symbols_truncated"], engine="python-ast",
                    discovery="explicit", max_output_bytes=max_output_bytes,
                )
                if response["results"] or not source_result["symbols"]:
                    return response
                source_result["symbols"].pop()
                source_result["symbols_truncated"] = True
    return _response("symbols", root, results=results, errors=errors, engine="python-ast",
                     discovery="explicit", max_output_bytes=max_output_bytes)


def repository_map(
    workspace: str | Path,
    task_query: str,
    *,
    max_files: int = 80,
    max_results: int = 80,
    max_tokens: int = 3000,
    max_output_bytes: int = 12 * 1024,
) -> dict[str, Any]:
    """Build a fresh symbol map ranked for a task query within strict bounds.

    UTF-8 bytes are a conservative token-count upper bound for tokenizers with
    byte fallback; no provider-specific tokenizer is assumed or installed.
    """
    root = _workspace(workspace)
    if not isinstance(task_query, str) or not task_query.strip() or len(task_query) > 4096:
        raise RetrievalError("task_query must be non-empty text of at most 4096 characters")
    max_files = _positive("max_files", max_files, MAX_FILES)
    max_results = _positive("max_results", max_results, MAX_RESULTS)
    max_tokens = _positive("max_tokens", max_tokens, MAX_TOKENS)
    max_output_bytes = _positive("max_output_bytes", max_output_bytes, 1024 * 1024)
    budget = min(max_tokens, max_output_bytes)
    if budget < 512:
        raise RetrievalError("max_tokens and max_output_bytes must allow at least 512 bytes")
    names, candidate_truncated, git_aware = _git_paths(root, MAX_DISCOVERY_PATHS)
    task_words = _words(task_query)
    python_names = [name for name in names if name.casefold().endswith(".py")]
    python_names.sort(key=lambda name: (-len(task_words & _words(name)), name))
    if len(python_names) > max_files:
        candidate_truncated = True
        python_names = python_names[:max_files]
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    python_candidates = []
    for name in python_names:
        try:
            python_candidates.append(_resolve_file(root, name))
        except (RetrievalError, OSError) as exc:
            errors.append({"code": "unsafe_path", "path": name, "message": str(exc)[:200]})
    scanned = 0
    total_bytes = 0
    truncated = candidate_truncated
    for relative, source_path in python_candidates:
        scanned += 1
        try:
            size = source_path.stat().st_size
        except OSError as exc:
            errors.append({"code": "read_error", "path": relative, "message": str(exc)[:200]})
            continue
        if size > MAX_FILE_BYTES or total_bytes + size > MAX_TOTAL_SCAN_BYTES:
            truncated = True
            if len(errors) < 20:
                errors.append({"code": "file_too_large", "path": relative, "message": "File or request scan byte budget exceeded"})
            continue
        data, error = _read_python(source_path)
        if error:
            errors.append({"code": "binary_file" if error == "Binary file" else "read_error", "path": relative, "message": error})
            continue
        total_bytes += len(data)
        try:
            outline, definitions_truncated = _definitions(_decode_python(data))
        except SyntaxError as exc:
            errors.append({"code": "syntax_error", "path": relative, "message": f"{exc.msg} at line {exc.lineno}"[:200]})
            continue
        except RecursionError:
            errors.append({"code": "ast_depth", "path": relative, "message": "Python syntax tree is too deeply nested"})
            continue
        truncated |= definitions_truncated
        digest = hashlib.sha256(data).hexdigest()
        path_words = _words(relative)
        for item in outline:
            symbol_words = _words(item["qualified_name"] + " " + item.get("signature", ""))
            score = 4 * len(task_words & symbol_words) + 2 * len(task_words & path_words)
            if task_words and not score:
                continue
            results.append({"path": relative, "sha256": digest, **item, "relevance": score})
            if len(results) >= 20_000:
                truncated = True
                break
        if len(results) >= 20_000:
            break
    results.sort(key=lambda item: (-item["relevance"], item["path"], item["start_line"], item["qualified_name"]))
    if len(results) > max_results:
        results = results[:max_results]
        truncated = True
    response = _response("map", root, results=results, errors=errors, truncated=truncated,
                          engine="python-ast", discovery="git" if git_aware else "filesystem",
                          max_output_bytes=budget)
    response["token_budget"] = max_tokens
    response["token_upper_bound"] = 0
    while True:
        response["token_upper_bound"] = len(
            json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        actual = len(json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if actual <= budget:
            break
        if response["results"]:
            response["results"].pop()
            response["truncated"] = True
            response["status"] = "partial"
        elif response["errors"]:
            response["errors"].pop()
            response["truncated"] = True
            response["status"] = "partial"
        else:
            raise RetrievalError("Token budget is too small for repository map metadata")
    return response
