"""Bounded, read-only source retrieval for a single workspace."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
from typing import Any, Iterable

SCHEMA = "local-agent-retrieval-v1"
DEFAULT_MAX_PATHS = 200
DEFAULT_MAX_RESULTS = 80
DEFAULT_MAX_OUTPUT_BYTES = 12 * 1024
DEFAULT_MAX_LINE_BYTES = 4096
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_SCAN_BYTES = 32 * 1024 * 1024
MAX_DISCOVERY_BYTES = 4 * 1024 * 1024
MAX_DISCOVERY_PATHS = 20_000
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "vendor",
    "__pycache__", ".pytest_cache", ".pytest_tmp_root", ".mypy_cache", ".ruff_cache",
    ".tox", "dist", "build", "target", "coverage", "htmlcov",
}


class RetrievalError(ValueError):
    """Invalid workspace, path, or retrieval limits."""


def _is_junction(path: Path) -> bool:
    check = getattr(path, "is_junction", None)
    return bool(check and check())


def _workspace(value: str | os.PathLike[str] | None) -> Path:
    candidate = Path.cwd() if value is None else Path(value).expanduser()
    if candidate.is_symlink() or _is_junction(candidate):
        raise RetrievalError("Workspace root must not be a symlink or junction")
    try:
        root = candidate.resolve(strict=True)
    except OSError as exc:
        raise RetrievalError(f"Workspace root does not exist: {candidate}") from exc
    if not root.is_dir():
        raise RetrievalError(f"Workspace root is not a directory: {candidate}")
    return root


def _positive(name: str, value: int, maximum: int) -> int:
    if type(value) is not int or value <= 0 or value > maximum:
        raise RetrievalError(f"{name} must be an integer between 1 and {maximum}")
    return value


def _safe_relative(value: str | os.PathLike[str]) -> str:
    raw = os.fspath(value)
    windows = PureWindowsPath(raw)
    if not raw or "\0" in raw or Path(raw).is_absolute() or windows.is_absolute() or windows.drive:
        raise RetrievalError(f"Expected a relative workspace path: {raw!r}")
    normalized = raw.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise RetrievalError(f"Unsafe relative workspace path: {raw!r}")
    return PurePosixPath(*parts).as_posix()


def _resolve_file(root: Path, value: str | os.PathLike[str]) -> tuple[str, Path]:
    relative = _safe_relative(value)
    target = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = target.resolve(strict=True)
    except OSError as exc:
        raise RetrievalError(f"Source path does not exist: {relative}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RetrievalError(f"Source path escapes the workspace: {relative}") from exc
    if not resolved.is_file():
        raise RetrievalError(f"Source path is not a regular file: {relative}")
    return relative, target


def _excluded(relative: str) -> bool:
    return any(part.lower() in EXCLUDED_DIRS for part in PurePosixPath(relative).parts)


def _fallback_paths(
    root: Path, max_paths: int, path_query: str | None = None,
) -> tuple[list[str], bool]:
    found: list[str] = []
    needle = path_query.casefold() if path_query else None
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        parent = Path(current)
        dirs[:] = sorted(
            name for name in dirs
            if name.lower() not in EXCLUDED_DIRS
            and not (parent / name).is_symlink()
            and not _is_junction(parent / name)
        )
        for name in sorted(names):
            path = parent / name
            if path.is_symlink() or _is_junction(path):
                continue
            relative = path.relative_to(root).as_posix()
            if _excluded(relative) or (needle and needle not in relative.casefold()) or not path.is_file():
                continue
            if len(found) >= max_paths:
                return sorted(found), True
            found.append(relative)
    return sorted(found), False



def _git_paths(
    root: Path, max_paths: int, path_query: str | None = None,
) -> tuple[list[str], bool, bool]:
    """Return bounded tracked plus nonignored untracked paths when Git is available."""
    git_exe = shutil.which("git")
    if not git_exe:
        paths, truncated = _fallback_paths(root, max_paths, path_query)
        return paths, truncated, False
    try:
        top = subprocess.run(
            [git_exe, "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True, capture_output=True, timeout=3,
        ).stdout.decode("utf-8", errors="strict").strip()
        repository = Path(top).resolve(strict=True)
        prefix = root.relative_to(repository).as_posix()
        if prefix == ".":
            prefix = ""
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        paths, truncated = _fallback_paths(root, max_paths, path_query)
        return paths, truncated, False
    try:
        process = subprocess.Popen(
            [git_exe, "-C", str(repository), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        assert process.stdout is not None
        output = bytearray()
        byte_truncated = False
        while len(output) <= MAX_DISCOVERY_BYTES:
            block = process.stdout.read(min(64 * 1024, MAX_DISCOVERY_BYTES + 1 - len(output)))
            if not block:
                break
            output.extend(block)
            if len(output) > MAX_DISCOVERY_BYTES:
                byte_truncated = True
                process.terminate()
                break
        process.stdout.close()
        exit_code = process.wait(timeout=3)
        if exit_code not in (0, -15, 15):
            raise OSError(f"git ls-files exited with status {exit_code}")
        if byte_truncated:
            boundary = output.rfind(b"\0")
            output = output[:boundary + 1] if boundary >= 0 else bytearray()
    except (OSError, subprocess.SubprocessError):
        paths, truncated = _fallback_paths(root, max_paths, path_query)
        return paths, truncated, False
    names: list[str] = []
    needle = path_query.casefold() if path_query else None
    truncated = byte_truncated
    for raw in bytes(output).split(b"\0"):
        if not raw:
            continue
        name = os.fsdecode(raw)
        if name.endswith(("/", "\\")):
            continue
        if os.sep == "\\":
            name = name.replace("\\", "/")
        if prefix:
            if not name.startswith(prefix + "/"):
                continue
            name = name[len(prefix) + 1:]
        if not name or _excluded(name) or (needle and needle not in name.casefold()):
            continue
        if len(names) >= max_paths:
            truncated = True
            break
        names.append(name)
    return sorted(set(names)), truncated, True



def _candidate_paths(
    root: Path,
    paths: Iterable[str | os.PathLike[str]] | None,
    max_paths: int,
    path_query: str | None = None,
) -> tuple[list[tuple[str, Path]], bool, bool]:
    if paths is None:
        names, truncated, git_aware = _git_paths(root, max_paths, path_query)
    else:
        names = []
        truncated = False
        for value in paths:
            if len(names) >= max_paths:
                truncated = True
                break
            names.append(_safe_relative(value))
        git_aware = False
        if path_query:
            needle = path_query.casefold()
            names = [name for name in names if needle in name.casefold()]
    names = sorted(set(names))
    resolved = [_resolve_file(root, name) for name in names]
    return resolved, truncated, git_aware



def _encoded_size(value: dict[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _response(
    operation: str,
    root: Path,
    *,
    results: list[dict[str, Any]],
    errors: list[dict[str, str]] | None = None,
    truncated: bool = False,
    engine: str | None = None,
    discovery: str | None = None,
    max_output_bytes: int,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "operation": operation,
        "workspace": str(root),
        "status": "partial" if errors or truncated or len(errors or []) > 20 else "ok",
        "results": results,
        "truncated": truncated or len(errors or []) > 20,
        "errors": (errors or [])[:20],
    }
    if engine is not None:
        value["engine"] = engine
    if discovery is not None:
        value["discovery"] = discovery
    while _encoded_size(value) > max_output_bytes:
        if not value["results"]:
            if value["errors"]:
                value["errors"].pop()
                value["truncated"] = True
                value["status"] = "partial"
                continue
            raise RetrievalError("Output byte limit is too small for response metadata")
        value["results"].pop()
        value["truncated"] = True
        value["status"] = "partial"
    return value


def locate(
    workspace: str | os.PathLike[str] | None = None,
    query: str | None = None,
    *,
    paths: Iterable[str | os.PathLike[str]] | None = None,
    limit: int = DEFAULT_MAX_PATHS,
    max_output_bytes: int = 8 * 1024,
) -> dict[str, Any]:
    """List sorted workspace-relative paths, optionally filtering by path text."""
    root = _workspace(workspace)
    limit = _positive("limit", limit, 2000)
    max_output_bytes = _positive("max_output_bytes", max_output_bytes, 1024 * 1024)
    if max_output_bytes < 512:
        raise RetrievalError("max_output_bytes must be at least 512")
    candidates, candidate_truncated, git_aware = _candidate_paths(root, paths, MAX_DISCOVERY_PATHS if query else limit, query)
    needle = query.casefold() if query else None
    results = [{"path": name} for name, _ in candidates if needle is None or needle in name.casefold()]
    return _response(
        "locate", root, results=results[:limit], truncated=candidate_truncated or len(results) > limit,
        discovery="explicit" if paths is not None else ("git" if git_aware else "filesystem"),
        max_output_bytes=max_output_bytes,
    )


def _bounded_text(text: str, max_bytes: int, match_start: int | None = None) -> tuple[str, bool]:
    if len(text.encode("utf-8")) <= max_bytes:
        return text, False
    marker_bytes = len("…".encode("utf-8"))
    content_chars = max(1, (max_bytes - marker_bytes * 2) // 2)
    start = max(0, (match_start or 0) - content_chars // 2)
    end = min(len(text), start + content_chars)
    start = max(0, end - content_chars)
    clipped = ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")
    while len(clipped.encode("utf-8")) > max_bytes and end > start:
        end -= 1
        clipped = ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")
    return clipped, True


def _python_search(
    candidates: list[tuple[str, Path]], query: str, expression: re.Pattern[str] | None,
    limit: int, max_line_bytes: int,
) -> tuple[list[dict[str, Any]], bool, list[dict[str, str]]]:
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    truncated = False
    for relative, path in candidates:
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
        except OSError as exc:
            errors.append({"code": "read_error", "path": relative, "message": str(exc)[:200]})
            continue
        if b"\0" in data:
            errors.append({"code": "binary_file", "path": relative, "message": "Binary content was skipped"})
            continue
        if len(data) > MAX_FILE_BYTES:
            data = data[:MAX_FILE_BYTES]
            truncated = True
            errors.append({"code": "file_too_large", "path": relative, "message": "Search stopped at 2 MiB"})
        try:
            source = data.decode("utf-8")
        except UnicodeDecodeError:
            errors.append({"code": "decode_error", "path": relative, "message": "File is not valid UTF-8"})
            continue
        for line_number, line in enumerate(source.splitlines(), 1):
            match = expression.search(line) if expression else (None if query not in line else True)
            if not match:
                continue
            text, clipped = _bounded_text(line, max_line_bytes, match.start() if expression else line.find(query))
            results.append({"path": relative, "line": line_number, "text": text, "line_truncated": clipped})
            if len(results) > limit:
                results.pop()
                truncated = True
                return results, truncated, errors
    return results, truncated, errors


def _rg_search(
    executable: str,
    root: Path,
    candidates: list[tuple[str, Path]],
    query: str,
    limit: int,
    max_line_bytes: int,
) -> tuple[list[dict[str, Any]], bool, list[dict[str, str]]]:
    args = [
        executable, "--json", "--no-messages", "--hidden", "--no-ignore", "--max-filesize", "2M", "--max-columns",
        str(max_line_bytes), "--max-columns-preview", "-e", query, "--",
    ]
    args.extend(name for name, _ in candidates)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    truncated = False
    path_map = {os.path.normcase(name.replace("/", os.sep)): name for name, _ in candidates}
    try:
        process = subprocess.Popen(args, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert process.stdout is not None
        row_cap = max_line_bytes * 8 + 4096
        for raw in iter(lambda: process.stdout.readline(row_cap + 1), b""):
            if len(raw) > row_cap and not raw.endswith(b"\n"):
                truncated = True
                process.terminate()
                break
            try:
                event = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                errors.append({"code": "rg_output", "message": "ripgrep returned an invalid JSON record"})
                continue
            if event.get("type") != "match":
                continue
            data = event.get("data", {})
            raw_path = data.get("path", {}).get("text")
            if raw_path is None and data.get("path", {}).get("bytes"):
                raw_path = os.fsdecode(base64.b64decode(data["path"]["bytes"]))
            relative = path_map.get(os.path.normcase((raw_path or "").replace("/", os.sep)))
            if relative is None:
                errors.append({"code": "rg_path", "message": "ripgrep returned a path outside the candidate set"})
                continue
            line_data = data.get("lines", {})
            text = line_data.get("text")
            if text is None and line_data.get("bytes"):
                try:
                    text = base64.b64decode(line_data["bytes"]).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    errors.append({"code": "decode_error", "path": relative, "message": "Matched line is not UTF-8"})
                    continue
            text = (text or "").rstrip("\r\n")
            if "\0" in text:
                errors.append({"code": "binary_file", "path": relative, "message": "Binary content was skipped"})
                continue
            submatches = data.get("submatches", [])
            match_start = None
            if submatches:
                prefix = text.encode("utf-8")[:submatches[0].get("start", 0)]
                match_start = len(prefix.decode("utf-8", errors="ignore"))
            text, clipped = _bounded_text(text, max_line_bytes, match_start)
            clipped = clipped or text.startswith("…") or text.endswith("…")
            results.append({"path": relative, "line": int(data["line_number"]), "text": text,
                            "line_truncated": clipped})
            if len(results) > limit:
                results.pop()
                truncated = True
                process.terminate()
                break
        process.stdout.close()
        exit_code = process.wait(timeout=3)
        if exit_code not in (0, 1, -15, 15) and not truncated:
            errors.append({"code": "rg_failed", "message": f"ripgrep exited with status {exit_code}"})
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append({"code": "rg_failed", "message": str(exc)[:200]})
    return results, truncated, errors


def _bounded_search_candidates(
    candidates: list[tuple[str, Path]],
) -> tuple[list[tuple[str, Path]], list[dict[str, str]], bool]:
    accepted: list[tuple[str, Path]] = []
    errors: list[dict[str, str]] = []
    total = 0
    truncated = False
    for relative, path in candidates:
        try:
            size = path.stat().st_size
        except OSError as exc:
            errors.append({"code": "read_error", "path": relative, "message": str(exc)[:200]})
            continue
        if size > MAX_FILE_BYTES:
            errors.append({"code": "file_too_large", "path": relative, "message": "Files over 2 MiB are skipped"})
            truncated = True
            continue
        if total + size > MAX_TOTAL_SCAN_BYTES:
            errors.append({"code": "scan_budget", "path": relative, "message": "Search stopped at the 32 MiB scan budget"})
            truncated = True
            break
        total += size
        accepted.append((relative, path))
    return accepted, errors, truncated



def search(
    workspace: str | os.PathLike[str] | None,
    query: str,
    *,
    regex: bool = False,
    paths: Iterable[str | os.PathLike[str]] | None = None,
    limit: int = DEFAULT_MAX_RESULTS,
    max_files: int = DEFAULT_MAX_PATHS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
) -> dict[str, Any]:
    """Search bounded candidate files; literal mode is the default."""
    root = _workspace(workspace)
    if not isinstance(query, str) or not query or "\0" in query:
        raise RetrievalError("Search query must be a nonempty string without NUL characters")
    limit = _positive("limit", limit, 2000)
    max_files = _positive("max_files", max_files, 2000)
    max_output_bytes = _positive("max_output_bytes", max_output_bytes, 1024 * 1024)
    max_line_bytes = _positive("max_line_bytes", max_line_bytes, 64 * 1024)
    if max_output_bytes < 512:
        raise RetrievalError("max_output_bytes must be at least 512")
    expression = None
    if regex:
        try:
            expression = re.compile(query)
        except re.error as exc:
            raise RetrievalError(f"Invalid regular expression: {exc}") from exc
    candidates, candidate_truncated, git_aware = _candidate_paths(root, paths, max_files)
    candidates, scan_errors, scan_truncated = _bounded_search_candidates(candidates)
    engine = "python"
    errors: list[dict[str, str]] = list(scan_errors)
    if not regex and (rg := shutil.which("rg")):
        searchable: list[tuple[str, Path]] = []
        for relative, path in candidates:
            try:
                with path.open("rb") as stream:
                    binary = b"\0" in stream.read(8192)
            except OSError as exc:
                errors.append({"code": "read_error", "path": relative, "message": str(exc)[:200]})
                continue
            if binary:
                errors.append({"code": "binary_file", "path": relative, "message": "Binary content was skipped"})
            else:
                searchable.append((relative, path))
        results, truncated, engine_errors = _rg_search(rg, root, searchable, query, limit, max_line_bytes)
        errors.extend(engine_errors)
        engine = "rg"
        if engine_errors and not results and engine_errors[0]["code"] == "rg_failed":
            results, fallback_truncated, fallback_errors = _python_search(
                searchable, query, None, limit, max_line_bytes
            )
            truncated = truncated or fallback_truncated
            errors.extend(fallback_errors)
            engine = "python"
    else:
        results, truncated, fallback_errors = _python_search(candidates, query, expression, limit, max_line_bytes)
        errors.extend(fallback_errors)
    results.sort(key=lambda item: (item["path"], item["line"]))
    return _response(
        "search", root, results=results, errors=errors,
        truncated=truncated or candidate_truncated or scan_truncated, engine=engine,
        discovery="explicit" if paths is not None else ("git" if git_aware else "filesystem"),
        max_output_bytes=max_output_bytes,
    )


def _read_physical_line(
    stream: Any, max_line_bytes: int, scan_budget: int, bytes_before: int,
) -> tuple[bytes, bool, int, bool]:
    raw = stream.readline(max_line_bytes + 3)
    if not raw:
        return b"", False, 0, False
    consumed = len(raw)
    binary = b"\0" in raw
    terminated = raw.endswith(b"\n")
    content = raw[:-1] if terminated else raw
    if content.endswith(b"\r"):
        content = content[:-1]
    clipped = len(content) > max_line_bytes
    if clipped and not terminated:
        while True:
            remaining = scan_budget - bytes_before - consumed
            if remaining <= 0:
                raise RetrievalError("Requested line range exceeds the bounded scan budget")
            chunk = stream.readline(min(64 * 1024, remaining + 1))
            consumed += len(chunk)
            binary = binary or b"\0" in chunk
            if not chunk or chunk.endswith(b"\n"):
                break
    return content[:max_line_bytes], clipped, consumed, binary


def _decode_excerpt_line(raw: bytes, clipped: bool, relative: str, line_number: int, max_line_bytes: int) -> str:
    candidate = raw
    while True:
        try:
            text = candidate.decode("utf-8")
            break
        except UnicodeDecodeError as exc:
            if clipped and exc.reason == "unexpected end of data" and exc.end == len(candidate) and candidate:
                candidate = candidate[:-1]
                continue
            raise RetrievalError(f"Source line is not valid UTF-8: {relative}:{line_number}") from exc
    if clipped:
        payload_limit = max(0, max_line_bytes - len("…".encode("utf-8")))
        while len(text.encode("utf-8")) > payload_limit and text:
            text = text[:-1]
        text += "…"
    return text



def context(
    workspace: str | os.PathLike[str] | None,
    path: str | os.PathLike[str],
    start_line: int,
    end_line: int,
    *,
    max_lines: int = 200,
    max_output_bytes: int = 16 * 1024,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
) -> dict[str, Any]:
    """Read an exact one-based line range and return the next continuation line."""
    root = _workspace(workspace)
    max_lines = _positive("max_lines", max_lines, 2000)
    max_output_bytes = _positive("max_output_bytes", max_output_bytes, 1024 * 1024)
    max_line_bytes = _positive("max_line_bytes", max_line_bytes, 64 * 1024)
    if max_output_bytes < 512:
        raise RetrievalError("max_output_bytes must be at least 512")
    if type(start_line) is not int or type(end_line) is not int or start_line < 1 or end_line < start_line:
        raise RetrievalError("Line range must be a positive, inclusive start/end pair")
    if end_line - start_line + 1 > max_lines:
        raise RetrievalError(f"Requested line range exceeds max_lines ({max_lines})")
    relative, target = _resolve_file(root, path)
    lines: list[dict[str, Any]] = []
    total = 0
    scan_budget = max(1024 * 1024, min(start_line * max_line_bytes, 16 * 1024 * 1024))
    try:
        with target.open("rb") as stream:
            for number in range(1, end_line + 1):
                if total > scan_budget:
                    raise RetrievalError("Requested line range exceeds the bounded scan budget")
                raw, clipped, consumed, binary = _read_physical_line(
                    stream, max_line_bytes, scan_budget, total
                )
                if not consumed:
                    break
                total += consumed
                if number < start_line:
                    continue
                if binary:
                    raise RetrievalError(f"Binary source is not suitable for a text excerpt: {relative}")
                text = _decode_excerpt_line(raw, clipped, relative, number, max_line_bytes)
                lines.append({"line": number, "text": text, "line_truncated": clipped})
    except OSError as exc:
        raise RetrievalError(f"Could not read source path {relative}: {exc}") from exc
    result = _response("context", root, results=lines, max_output_bytes=max_output_bytes)
    result["path"] = relative
    result["requested_range"] = {"start": start_line, "end": end_line}
    result["next_line"] = (lines[-1]["line"] + 1) if lines else start_line
    while _encoded_size(result) > max_output_bytes:
        if not result["results"]:
            raise RetrievalError("Output byte limit is too small for excerpt metadata")
        removed = result["results"].pop()
        result["next_line"] = removed["line"]
        result["truncated"] = True
        result["status"] = "partial"
    return result
