# Implementation Plan: Improve ag Command Information

## Goal

Make ag a useful, readable command directory. Its default view will show registered project tools and user-configured shell shortcuts. --all will include the broader shell inventory and PATH executables. Descriptions will be human-readable, with an optional raw-definition column and terminal-aware colors.

## Approved decisions

- Keep one ag command; use -A/--all for the broad inventory.
- Keep -x/--executables as an additive PATH-executable option with its existing behavior.
- Default rows are registered tools plus shortcuts from user profiles/configuration.
- Default search matches names and help descriptions. -D/--definitions also matches and displays raw definitions.
- Use Name and Help as the default columns; -D adds Definition.
- Color output only for an interactive terminal, unless NO_COLOR is set. JSON and redirected output contain no ANSI codes.
- Preserve the existing JSON output schema and ag entry point.
- Treat this user-facing behavior change as a major version update per repository standards.

## Constraints

- Do not execute discovered commands to generate help at search time.
- Do not add an fg alias; it conflicts with common shell job-control terminology.
- Keep shell-inventory classification internal to the adapter payload; avoid changing the public CommandEntry JSON schema unless implementation proves that necessary.
- Preserve unrelated changes in the primary checkout; all edits remain in the ag-info worktree.

## Task 1: Add curated metadata and useful descriptions

Files:
- modules/scripts_help/scripts_help/command_registry.py
- modules/scripts_help/scripts_help/shell_integration.py
- modules/scripts_help/tests/registry_ag_test.py
- modules/clipboard_tools/pyproject.toml

Steps:
1. Add a regression test showing that a Python console script without a per-command registry description inherits the project summary from its pyproject.toml.
2. Add tests for shell inventory filtering: configured/user-owned shortcuts are included in curated mode; system/module commands are omitted; broad mode retains both.
3. Update console-script metadata loading to use the project description as a fallback while preserving explicit per-command descriptions.
4. Mark shell adapter records as curated when their alias/function comes from user profile or user-owned configuration; retain system/module records for --all.
5. Keep classification metadata out of the public CommandEntry serialization.

Checks:
- Run the focused tests and verify a custom command such as c2c receives concise help rather than its Python entry-point target.
- Verify synthetic user and system inventory records produce the expected curated/all results on every platform.

## Task 2: Implement curated and full search/table modes

Files:
- modules/scripts_help/scripts_help/ag.py
- modules/scripts_help/scripts_help/shell_integration.py
- modules/scripts_help/tests/registry_ag_test.py

Steps:
1. Add -A/--all and -D/--definitions; preserve -x/--executables and explain how the inventory flags combine in CLI help.
2. Make curated mode the default for shell inventory while continuing to include registry entries.
3. Search names and descriptions by default; include raw target/definition matching only with -D.
4. Render Name and Help by default, and add Definition as the third column with -D.
5. Bound displayed column widths to the terminal width and truncate long values with a readable ellipsis.
6. Apply stable colors by entry kind/source only when output is a terminal and NO_COLOR is absent. Keep JSON and piped output free of ANSI codes.

Checks:
- Add focused tests for defaults, --all, --executables, --definitions, text matching, JSON schema compatibility, width/truncation, and color gating.
- Use captured output with TTY/non-TTY streams and NO_COLOR set/unset to verify ANSI behavior.

## Task 3: Update documentation and version metadata

Files:
- modules/scripts_help/README.md
- modules/scripts_help/pyproject.toml
- modules/scripts_help/docs/superpowers/specs/2026-11-27-ag-info-design.md
- This plan

Steps:
1. Update CLI usage and examples for curated default, --all, --executables, and --definitions.
2. Bump the package and README versions to 2.0.0. There is no scripts_help self-entry in the registry file, so no registry version is applicable.
3. Ensure the design document and this plan reflect any implementation-level adjustments.

Checks:
- Run the complete scripts_help module test suite.
- Run git diff --check and inspect the final changed-file list and diff.
- Confirm generated text and JSON remain backward-compatible where specified.

## Execution order

Implement Task 1 and its tests first, then Task 2 and its tests, then Task 3. Run focused checks after each task and the full module suite at the end. Stage only the files listed above that actually change. Do not merge the branch into main without a separate explicit request.

## Outcome

- [x] Curated defaults, full inventory mode, readable help, optional definitions, terminal colors, and width clipping implemented.
- [x] README/package version updated to 2.0.0; clipboard entry points now have per-command summaries.
- [x] Focused tests: 9 passed.
- [x] Full module suite: 65 passed, 1 skipped because the W11-PowerShell checkout is not present beside this isolated worktree.
- [x] Generated PowerShell adapter parsed successfully; generated Bash adapter passed bash -n.
- [x] CRLF-aware git diff check passed.
- Remaining: review/merge/push is not included in this implementation plan.
