# Scripts Repository — Module Standards

Reference this file when working on any module in this repository.  All AI
coding assistants (Claude Code, GitHub Copilot, Cursor, Codex, Gemini CLI)
should treat these guidelines as binding conventions.

---

## 1. Module Version Numbering  `MAJOR.MINOR.PATCH`

```
 X  .  Y  .  Z Z Z
 │     │     └── PATCH — fixes/refactors/docs/tests; no new user-facing feature
 │     └──────── MINOR — backward-compatible feature or install metadata change
 └────────────── MAJOR — breaking change, plus entry-point regeneration rule below
```

This repository follows standard semantic-version intent: `Z` is the PATCH
number and must not be used for new functionality. A backward-compatible new
feature is a MINOR (`Y`) change even when the implementation touches only
Python source. One repository-specific operational exception remains: any
change to published entry points is treated as MAJOR so setup recreates command
wrappers reliably.

### What each level means for setup/reinstall

| Changed | Level | `setup.py` / `bootstrap` action required |
|---------|-------|------------------------------------------|
| Bug fix, refactor, docs, or tests only | PATCH | **Nothing** — editable install picks up source changes automatically |
| Backward-compatible feature addition, or `pyproject.toml` deps/metadata change | MINOR | `pip install -e .` — existing `.cmd` files stay valid |
| `[project.scripts]` entry points added, removed, or renamed | MAJOR | `pip uninstall <pkg> && pip install -e .` — `.cmd` files in `bin/` must be regenerated |

### Decision rule for `setup.py` / `bootstrap.ps1` / `bootstrap.sh`

```python
installed = get_installed_version(pkg_name)   # via importlib.metadata
source    = get_pyproject_version(module_dir)  # read pyproject.toml

if source_major > installed_major:
    # Entry points changed → force full reinstall to regenerate .cmd
    pip_uninstall_then_install(module_dir)
elif source_minor > installed_minor:
    # Deps/metadata changed → reinstall only (no .cmd recreation)
    pip_install_e(module_dir)
# else: only patch changed (or equal) → nothing needed
```

### When to bump which digit

**Bump MAJOR** when any of these change in `pyproject.toml`:
- `[project.scripts]` — entry added, removed, or renamed
- `[project.entry-points]` — any plugin/console entry point

**Bump MINOR** for backward-compatible user-facing functionality and for these
`pyproject.toml` changes (when entry points are unchanged):
- new feature, new option, new subcommand, or meaningful behavior addition
- `[project.dependencies]` — new or removed package
- `[project.optional-dependencies]` — new extras
- `requires-python` version
- `[tool.*]` build-system changes that affect installation

**Bump PATCH** for everything else:
- Bug fixes and refactoring that do not add user-facing functionality
- Test changes
- Documentation updates
- Internal restructuring that doesn't affect the public CLI surface

### Commit message convention

```
bump: ytaedl 1.12.1 → 2.0.0  (MAJOR: entry points changed)
bump: mymodule 2.0.0 → 2.1.0  (MINOR: added requests dependency)
bump: mymodule 2.1.0 → 2.1.1  (PATCH: fixed edge case in downloader)
```

---

## 2. CLI Design

### Subcommand threshold

Use argparse **subcommands** when a module's CLI has **more than 7 distinct
flags** OR has meaningfully different operating modes.  See `ytaedl` as the
canonical example:

```
ytaedl run       [core flags]
ytaedl run watcher   [core + watcher flags]
ytaedl cleanup   partial|index
ytaedl worker    [flags]
ytaedl urls / archive
```

Benefits: focused help per subcommand, independent flag namespaces (no
short-flag collisions across modes), easier extension later.

### Flag naming — MANDATORY

**Every argument must have both a `--full-long-name` AND a `-X` short form.**
No exceptions.  Short forms use a single dash and one upper- or lower-case
letter.

```python
# ✅ Correct
parser.add_argument("-t", "--threads", ...)
parser.add_argument("-P", "--proxy-dl-location", ...)
parser.add_argument("-n", "--dry-run", ...)

# ❌ Wrong — missing short form
parser.add_argument("--threads", ...)

# ❌ Wrong — missing long form
parser.add_argument("-t", ...)
```

Hidden/internal flags (set by the manager, not user-facing) may use
`help=argparse.SUPPRESS` but must still have both forms.

### Coloured help for sub-subcommands

When a subcommand has its own sub-subcommands (e.g. `ytaedl run watcher`),
use `ColoredSectionHelpFormatter` from `ytaedl._cli_help` as a pattern to
show ANSI-coloured sections per profile in `--help` output.

### Common flag conventions

| Purpose | Preferred short | Preferred long |
|---------|-----------------|---------------|
| Verbose | `-v` | `--verbose` |
| Quiet | `-q` | `--quiet` |
| Dry-run | `-n` | `--dry-run` |
| Force | `-f` | `--force` |
| Output dir | `-o` | `--output-dir` |
| Input file | `-i` | `--input-file` |
| Config file | `-c` | `--config` |
| Threads | `-t` | `--threads` |

---

## 3. Testing

### File naming

```
tests/module_name_test.py   ✅  (suffix _test.py)
tests/test_module.py        ❌  (old pytest style — do not use)
```

### Fixtures

Always use `tmp_path` for filesystem tests.  Never write to relative paths
in tests (no `./stars/`, `./logs/`, etc.).

### Temp roots

Module tests must keep generated temp directories inside the owning module
directory unless the user explicitly asks for another location.  On Windows,
if pytest or `tempfile` needs a custom writable temp root, prefer:

```
modules/<module>/.pytest_tmp_root/<module>-temp-<pid>/
```

Do not create repo-root scratch folders such as `.tmp-<module>-run/`,
`codex_tmp_test/`, or `pytest-of-<user>/` from module tests.  If a module needs
an ignored runtime scratch directory, document it in that module and add a
targeted ignore rule.

### Coverage expectations

- Happy path + at least one error/edge case per public function
- Mocks: filesystem (tmp_path), network, env vars, subprocesses (`unittest.mock`)
- No integration tests against live external services in CI

---

## 4. Python Code Standards

### Style

- **PEP 8** compliant; line length 120 (`black --line-length 120`)
- **`ruff check`** for linting before commit
- **Type hints** on all public functions and class attributes
- **`pathlib.Path`** everywhere — no `os.path` unless unavoidable
- **`logging`** not `print` in library code; `print` is fine in CLI entry points

### Imports

- Standard library first, then third-party, then local — separated by blank lines
- No wildcard imports

### Error handling

- Raise specific exceptions; catch specific exceptions
- Actionable error messages: what went wrong + what to do
- `try/except Exception` only in top-level CLI handlers or I/O wrappers

### Comments

- Only when the **WHY** is non-obvious (hidden constraint, workaround, invariant)
- Never explain WHAT the code does — good names do that
- No task/fix/PR references in code comments (put those in commit messages)

---

## 5. Cross-Platform Requirements

All modules must explicitly handle:

| Platform | Key differences |
|----------|----------------|
| **Windows 11** | PowerShell 7+, backslash paths, `Scripts\` venv dir |
| **Termux (Android)** | `pkg install uv` (not pip/cargo), `UV_LINK_MODE=copy`, no hardlinks, `pkg install patchelf` for native builds |
| **WSL2 (Ubuntu)** | Bash + Zsh, `bin/` venv dir, may share files with Windows |

Use `SystemUtils` from `cross_platform` for OS detection.  Never use `sys.platform == "win32"` directly in module code.

---

## 6. Module Dependency Ordering

When adding a new module that depends on core modules, ensure it installs
AFTER its dependencies.  The core order is fixed:

1. `standard_ui` — no dependencies
2. `cross_platform` — no dependencies
3. `python_setup` — depends on `cross_platform`
4. `scripts_setup` — no dependencies

All other modules: declare deps in `pyproject.toml`; `dependency_resolver.py`
handles ordering automatically.

---

## 7. Partial / Temp File Conventions  (ytaedl-specific)

When a module manages per-operation working directories:

- Use `_partial/<hash12>/` pattern (sha256 of key, first 12 hex chars)
- Write a `meta.json` sentinel before starting any work
- Delete the working dir on **success**; keep on failure (for resume)
- Write an empty `.ignore` in any subdir of a media/library folder to prevent
  Jellyfin (or similar) from indexing in-progress files
- Track format version in `_partial/.version` using the scheme in §1 above

---

## 8. Entry Point / `.cmd` File Conventions

Console scripts are defined in `[project.scripts]` in `pyproject.toml`.
The `.cmd` wrapper in `.venv/Scripts/` is generated by `pip install`.

- **Never hardcode** `.cmd` paths — always go through `$PATH` / the venv
- When you add, rename, or remove a script, **bump the MAJOR version** and
  document the change in `pyproject.toml`'s changelog comment
- The `setup.py` installer will detect the major bump and force reinstall

---

## 9. Planning Artifacts

All implementation plans, investigations, and durable handoff notes belong
under the repository-level `plans/` directory. Do not leave canonical plans
inside module subdirectories.

- Use `plans/modules/<module>/` for module-specific plans.
- Module plan directories should use this taxonomy when they contain more than
  one durable plan:
  - `INDEX.md` is the canonical registry.
  - `user/` contains user-authored plans or raw user requests.
  - `ai/` contains assistant interpretations, implementation plans, and status
    notes.
  - `ai/perma/` may contain durable reusable plan templates that are not one
    execution instance. Keep these stable and reference them from indexed plans.
  - Plan filenames use
    `<index>_<yyyymmdd-HHMM|yyyymmdd-unknown>_<origin>_<slug>__<status>.md`.
    Example: `0005_20260509-1700_ai_codex-plan-plus-1__implemented.md`.
  - Status values are `planned`, `in_progress`, `implemented`, `partial`,
    `superseded`, and `deferred`.
- Keep older plans instead of deleting them. Move or rename superseded plans
  into the taxonomy and mark the status in both filename and metadata.
- A module may keep short status notes, but canonical current status should be
  discoverable from `plans/modules/<module>/INDEX.md`.
- If a plan is moved from a module-local folder, preserve the old content under
  `plans/` before removing the duplicate module-local copy.

---

## 10. pyscript Versioning  `MAJOR.MINOR.PATCH`

Standalone scripts in `pyscripts/` embed a `__version__` string directly in
the file.  This is the single source of truth for pyscript versions.

### Placement

Place `__version__` immediately **after the module docstring** (or after the
shebang / coding declaration if there is no docstring), before the first
`import` statement:

```python
#!/usr/bin/env python3
"""
my_script.py — one-line description.
"""

__version__ = "0.1.0"

import argparse
import sys
```

If a coding declaration is present it stays on line 2; `__version__` still
goes after the docstring:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module docstring."""

__version__ = "0.1.0"

import sys
```

### Bump rules for pyscripts

pyscripts have no `pyproject.toml`, so the entry-point / dep rules from §1
do not apply.  Use this simpler scheme:

| Changed | Level | Example |
|---------|-------|---------|
| Breaking: renamed/removed flag, incompatible output format | **MAJOR** | `1.0.0 → 2.0.0` |
| New feature, new flag, new subcommand, significant behavior addition | **MINOR** | `0.1.0 → 0.2.0` |
| Bug fix, refactoring, doc update, internal improvement with no new feature | **PATCH** | `0.1.0 → 0.1.1` |

### Reading a pyscript's version

```python
import re
text = open("pyscripts/my_script.py").read(2000)
m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
version = m.group(1) if m else None
```

### Commit convention

```
bump: my_script.py 0.1.0 → 0.2.0  (MINOR: added --output-dir flag)
bump: my_script.py 0.1.0 → 0.1.1  (PATCH: fixed edge case in path handling)
```

---

## AI Assistant Usage Notes

When an AI coding assistant (Claude Code, Copilot, Cursor, Codex, Gemini)
proposes changes to this repository, it should:

**For modules (`modules/`):**
1. Check whether `[project.scripts]` is changing → if yes, bump MAJOR
2. Check whether there is a backward-compatible new feature or a non-scripts
   `pyproject.toml` change → if yes, bump MINOR
3. For fixes/refactors/docs/tests only, with no new user-facing feature → bump PATCH
4. Update the version in `pyproject.toml` AND in `__init__.py` (if it has one)

**For pyscripts (`pyscripts/`):**
5. Every new pyscript must include `__version__ = "0.1.0"` after the docstring
6. Every modification must bump `__version__` following the rules in §10
7. Breaking flag/output changes → MAJOR; new features/flags → MINOR; fixes/refactors/docs only → PATCH

**For all code:**
8. Ensure every new argument has both short and long forms
9. Prefer subcommands over flat flags when > 7 arguments
10. Never add a flag without both `-X` and `--full-name` forms
11. Use `tests/*_test.py` naming for new test files
12. Put all durable plans under `plans/` and retain superseded plans there
13. Run `pytest` and `ruff check` before reporting a task complete

**Help registry (`modules/scripts_help`):**
14. After adding a new pyscript or module-with-CLI, add an entry to
    `modules/scripts_help/scripts_help/registry/registry.py`
15. If updating an existing entry's description, update the `"version"` field
    to match the current live version so the staleness check stays quiet
