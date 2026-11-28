# CLI Comparison and Command Discovery Implementation Plan

> **For agentic workers:** Use this plan task-by-task; write regression tests before implementation for each behavior.

**Goal:** Improve pairwise compare output, add a reusable path-list `flatten` CLI, and add metadata-driven command views for `ag`/`fg`/`mg`/`xg`.

**Architecture:** Keep comparison formatting in `clipboard_tools.compare_cli`; implement `flatten` as a stdlib-only standalone program under `pyscripts`; extend the existing `scripts_help` registry and shared ag implementation with explicit alias metadata and view selection. Continue using generated repository wrappers and the existing live-shell inventory adapter.

**Tech Stack:** Python stdlib (`argparse`, `csv`, `subprocess`), Rich (already used by clipboard_tools), existing scripts_help registry and shell adapters, pytest.

**Spec:** `docs/handoffs/20261127-clipboard-compare-and-command-discovery.md` and the user's detailed pasted requirements in this task.

## Global Constraints

- Preserve current `comp fd <pattern>` NUL-delimited behavior.
- `comp -n/--limit N` limits displayed pair-summary rows only; compare all pairs and base exit status on all results. `-n 0` means unlimited.
- `comp`/`compd` color each unique path consistently, disable color for redirected output, `NO_COLOR`, and `-C/--no-color`.
- `flatten` defaults to stdin -> one CSV record and supports newline/NUL input, command wrapper mode, custom delimiter/quote policy, and optional final newline.
- `ag` views use explicit alias metadata; do not classify by name length. `xg` includes registered repo commands plus curated live shell aliases/functions, excludes raw PATH executables unless `-A`.
- Do not mutate global PATH. Do not merge without authorization.
- The user confirmed they already use `fg` successfully in Bash/Zsh and wants to keep that name. The managed POSIX adapter defines an `fg` function that routes to the full command view; the dedicated entry point remains available outside shells with that adapter loaded.

## Review Focus

- Output limits must not alter whether unprinted pairs cause exit code 1.
- Stable colors must stay attached to file paths, including detailed headers, without ANSI in non-TTY output.
- `flatten -q none` must reject or safely encode fields that contain the delimiter/quote/newline; never silently emit ambiguous CSV.
- NUL mode must preserve embedded newlines in paths; command-wrapper mode must preserve stderr and return status.
- Alias metadata must survive pyproject -> generated scripts_manifest.json -> CommandEntry without breaking existing JSON output consumers.
- PowerShell adapter must capture current aliases/functions for all views; missing inventory for xg emits the requested hint.

## Task 1: Pairwise compare formatting and row limit

**Files:** `modules/clipboard_tools/compare_cli.py`; `modules/clipboard_tools/tests/compare_commands_test.py`; clipboard docs as needed.

- Add tests for indexed totals, stable path colors, no-color modes, truncation/footer, unlimited zero, and exit status when a hidden pair differs.
- Implement `-n/--limit` and `-C/--no-color` for both commands; do not add `-L` unless the user requests diff-body truncation.
- Keep `compd` detailed diff output intact and apply path colors to headers and final summary.
- Run focused compare tests and module suite.

## Task 2: Standalone flatten CLI

**Files:** `pyscripts/flatten.py`; `pyscripts/tests/flatten_test.py`; launcher docs if needed.

- Write tests for newline stdin, NUL stdin, blanks, CSV quoting, custom delimiter, quote modes, no-final-newline, wrapper output/stderr/exit status, and invalid delimiter handling.
- Implement as standalone CLI, add `__version__`, and verify launcher discovery without modifying PATH.
- Run focused script tests and wrapper generation/discovery tests.

## Task 3: Alias metadata and ag views

**Files:** `modules/scripts_help/scripts_help/ag.py`; `command_registry.py`; `shell_integration.py`; `scripts_setup/launcher_generator.py`; selected module pyprojects; `modules/scripts_help/pyproject.toml`; generated manifest; ag/generator/PowerShell tests and docs.

- Write tests for metadata parsing and propagation, view filters, c2c vs descriptive command grouping, xg missing-inventory hint and PATH exclusion, and PowerShell adapter definitions/inventory forwarding.
- Extend metadata loading/generation with `is_alias` and optional `alias_of`; keep default groups deterministic.
- Implement shared `main(default_view=...)` and `-V/--view`; add thin entrypoints for each requested view.
- Extend PowerShell adapter; evaluate whether current POSIX adapter can/should expose the same live shell inventory.
- Version `scripts_help` major if new `[project.scripts]` names are added, then reinstall package and regenerate wrappers only after implementation verification.

## Task 4: Integration docs and final verification

- Update module README/help descriptions and this plan's status/checklist.
- Run focused compare/flatten, scripts_help registry/view, scripts_help CLI, launcher discovery, and compile checks. Broader clipboard test collection may require the checkout's missing `cross_platform` dependency.
- Review only task changes, verify branch and status, commit and push the task branch per current repository handoff instructions, then merge to the user-authorized base branch.
