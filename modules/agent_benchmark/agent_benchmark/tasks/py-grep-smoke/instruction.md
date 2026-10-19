# Task: Substring Grep (Smoke)

Implement the `grep` function in `grep.py`.

## Specification

```python
def grep(pattern: str, lines: list[str], ignore_case: bool = False) -> list[str]:
    ...
```

- **Substring Match**: Match lines containing `pattern` as a literal substring. Do NOT use regular expression pattern matching; special characters (such as `.`, `*`, `[`, `]`, `?`, `+`, `^`, `$`, `\`) must be treated as literal characters.
- **Order & Duplicates**: Preserve the original order of lines from `lines`. Retain duplicate lines if they match.
- **Case Sensitivity**:
  - If `ignore_case` is `False` (default), perform exact case-sensitive substring matching.
  - If `ignore_case` is `True`, perform case-insensitive substring matching.
  - Returned lines must preserve their original casing from `lines`.
- **Empty Strings**:
  - An empty `pattern` (`""`) matches all lines in `lines`.
  - If `lines` is empty, return an empty list `[]`.
- **Unicode**:
  - Correctly handle Unicode strings (e.g. accented characters, non-ASCII text).
- **Constraints**:
  - Only edit `grep.py`.
  - Do not spawn background processes or install external packages.
