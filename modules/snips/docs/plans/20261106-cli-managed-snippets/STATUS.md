# CLI-managed snippets plan status

## Objective

Build a Python CLI for versioned snippet/action configuration, with AutoHotkey v2 as the Windows hotkey runtime and safe multiline insertion, clipboard fencing, selection fencing, per-user startup, and import/export.

## Architecture decision

Use a small `snips` Python module with no runtime Python dependency and AutoHotkey v2 as the per-user background runtime. Keep the canonical schema-versioned JSON separate from generated runtime files. Python writes snippet bodies to separate UTF-8 text files and generates a minimal `.ahk` dispatcher containing only validated IDs, hotkeys, and paths; user text never becomes AHK source. Clipboard actions temporarily replace clipboard text for paste and restore `ClipboardAll()` afterward. Runtime status is checked by the unique per-user process/window title and the AHK status file.

Investigated FlitKey, Lintalist, and Espanso. FlitKey documents per-snippet hotkeys, cursor placeholders, and clipboard support, but its documented management path is a PyQt desktop app/import flow rather than a reusable CLI API. Lintalist has hotkeys, editable multiline snippets, and caret plugins, but the current project is AutoHotkey v1 based. Espanso has a CLI and file configuration, but its current docs describe typed triggers and say keyboard-shortcut matches are not currently supported. A custom CLI over AutoHotkey v2 is the smallest path that directly satisfies the required global hotkeys and control surface without PyQt or another long-running Python process.

## Stages

1. Implement schema, hotkey parser, generated AHK runtime, configuration transaction/rollback, and unit tests.
2. Implement CLI subcommands, installer detection/setup, startup registration, help registry, and docs.
3. Run focused tests, validate generated AHK with the installed v2 runtime, install/start the managed runtime if it validates, and perform UI validation where available.
4. Review task-only diff, commit on the task branch, and report any validation limits.

## Current state

- Worktree: `.worktrees/cli-managed-snippets`
- Branch: `codex/cli-managed-snippets-20261106`
- Base: `58dbc4775fbc1bd429db489d386311ee0795befc`
- Feature commit: `91b2dd30` (`feat(snips): add CLI-managed Windows snippets`), pushed to `origin/codex/cli-managed-snippets-20261106`.
- Implemented the schema, atomic config/runtime deployment with rollback, CLI, AutoHotkey backend discovery/install, HKCU Run startup, help registry entry, tests, and user documentation.
- Follow-up packaging fix: CLI version now comes from a sibling module, so it loads even when the installed editable import resolves `snips` as a namespace package. The module version is `0.1.1`; a regression test reproduces the reported `unknown location` import error and verifies the fix.
- The backend reuses an existing AutoHotkey v2, checks Scoop install roots, and installs in WinGet → Scoop Extras → official installer order. The official fallback selects the numerically newest stable v2 setup and uses its `/silent` switch.
- On 2026-11-06, AutoHotkey v2.0.30.0 was detected at `C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe`. `snips install --apply --json` refreshed the runtime at `C:\Users\mcarls\AppData\Local\snips\runtime`, confirmed the existing startup value without replacing it, and started PID 132292. Subsequent `status` and `doctor` reported the process running, schema-1 config valid with two bindings, and startup configured.
- Focused suite: `python -m pytest -q -o "addopts=-ra" --basetemp=.pytest_tmp_root/namespace-fix-final` → 26 passed, including namespace import regression and generated AHK parse/registration in validation mode. `ruff check` and `ruff format --check --line-length 120` pass. `compileall` and CLI help pass. The installed `snips --version`, `snips list`, and `snips status` commands work.
- Interactive Notepad/browser/editor tests and clipboard/caret interaction checks were not performed because the user prohibited further computer UI interaction after an earlier AutoHotkey popup. No GUI validation is claimed.

## Handoff

Implementation, validation, feature commit, task-branch push, local merge into `main`, and the namespace-package import fix are complete. The `main` merge and follow-up fix remain local and were not pushed. Keep the feature worktree available for review.
