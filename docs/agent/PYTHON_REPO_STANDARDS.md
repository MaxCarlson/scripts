# Reusable Python Repository Standards

This file contains Python conventions reusable across repositories. Repo-specific exceptions belong in `REPO_LLM_INSTRUCTIONS.md` or a repo-specific standards file.

## Versioning

Use semantic version intent: `MAJOR.MINOR.PATCH`.

- MAJOR: breaking public interface change, renamed/removed CLI flag, incompatible output format, or published entry-point change.
- MINOR: backward-compatible feature, new option, new subcommand, meaningful behavior addition, dependency change, metadata change, or build/install behavior change.
- PATCH: bug fix, refactor, docs, tests, or internal improvement with no user-facing feature.

`PATCH` must not be used for new functionality.

For Python packages, bump `pyproject.toml` `[project]` version. If the package exposes `__version__`, keep it in sync.

For standalone Python scripts, embed `__version__` after the module docstring and before imports:

```python
#!/usr/bin/env python3
"""
my_script.py — one-line description.
"""

__version__ = "0.1.0"

import argparse
```

Every modification to a standalone script must bump `__version__`.

## CLI Design

Every user-facing argument must have both a short and long form:

```python
parser.add_argument("-t", "--threads", ...)
parser.add_argument("-n", "--dry-run", ...)
```

Use argparse subcommands when a CLI has more than 7 distinct flags or multiple distinct operating modes.

Preferred common flags:

| Purpose | Short | Long |
|---|---:|---|
| Verbose | `-v` | `--verbose` |
| Quiet | `-q` | `--quiet` |
| Dry run | `-n` | `--dry-run` |
| Force | `-f` | `--force` |
| Output dir | `-o` | `--output-dir` |
| Input file | `-i` | `--input-file` |
| Config | `-c` | `--config` |
| Threads | `-t` | `--threads` |

Destructive actions should default to dry-run or require an explicit force/apply flag.

## Testing

Use `pytest` for normal, edge, and failure cases.

Test files use suffix naming:

```text
tests/module_name_test.py
```

Prefer `tmp_path` for filesystem tests. Do not write to relative scratch paths from tests.

Coverage expectations:

- happy path plus at least one edge/error case per public function,
- mocks for filesystem, network, environment variables, and subprocesses when appropriate,
- no live external service calls in default CI tests.

## Python Style

- PEP 8-compatible style.
- Line length: 120 unless the repo says otherwise.
- Use `black --line-length 120` when applicable.
- Run `ruff check` when applicable.
- Type hints on public functions and class attributes.
- Prefer `pathlib.Path` over `os.path`.
- Use `logging` in library code. `print` is acceptable in CLI entry points.
- Standard library imports first, then third-party, then local imports, separated by blank lines.
- No wildcard imports.

## Error Handling

- Raise and catch specific exceptions.
- Error messages should state what failed and what the user can do next.
- Use broad `except Exception` only in top-level CLI handlers or narrow I/O boundaries.

## Comments

Comment the non-obvious why: invariants, workarounds, compatibility constraints, or external assumptions.

Do not explain obvious code behavior in comments. Prefer clear names.

## Cross-Platform Requirements

Write code that works on Windows 11, WSL2/Linux, and Termux when feasible.

Important differences:

| Platform | Notes |
|---|---|
| Windows 11 | PowerShell 7+, backslash paths, `Scripts/` venv directory. |
| WSL2/Linux | Bash/Zsh, `bin/` venv directory. |
| Termux | Prefer Termux package manager for system deps; hardlinks may fail; paths and permissions differ. |

Use repo-provided platform utilities when available. Avoid direct platform checks scattered across code.
