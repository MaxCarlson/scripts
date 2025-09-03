# cross_platform Module

A collection of small, focused utilities that make your scripts **portable** across Windows 11, WSL2, and Termux. The goal is to centralize common patterns—filesystem walking, path printing, safe deletion, and more—so your scripts stay lean and robust.

## Key Principles

- **No surprises:** Helpers never raise on routine tasks like formatting a relative path.
- **Pure & composable:** Return plain data (lists, dicts, strings). Callers decide how to print or log.
- **Cross-platform first:** Handle Windows drive letters/anchors, Linux paths, symlinks, and case differences gracefully.
- **Stable surfaces:** Functions are small, with predictable signatures that are easy for humans and LLMs to use.

## Submodules

- `cross_platform.fs_utils` — Filesystem helpers (path normalization, scanning, deletion, safe relative paths, summaries).
- Other submodules (e.g., `debug_utils`, `process_manager`, etc.) exist in this package; this README focuses on `fs_utils` because it underpins many scripts.

## Quickstart

```python
from pathlib import Path
from cross_platform.fs_utils import (
    scanned_files_by_extension,
    aggregate_counts_by_parent,
    dir_summary_lines,
    relpath_str,
    delete_files,
)

root = Path("stars")               # user-facing path (relative is fine)
result = scanned_files_by_extension(root, "jpg")

print(f"Searched {len(result.searched_dirs)} directories.")
print(f"Found {len(result.matched_files)} *.jpg files.")

# Per-directory summary (safe across OSes; never raises)
counts = aggregate_counts_by_parent(result.matched_files)
for line in dir_summary_lines(root, counts, top_n=50, show_all=False, absolute_paths=False):
    print(line)

# Dry run pattern; actually delete when you're ready
# failures = delete_files(result.matched_files)
# if failures:
#     for p, ex in failures:
#         print(f"Failed to delete {p}: {ex}", file=sys.stderr)
```
