"""File/URL I/O helpers (with simple archive utilities kept for tests)."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Set


def read_urls_from_files(paths: Iterable[Path]) -> List[str]:
    """
    Read all non-comment, non-empty lines from the provided files.
    - Full-line comments starting with '#', ';', or ']' are ignored.
    - Inline comments after ' # ' or ' ; ' are stripped.
    Returns de-duplicated (stable order) list of URLs.
    """
    out: List[str] = []
    for p in paths:
        p = Path(p)
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for ln in text.splitlines():
            s = ln.strip()
            if not s:
                continue
            head = s.lstrip()
            if head.startswith("#") or head.startswith(";") or head.startswith("]"):
                continue
            # strip "inline" comments that follow a space + delimiter
            # (keeps URL fragments like '#scene-123' which have no leading space)
            for token in (" # ", " ; "):
                idx = s.find(token)
                if idx != -1:
                    s = s[:idx].strip()
                    break
            if s:
                out.append(s)
    # stable de-dup
    seen: Set[str] = set()
    uniq: List[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


# --- Archive helpers (kept for tests & optional usage) ---

def load_archive(path: Path) -> Set[str]:
    """
    Load archive file as a set of trimmed lines.
    Non-existent file -> empty set.
    """
    p = Path(path)
    if not p.exists():
        return set()
    try:
        return {
            ln.strip()
            for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines()
            if ln.strip()
        }
    except Exception:
        return set()


def write_to_archive(path: Path, url: str) -> None:
    """
    Append a single URL (trimmed) to the archive file, creating parents as needed.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(url.strip() + "\n")


def expand_url_dirs(dirs: Iterable[Path]) -> List[Path]:
    """
    Collect *.txt files from the given directories (non-recursive), sorted.
    """
    out: List[Path] = []
    for d in dirs:
        d = Path(d)
        if d.is_dir():
            out.extend(sorted(d.glob("*.txt")))
    return out
