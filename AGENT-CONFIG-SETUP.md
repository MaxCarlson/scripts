# Agent Config Setup — Handoff for Browser LLM

> **This document is a task brief for a browser-based LLM (Claude.ai, ChatGPT, Gemini web).**
> It is self-contained. You do not need access to the local repository to write the
> implementation. The human will copy the files you produce into the repo.
>
> **Context to attach when opening this task:**
> - This file (`scripts/AGENT-CONFIG-SETUP.md`)
> - `scripts/MODULE_STANDARDS.md`
> - `scripts/setup.py` (for understanding the existing setup structure)
> - `scripts/AGENTS.md`, `scripts/CLAUDE.md`, `scripts/GEMINI.md` (current repo-level configs)
> - `scripts/bootstrap.sh`, `scripts/bootstrap.ps1`

---

## 1. Background and Goal

`~/scripts` is a personal automation scripts repository that runs on three platforms:
- **WSL2 Ubuntu** (primary dev environment, `~` = `/home/mcarls`)
- **Windows 11 PowerShell 7** (`~` = `C:\Users\mcarls`)
- **Termux Android** (`~` = `/data/data/com.termux/files/home`)

AI coding assistants (Claude Code, Codex, Gemini CLI, GitHub Copilot, Cursor, Cline)
each read one or more global config/instruction files from fixed OS-level paths. Right
now those files are managed by a separate `~/dotfiles` repo and its `symlinks.sh`
script.

**Goal:** Move the master global agent config files into `scripts/docs/agent-config/`
and have `scripts/setup.py` (and `bootstrap.sh` / `bootstrap.ps1`) handle creating
and maintaining the symlinks on every platform. The dotfiles repo retains its
`symlinks.sh` but defers to the scripts versions for these specific files.

---

## 2. Current State (what already exists)

### Dotfiles manages symlinks today

`~/dotfiles/symlinked/llms/symlinks.sh` creates:

| Symlink (global location) | Source (dotfiles) |
|---|---|
| `~/.claude/CLAUDE.md` | `dotfiles/symlinked/llms/AGENTS.md` (or `claude/CLAUDE.md` if non-empty) |
| `~/.codex/AGENTS.md` | `dotfiles/symlinked/llms/AGENTS.md` (or `codex/AGENTS.md` if non-empty) |
| `~/.gemini/GEMINI.md` | `dotfiles/symlinked/llms/gemini/GEMINI.md` |
| `~/.claude/settings.json` | `dotfiles/symlinked/llms/claude/settings.json` |
| `~/.gemini/settings.json` | `dotfiles/symlinked/llms/gemini/settings.json` |
| `~/.codex/config.toml` | `dotfiles/symlinked/llms/codex/config.toml` |

The master vendor-neutral instructions live at
`~/dotfiles/symlinked/llms/AGENTS.md` (168 lines, detailed Python/uv style
guidance). Claude-specific global instructions are currently at
`~/dotfiles/symlinked/llms/claude/CLAUDE.md` (which was recently updated with a
"Token Conservation" section — see Section 4 below).

### scripts repo has repo-level configs (not global)

`scripts/AGENTS.md`, `scripts/CLAUDE.md`, `scripts/GEMINI.md` are repo-level
context files read when an agent is *inside* the scripts repo. They are NOT
the global `~/.claude/CLAUDE.md` etc. — they are separate.

---

## 3. Desired End State

### New directory: `scripts/docs/agent-config/`

This becomes the single source of truth for global agent configs. Files here
are symlinked to the appropriate OS-level paths on each machine.

```
scripts/
  docs/
    agent-config/
      AGENTS.md               # Master vendor-neutral instructions (all LLM CLIs)
      CLAUDE.md               # Claude Code global instructions (~/.claude/CLAUDE.md)
      GEMINI.md               # Gemini CLI global instructions (~/.gemini/GEMINI.md)
      copilot-instructions.md # GitHub Copilot global instructions (see note below)
```

> **Note on Copilot:** GitHub Copilot reads per-repo `.github/copilot-instructions.md`
> files; there is no single global path. Include `copilot-instructions.md` in this
> directory as a canonical template to be copied (not symlinked) into new repos, not
> as a symlink target.

### Global symlink targets per platform

| Global path (all platforms) | Source file |
|---|---|
| `~/.claude/CLAUDE.md` | `scripts/docs/agent-config/CLAUDE.md` |
| `~/.codex/AGENTS.md` | `scripts/docs/agent-config/AGENTS.md` |
| `~/.gemini/GEMINI.md` | `scripts/docs/agent-config/GEMINI.md` |

Platform-specific paths:
- **WSL2 / Termux:** `~` = `$HOME` (POSIX). Symlinks via `os.symlink()` or `Path.symlink_to()`.
- **Windows 11:** `~` = `%USERPROFILE%`. Symlinks require Developer Mode or admin.
  Use `Path.symlink_to()` — Python on Windows with Developer Mode enabled creates
  symlinks without elevation. Fall back to a warning if it fails.

### `setup.py` changes

Add a new setup group called `"Agent Config Symlinks"` that:
1. Resolves the `scripts/docs/agent-config/` directory
2. Creates the three symlinks above (parent dirs created if missing)
3. Logs each symlink action (created / already correct / updated)
4. Handles Windows symlink permission errors gracefully (warn, don't abort)
5. Handles Termux (same as Linux — no special case needed)

### `bootstrap.sh` / `bootstrap.ps1` changes

These scripts just call `setup.py`, so no direct changes are needed beyond what
`setup.py` does. However, add a note in each bootstrap script's header comment
pointing to `docs/agent-config/` as the place to edit global agent instructions.

### Dotfiles `symlinks.sh` update

After this change, `dotfiles/symlinked/llms/symlinks.sh` should skip the three
files that scripts now manages. Add guard comments explaining the source of truth
has moved. Keep the `settings.json` and `config.toml` symlinks — those are
settings files (not instructions) and belong in dotfiles.

---

## 4. Content of the Master Config Files

Write these files verbatim. They contain everything an AI coding agent on this
machine needs to know about working preferences.

### `scripts/docs/agent-config/AGENTS.md`

This is the vendor-neutral master. It is read by Codex, Cursor, Cline, GitHub
Copilot (when copied per-repo), and any other agent that consumes `AGENTS.md`.
Claude Code and Gemini CLI each have their own file below, but those files should
IMPORT or REFERENCE these same core rules — do not duplicate content.

```markdown
# AGENTS.md

> Vendor-neutral AI coding agent instructions.
> Compatible with: OpenAI Codex, Claude Code, Cursor, Cline, GitHub Copilot.

<project>
name: [PROJECT_NAME]
language: Python 3.11+
type: [cli-tool | library | web-service | monorepo]
</project>

<stack>
## Runtime
- Python 3.11+ (primary)
- Platforms: WSL2 Ubuntu 22.04+, Windows 11 (PowerShell 7, UTF-8), Termux Android
- Package manager: uv (pip fallback on Termux)
- Virtual env: .venv/ (uv venv)
</stack>

<commands>
## Setup
```bash
uv venv && source .venv/bin/activate  # Linux/macOS/WSL2/Termux
uv venv && .venv\Scripts\Activate.ps1  # Windows
uv sync
```

## Quality
```bash
uv run black .
uv run ruff check --fix .
uv run mypy src/ --strict
uv run pytest tests/ -v --tb=short
```
</commands>

<code_style>
## Python Conventions
- Type hints: mandatory on all public functions and methods
- Docstrings: Google style, imperative first line
- Imports: stdlib | third-party | local (blank line separated, alphabetized)
- Paths: pathlib.Path (never os.path)
- Strings: f-strings (never .format() or %)
- I/O: explicit encoding="utf-8"
- Logging: logging module (never print() for operational output)
- Config: pyproject.toml (no setup.py/setup.cfg for new modules)
</code_style>

<cli_conventions>
ALL CLI arguments MUST have both short and long forms: `-a/--argument-name`.
Parser: argparse with subcommands where appropriate.
Every argument needs help= text.
</cli_conventions>

<testing>
- Test file naming: tests/<module_name>_test.py (never test_<module>.py)
- Coverage: happy path, edge cases, error conditions
- Mock external deps (filesystem, network, env vars)
- Run tests before claiming completion
</testing>

<versioning>
Bump SemVer in pyproject.toml on every module change:
- MAJOR: breaking API changes (entry point wrappers changed)
- MINOR: new backwards-compatible features, pyproject.toml dependency changes
- PATCH: bug fixes, refactoring, docs, tests only — no new user-facing feature
</versioning>

<token_conservation>
## Browser LLM Offloading

Hard token limits apply to Claude Code, Codex, and Gemini CLI. Hitting the limit
triggers a 5-hour lockout. Switching between Claude → Codex → Gemini CLI as limits
are hit is the fallback strategy.

**Always watch for token-intensive tasks that don't need local file access** and
flag them for a browser-based LLM (Claude.ai, ChatGPT, Gemini web):
- Writing implementation plans
- Drafting design docs
- Writing summaries/reports
- Reviewing specs for gaps
- Brainstorming approaches

Tasks that MUST stay local: running tests, editing files, executing commands,
anything requiring live repo access.

**When offloading:**
1. Write a self-contained Markdown handoff document with all context the browser
   LLM needs (specs, plans, relevant code excerpts, clear output instructions)
2. Tell the user which files/folders/repos to attach in the browser LLM session
3. Keep handoff docs concise — no full conversation history needed
</token_conservation>

<constraints>
NEVER:
- Use os.path (use pathlib.Path)
- Use print() for logging (use logging module)
- Hardcode paths
- Skip type hints on public APIs
- Name tests test_*.py (use <module>_test.py)
- Modify files outside project root without confirmation
- Run destructive commands without confirmation

ALWAYS:
- Run tests before claiming completion
- Use .venv/
- Preserve existing code style
- Ask on ambiguous requirements
- Bump version on module changes
</constraints>
```

### `scripts/docs/agent-config/CLAUDE.md`

Claude Code reads `~/.claude/CLAUDE.md` as the global instruction file. This file
extends the vendor-neutral rules above with Claude Code-specific guidance.

```markdown
# Global Defaults — Claude Code

Python 3.11+ | uv package manager | Cross-platform (WSL2, Termux, Windows 11)

> Core coding conventions, testing, and platform rules are in the vendor-neutral
> AGENTS.md (also symlinked). This file adds Claude Code-specific guidance.

## Code Style

- Type hints: mandatory on public functions/methods
- Docstrings: Google style, imperative first line
- Imports: stdlib | third-party | local (blank-line separated, alphabetized)
- Paths: `pathlib.Path` (never `os.path`)
- Strings: f-strings only (never `.format()` or `%`)
- I/O: explicit `encoding="utf-8"`
- Logging: `logging` module (never `print()` for operational output)
- Config: `pyproject.toml` (no setup.py/setup.cfg for new modules)

## CLI Arguments

ALL CLI arguments MUST use `-a/--argument-name` format (both short and long REQUIRED).
Parser: argparse with subcommands where appropriate. Every argument needs `help=` text.

## Quality Tools

```bash
uv run black .                                    # Format
uv run ruff check --fix .                         # Lint
uv run mypy src/ --strict                         # Type check
uv run pytest tests/ -v --tb=short                # Test
```

## Testing

- File naming: `tests/<module_name>_test.py` (never `test_<module>.py`)
- Coverage: happy path, edge cases, error conditions
- Mock external deps (filesystem, network, env vars)
- Run tests before claiming completion

## Version Management

Bump SemVer in `pyproject.toml` on every module change:
- MAJOR: breaking API changes
- MINOR: new backwards-compatible features
- PATCH: bug fixes, refactoring, docs

## Cross-Platform

- Platforms: WSL2 Ubuntu, Windows 11 PowerShell 7, Termux Android
- OS detection: `SystemUtils` class from `cross_platform` module (`is_windows()`, `is_linux()`, `is_termux()`, `is_wsl()`)
- Termux: `UV_LINK_MODE=copy` required, `pkg install uv` (not pip), native compilation often fails
- WSL2: prefer `/home/` over `/mnt/c/` for performance
- Handle path separators via `pathlib`

## Token Conservation — Browser LLM Offloading

Hard token limits apply to Claude Code, Codex, and Gemini CLI. Hitting the limit
triggers a 5-hour lockout. Switching between Claude → Codex → Gemini CLI as limits
are hit is the fallback strategy.

**Always watch for token-intensive tasks that don't need local file access** and
flag them for a browser-based LLM (Claude.ai, ChatGPT, Gemini web).

Good offload candidates: writing implementation plans, drafting design docs,
writing summaries/reports, reviewing specs for gaps, brainstorming approaches.

Must stay local: running tests, editing files, executing commands, anything
needing live repo access.

**When offloading:**
1. Write a self-contained Markdown handoff document with all context the browser
   LLM needs (specs, existing plans, relevant code excerpts, clear instructions
   for what to produce)
2. Tell the user which files/folders/repos to attach when opening the browser
   LLM session
3. Keep the handoff doc concise — the browser LLM doesn't need the full
   conversation history

## Constraints

**NEVER**: use `os.path` | use `print()` for logging | hardcode paths | skip type hints on public APIs | name tests `test_*.py` | modify files outside project root without confirmation | run destructive commands without confirmation

**ALWAYS**: run tests before completion | use `.venv/` | preserve existing code style | ask on ambiguous requirements | bump version on module changes
```

### `scripts/docs/agent-config/GEMINI.md`

Gemini CLI reads `~/.gemini/GEMINI.md`. Keep it consistent with CLAUDE.md above.

```markdown
# Global Defaults — Gemini CLI

Python 3.11+ | uv package manager | Cross-platform (WSL2, Termux, Windows 11)

> Core conventions are in AGENTS.md. This file adds Gemini CLI context.

## Module Standards

Read `MODULE_STANDARDS.md` before changing any module in the scripts repo.
It is the single source of truth for versioning, CLI design, testing, and
cross-platform behavior.

## Code Style

- Type hints: mandatory on public functions/methods
- Docstrings: Google style, imperative first line
- Imports: stdlib | third-party | local (blank-line separated, alphabetized)
- Paths: `pathlib.Path` (never `os.path`)
- Strings: f-strings only
- I/O: explicit `encoding="utf-8"`
- Logging: `logging` module only

## CLI Arguments

ALL flags need both short and long forms: `-a/--argument-name`.

## Testing

- File naming: `tests/<module_name>_test.py`
- Run tests before claiming completion

## Version Management

- MAJOR: breaking API / entry point changes
- MINOR: new backwards-compatible features or dependency changes
- PATCH: bug fix, refactor, docs, tests only

## Token Conservation — Browser LLM Offloading

Hard token limits apply to all local LLM CLIs. Flag token-heavy tasks that
don't need local file access for browser LLM offloading.

Good offload candidates: writing plans, drafting docs, reviewing specs.
Must stay local: running tests, editing files, executing commands.

When offloading: write a self-contained Markdown handoff doc with all needed
context, and tell the user which files to attach in the browser session.

## Cross-Platform

- WSL2 Ubuntu, Windows 11 PowerShell 7, Termux Android
- Use `pathlib.Path` for all paths; never `os.path`
- Termux: `UV_LINK_MODE=copy`, use `pkg install uv`
- WSL2: prefer `/home/` over `/mnt/c/`

## Constraints

**NEVER**: `os.path` | `print()` for logging | hardcode paths | skip type hints | `test_*.py` naming

**ALWAYS**: run tests before completion | `.venv/` | ask on ambiguous requirements | bump version on changes
```

### `scripts/docs/agent-config/copilot-instructions.md`

GitHub Copilot reads `.github/copilot-instructions.md` in each repo. There is no
global path. This file is a TEMPLATE to be copied (not symlinked) into new repos.
The `agents-init` helper (see dotfiles) or a future `setup.py` flag should copy
this when initializing a new project.

```markdown
# GitHub Copilot Instructions

> Project-specific Copilot instructions. Fill in [PROJECT_NAME] and delete inapplicable sections.

## Project

Name: [PROJECT_NAME]
Language: Python 3.11+
Type: [cli-tool | library | web-service]

## Code Style

- Type hints on all public functions
- Google-style docstrings, imperative first line
- `pathlib.Path` for all paths
- f-strings only
- `logging` for output, never `print()`
- `pyproject.toml` for config

## CLI

All arguments need short + long form: `-a/--argument-name`.

## Testing

- `tests/<module>_test.py` naming
- Run tests before marking complete

## Constraints

Never: `os.path`, `print()` for logging, hardcoded paths, skip type hints.
Always: run tests, use `.venv/`, bump version on changes.
```

---

## 5. Implementation Instructions

### 5.1 Create `scripts/docs/agent-config/` with the four files above

Write exactly the content from Section 4 into:
- `scripts/docs/agent-config/AGENTS.md`
- `scripts/docs/agent-config/CLAUDE.md`
- `scripts/docs/agent-config/GEMINI.md`
- `scripts/docs/agent-config/copilot-instructions.md`

### 5.2 Add symlink logic to `scripts/setup.py`

In `setup.py`, find the section near line 1289 that has `"Agent Skill Symlinks"`.
Add a new setup group immediately after it:

```python
# ─────────────────────────────────────────────────────────
# Agent Config Symlinks
# ─────────────────────────────────────────────────────────
with setup_group("Agent Config Symlinks", 3):
    _setup_agent_config_symlinks(SCRIPTS_DIR, verbose=args.verbose)
```

Add this function earlier in `setup.py` (before `main()`):

```python
def _setup_agent_config_symlinks(scripts_dir: Path, verbose: bool = False) -> None:
    """Create global symlinks for agent config files.

    Symlinks scripts/docs/agent-config/ files to the OS-level paths that
    LLM CLIs read on startup. Safe to run repeatedly — skips if already correct.

    Targets:
        ~/.claude/CLAUDE.md   → scripts/docs/agent-config/CLAUDE.md
        ~/.codex/AGENTS.md    → scripts/docs/agent-config/AGENTS.md
        ~/.gemini/GEMINI.md   → scripts/docs/agent-config/GEMINI.md
    """
    config_dir = scripts_dir / "docs" / "agent-config"
    if not config_dir.is_dir():
        log_warning(f"Agent config directory not found: {config_dir} — skipping symlinks")
        return

    home = Path.home()
    targets = [
        (config_dir / "CLAUDE.md",  home / ".claude"  / "CLAUDE.md"),
        (config_dir / "AGENTS.md",  home / ".codex"   / "AGENTS.md"),
        (config_dir / "GEMINI.md",  home / ".gemini"  / "GEMINI.md"),
    ]

    for source, link in targets:
        if not source.is_file():
            log_warning(f"Source missing, skipping: {source}")
            continue

        link.parent.mkdir(parents=True, exist_ok=True)

        if link.is_symlink():
            if link.resolve() == source.resolve():
                if verbose:
                    log_info(f"OK (already linked): {link}")
                continue
            # Wrong target — remove and re-create
            link.unlink()

        if link.exists():
            # Regular file exists — back it up before replacing
            backup = link.with_suffix(".md.bak")
            link.rename(backup)
            log_info(f"Backed up existing file: {link} → {backup}")

        try:
            link.symlink_to(source)
            log_info(f"Linked: {link} → {source}")
        except OSError as exc:
            # Windows without Developer Mode raises PermissionError
            log_warning(
                f"Could not create symlink {link} → {source}: {exc}\n"
                f"  On Windows, enable Developer Mode or run setup as Administrator."
            )
```

**Important:** The `log_info` and `log_warning` functions already exist in
`setup.py`. Do not redefine them.

### 5.3 Update `dotfiles/symlinked/llms/symlinks.sh`

Replace the three lines that create the CLAUDE.md, CODEX AGENTS.md, and GEMINI.md
symlinks with guard comments:

```sh
# CLAUDE.md, CODEX AGENTS.md, and GEMINI.md are now managed by scripts/setup.py.
# Source of truth: scripts/docs/agent-config/
# Run: python ~/scripts/setup.py   (or bootstrap.sh)
# The following lines are intentionally left as comments:
#   create_symlink "$CLAUDE_SOURCE" "$HOME/.claude/CLAUDE.md"
#   create_symlink "$CODEX_SOURCE"  "$HOME/.codex/AGENTS.md"
#   create_symlink "$LLMS_DIR/gemini/GEMINI.md" "$HOME/.gemini/GEMINI.md"
```

Keep the `settings.json` and `config.toml` symlinks — those remain in dotfiles.

### 5.4 Add a comment to `bootstrap.sh` and `bootstrap.ps1`

In `bootstrap.sh`, near the top after the usage block, add:

```sh
# Agent config files (CLAUDE.md, AGENTS.md, GEMINI.md) are managed here:
#   scripts/docs/agent-config/
# setup.py symlinks them to ~/.claude/, ~/.codex/, ~/.gemini/ automatically.
```

In `bootstrap.ps1`, near the top after param block:

```powershell
# Agent config files (CLAUDE.md, AGENTS.md, GEMINI.md) are managed here:
#   scripts/docs/agent-config/
# setup.py symlinks them to ~/.claude/, ~/.codex/, ~/.gemini/ automatically.
```

---

## 6. Platform Notes

| Platform | Symlink behavior | Notes |
|---|---|---|
| WSL2 Ubuntu | `Path.symlink_to()` — works natively | No special handling |
| Termux Android | `Path.symlink_to()` — works natively | Same as Linux |
| Windows 11 | `Path.symlink_to()` — requires Developer Mode | Graceful fallback: warn the user, skip |

The `_setup_agent_config_symlinks` function above handles all three cases. Windows
with Developer Mode enabled works without elevation. Without Developer Mode, the
function logs a warning and continues without aborting the rest of setup.

---

## 7. What to Produce

Write the following files. The human will copy them into the local repository:

1. **`scripts/docs/agent-config/AGENTS.md`** — from Section 4
2. **`scripts/docs/agent-config/CLAUDE.md`** — from Section 4
3. **`scripts/docs/agent-config/GEMINI.md`** — from Section 4
4. **`scripts/docs/agent-config/copilot-instructions.md`** — from Section 4
5. **`scripts/setup.py` diff** — add `_setup_agent_config_symlinks()` function and
   the `"Agent Config Symlinks"` setup group call (Section 5.2). Show as a unified
   diff or clearly marked before/after blocks so the human can apply it.
6. **`dotfiles/symlinked/llms/symlinks.sh` diff** — guard comment replacement
   (Section 5.3)
7. **`scripts/bootstrap.sh` patch** — add the agent-config comment (Section 5.4)
8. **`scripts/bootstrap.ps1` patch** — add the agent-config comment (Section 5.4)

You do NOT need to run tests or execute any commands. The human will apply and
test the changes locally.

---

## 8. Success Criteria

After `python ~/scripts/setup.py` runs on a fresh machine:

- `~/.claude/CLAUDE.md` resolves to `scripts/docs/agent-config/CLAUDE.md`
- `~/.codex/AGENTS.md` resolves to `scripts/docs/agent-config/AGENTS.md`
- `~/.gemini/GEMINI.md` resolves to `scripts/docs/agent-config/GEMINI.md`
- Re-running setup is idempotent (no errors, no duplicate symlinks)
- On Windows without Developer Mode: setup completes with a warning, not an error
