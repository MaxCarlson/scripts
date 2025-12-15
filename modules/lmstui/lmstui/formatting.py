from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Sequence, Tuple


def format_table(rows: List[Dict[str, Any]], columns: Sequence[Tuple[str, str]]) -> str:
    """
    columns: list of (key, header)
    """
    col_widths: List[int] = []
    for key, header in columns:
        w = len(header)
        for r in rows:
            v = r.get(key, "")
            w = max(w, len(str(v)))
        col_widths.append(w)

    parts: List[str] = []
    header_cells: List[str] = []
    for (key, header), w in zip(columns, col_widths):
        header_cells.append(header.ljust(w))
    parts.append("  ".join(header_cells))

    sep_cells: List[str] = []
    for w in col_widths:
        sep_cells.append("-" * w)
    parts.append("  ".join(sep_cells))

    for r in rows:
        cells: List[str] = []
        for (key, _), w in zip(columns, col_widths):
            cells.append(str(r.get(key, "")).ljust(w))
        parts.append("  ".join(cells))

    return "\n".join(parts)


def pretty_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)


def one_line(s: str) -> str:
    return " ".join((s or "").split())


def safe_get(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default
