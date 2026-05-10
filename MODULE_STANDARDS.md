# Scripts Repository — Module Standards

Reference this file when working on any module in this repository.  All AI
coding assistants (Claude Code, GitHub Copilot, Cursor, Codex, Gemini CLI)
should treat these guidelines as binding conventions.

---

## 1. Module Version Numbering  `MAJOR.MINOR.PATCH`

```
 X  .  Y  .  Z Z Z
 │     │     └── PATCH — Python source changes only (bug fixes, features)
 │     └──────── MINOR — pyproject.toml changes OTHER than entry points
 └────────────── MAJOR — [project.scripts] entry points changed
```

### What each level means for setup/reinstall

| Changed | Level | `setup.py` / `bootstrap` action required |
|---------|-------|------------------------------------------|
| `.py` files only | PATCH | **Nothing** — editable install picks up changes automatically |
| `pyproject.toml` deps or metadata (not scripts) | MINOR | `pip install -e .` — existing `.cmd` files stay valid |
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

**Bump MINOR** when any of these change in `pyproject.toml` (but not scripts):
- `[project.dependencies]` — new or removed package
- `[project.optional-dependencies]` — new extras
- `requires-python` version
- `[tool.*]` build-system changes that affect installation

**Bump PATCH** for everything else:
- Bug fixes, new features, refactoring in `.py` files
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

## AI Assistant Usage Notes

When an AI coding assistant (Claude Code, Copilot, Cursor, Codex, Gemini)
proposes changes to a module in this repository, it should:

1. Check whether `[project.scripts]` is changing → if yes, bump MAJOR
2. Check whether `pyproject.toml` is changing (non-scripts) → if yes, bump MINOR
3. Check whether only `.py` files are changing → bump PATCH
4. Ensure every new argument has both short and long forms
5. Prefer subcommands over flat flags when > 7 arguments
6. Never add a flag without both `-X` and `--full-name` forms
7. Use `tests/*_test.py` naming for new test files
8. Put all durable plans under `plans/` and retain superseded plans there
9. Run `pytest` and `ruff check` before reporting a task complete
