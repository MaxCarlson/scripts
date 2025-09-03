# File: scripts/modules/code_tools/rgcodeblock_lib/language_defs.py
from __future__ import annotations

from pathlib import Path
from typing import Tuple

LANGUAGE_DEFINITIONS = {
    "python": {"extensions": [".py"], "notes": "AST-based extraction"},
    "brace": {
        "extensions": [
            ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx",
            ".java", ".js", ".jsx", ".ts", ".tsx",
            ".cs", ".go", ".swift", ".rs", ".kt", ".kts",
            ".scss", ".css",
        ],
        "notes": "Brace counting around nearest '{'",
    },
    "json": {"extensions": [".json", ".json5"], "notes": "Brace/bracket counting"},
    "yaml": {"extensions": [".yaml", ".yml"], "notes": "Indentation / optional PyYAML"},
    "xml": {"extensions": [".xml", ".html", ".xhtml", ".svg"], "notes": "lxml or heuristic tag matching"},
    "ruby": {"extensions": [".rb"], "notes": "def..end / class..end"},
    "lua": {"extensions": [".lua"], "notes": "function..end"},
}

def get_language_type_from_filename(filename: str | Path) -> Tuple[str, str]:
    p = Path(filename)
    ext = p.suffix.lower()
    for lang, meta in LANGUAGE_DEFINITIONS.items():
        if ext in meta.get("extensions", []):
            return lang, ext
    if ext in {".c", ".cpp", ".hpp", ".cc", ".cxx", ".h"}: return "brace", ext
    if ext == ".py": return "python", ext
    if ext in {".json", ".json5"}: return "json", ext
    if ext in {".yaml", ".yml"}: return "yaml", ext
    if ext in {".xml", ".html", ".xhtml", ".svg"}: return "xml", ext
    if ext == ".rb": return "ruby", ext
    if ext == ".lua": return "lua", ext
    return "other", ext
