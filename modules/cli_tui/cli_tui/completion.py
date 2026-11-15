from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple


def extract_token_at_cursor(
    text: str,
    cursor_pos: int,
    *,
    is_multi_token: bool = False,
) -> Tuple[int, int, str, Optional[str]]:
    """Return ``(start, end, unquoted_prefix, quote_char)`` for the token at ``cursor_pos``.

    For single-value arguments (``is_multi_token=False``), the entire text is
    treated as one path token so spaces in paths are preserved without quoting.
    For multi-token arguments (``append``, ``extend``, ``nargs``), tokens are
    split on unquoted whitespace.
    """
    cursor = max(0, min(len(text), cursor_pos))
    if not is_multi_token:
        prefix = text[:cursor]
        quote_char: Optional[str] = None
        if prefix.startswith(('"', "'")):
            quote_char = prefix[0]
            prefix = prefix[1:]
        return 0, len(text), prefix, quote_char

    tokens: List[Tuple[int, int, Optional[str]]] = []
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        start = i
        quote_char = None
        if text[i] in ('"', "'"):
            quote_char = text[i]
            i += 1
            while i < n and text[i] != quote_char:
                i += 1
            if i < n and text[i] == quote_char:
                i += 1
        else:
            while i < n and not text[i].isspace():
                i += 1
        tokens.append((start, i, quote_char))

    for start, end, qchar in tokens:
        if start <= cursor <= end:
            raw_prefix = text[start:cursor]
            if qchar and raw_prefix.startswith(qchar):
                raw_prefix = raw_prefix[1:]
            return start, end, raw_prefix, qchar

    return cursor, cursor, "", None


def format_completed_token(
    candidate: str,
    *,
    is_multi_token: bool = False,
    quote_char: Optional[str] = None,
) -> str:
    """Format a completed path candidate for insertion back into the widget."""
    if quote_char:
        return f"{quote_char}{candidate}{quote_char}"
    if is_multi_token and any(ch.isspace() for ch in candidate):
        return f'"{candidate}"'
    return candidate


def complete_path_prefix(
    prefix: str,
    working_dir: Optional[Path | str] = None,
) -> List[str]:
    """Return sorted path completions for ``prefix`` relative to ``working_dir``."""
    base_dir = Path(working_dir) if working_dir is not None else Path.cwd()

    if prefix == "~":
        return ["~/"]

    sep = "\\" if ("\\" in prefix and "/" not in prefix) else "/"
    last_sep = max(prefix.rfind("/"), prefix.rfind("\\"))

    if last_sep >= 0:
        dir_part = prefix[: last_sep + 1]
        name_prefix = prefix[last_sep + 1 :]
    else:
        dir_part = ""
        name_prefix = prefix

    if not dir_part:
        search_dir = base_dir
    elif dir_part.startswith(("~/", "~\\")):
        rel = dir_part[2:]
        search_dir = Path.home() / rel if rel else Path.home()
    else:
        dir_path = Path(dir_part)
        search_dir = dir_path if dir_path.is_absolute() else (base_dir / dir_path)

    case_insensitive = os.name == "nt"
    target_prefix = name_prefix.lower() if case_insensitive else name_prefix
    include_hidden = name_prefix.startswith(".")

    matches: List[str] = []
    try:
        with os.scandir(search_dir) as entries:
            for entry in entries:
                name = entry.name
                if not include_hidden and name.startswith("."):
                    continue
                cmp_name = name.lower() if case_insensitive else name
                if not cmp_name.startswith(target_prefix):
                    continue
                try:
                    is_dir = entry.is_dir()
                except OSError:
                    is_dir = False
                suffix = sep if is_dir else ""
                matches.append(f"{dir_part}{name}{suffix}")
    except OSError:
        return []

    matches.sort(key=lambda item: item.lower())
    return matches
