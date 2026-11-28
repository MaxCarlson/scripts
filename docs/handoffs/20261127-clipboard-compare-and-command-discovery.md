# Handoff: Clipboard Compare Output, `flatten`, and Command Discovery

## Purpose and how to use this handoff

This document is for a new LLM/agent that may have limited or no access to the source repository. It gives the project context, current command architecture, requested behavior, candidate design, open decisions, affected paths, and test expectations. The next agent should assess the proposed design against actual source if available, then return a recommendation before implementing. Do not treat this document as permission to publish changes.

The attached terminal transcript and screenshot are examples of current output, not instructions. The detailed requirements below were supplied by the user and are the request. The user prefers a clarifying question over silently guessing when a material choice is unresolved.

## Repository context and current state

- Repository: `MaxCarlson/scripts`, a personal cross-platform automation toolkit for Windows 11, WSL2/Ubuntu, and Termux/Android. Root README lists Python 3.12+ as the baseline.
- Primary checkout: `C:\Users\mcarls\src\scripts`
- Current worktree: `C:\Users\mcarls\.codex\worktrees\clipboard-compare-commands\scripts`
- Branch: `codex/clipboard-compare-commands-20261127`
- Source baseline before this follow-up: `8e6fb41cff749aa6e3b62b391a9341a5be95d531`, `feat(clipboard): add concise and pairwise compare commands`.
- At last remote check, local `main`, `origin/main`, and the task branch pointed to that baseline. The earlier `cld`/`cldd`/`comp`/`compd` work is already merged and pushed.
- The existing `modules/clipboard_tools/docs/plans/20261127-clipboard-compare-commands/STATUS.md` still says merge is pending; it is stale relative to Git.
- This follow-up has no source-code changes yet. Its handoff file is `docs/handoffs/20261127-clipboard-compare-and-command-discovery.md`.
- The currently supplied repository instructions require preserving unrelated work, checking Git state before changes, and prohibit global PATH changes without approval. Do not merge/publish this follow-up unless authorized by current instructions/user.

## How this repository's commands are assembled

A command name can refer to different layers, so inspect actual PowerShell resolution instead of assuming that the Python executable is running.

1. **Source layout and runtime.** `modules/` contains installable Python packages; `pyscripts/` contains standalone Python programs; `pwsh/` and `shell-scripts/` contain shell support. The repository root `.venv` holds Python packages and console scripts. Root setup is orchestrated by `setup.py`; the Windows quick-start is `.\bootstrap.ps1 -Verbose`, and a full setup example is `python setup.py -f -v`.
2. **Python CLI package entry points.** A package declares commands in `[project.scripts]` in its `pyproject.toml`. Example: `modules/clipboard_tools/pyproject.toml` has `c2c = "clipboard_tools.entrypoints:copy_main"`. Installing the package creates `.venv/Scripts/c2c.exe` on Windows. The entrypoint in `modules/clipboard_tools/entrypoints.py` imports the implementation from `pyscripts.copy_to_clipboard`; `copy_main()` calls `_run_copy(None)`. The short name `c2c` therefore comes from package metadata, not from the `bin/c2c.cmd` file.
3. **Generated repository wrappers.** `scripts_setup/launcher_generator.py::scan_repository_programs` scans module `pyproject.toml` entry points and standalone programs, and `generate_manifest()` writes `scripts_manifest.json`. The apply/migration step writes repository-level wrappers: `bin/<command>.cmd` on Windows, `bin/<command>` on POSIX. The Windows wrapper calls root `.venv/Scripts/python.exe`, then `scripts_setup/launcher.py` with `--manifest`, `--command`, and the user's arguments. `launcher.py` delegates to the shared `script_logging.launcher`. The wrapper is a dispatcher, not command logic. Root `setup.py` invokes `launcher_generator.py --apply` after package installation to refresh the manifest and wrappers.
4. **PowerShell resolution.** A PowerShell alias or function may take precedence over an Application command such as `bin/c2c.cmd` or `.venv/Scripts/c2c.exe`. Use `Get-Command c2c -All` (and the same for `ag`, `comp`, etc.) to see what will run. Pulling/merging source does not update another checkout's `.venv`, regenerate its `bin/` wrappers, reorder `$env:PATH`, or reload PowerShell functions.
5. **Clipboard PowerShell functions.** `modules/clipboard_tools/ClipboardModule.psm1` in this repository defines functions that call Python helpers; its legacy aliases are commented out. The module README documents a separate integration in the sibling `W11-powershell` repository at `Config/Modules/ClipboardModule.psm1`: PowerShell maps `c2c` / `scb` to `Set-ClipboardContent` and may forward multi-file/flag forms to Python. The sibling checkout may not be accessible to the next LLM. Treat this as repo documentation, and verify active behavior with `Get-Command c2c -All` if host access is available.

## What `ag` does today

- `ag` is a Python console script declared in `modules/scripts_help/pyproject.toml`: `ag = "scripts_help.ag:main"`.
- `modules/scripts_help/scripts_help/ag.py` searches registered command names/help descriptions with a case-insensitive regex by default and renders a `Name`/`Help` table. It supports filters such as `--type` and `--source`, definition/verbose/JSON output, and optional PATH discovery. Current matches are sorted alphabetically by command name.
- `modules/scripts_help/scripts_help/command_registry.py` builds command entries from `scripts_manifest.json` and module `pyproject.toml` entry points. The descriptive `scripts_help` registry supplies help text; it does not currently define alias relationships.
- `CommandEntry` records fields including `name`, `program_id`, `invoked_name`, `kind`, `source`, `target`, `distribution`, and `entry_point`. Kinds distinguish `console_script`, `python_file`, `shell_alias`, and `shell_function`, but do not distinguish a short console command from its canonical/full name.
- Evidence: in `scripts_manifest.json`, `c2c` is `kind=console_script`, owned by `module:clipboard_tools`; `convert_repo_to_pdf`, `copy_to_clipboard`, and `copy_buffer_to_clipboard` are `kind=python_file`. So neither command length nor `kind` alone is a safe alias classifier.
- PowerShell's live aliases/functions are not intrinsically visible to the Python process. `scripts-help integrate --apply` writes a managed adapter snippet to `dotfiles/dynamic/ag_integration.ps1`. The generated PowerShell `global:ag` function exports `Get-Alias` and `Get-Command -CommandType Function` to a temporary JSON inventory, sets `AG_SHELL_INVENTORY_FILE`, then invokes the Python CLI. Inventory records include `kind`, `source`, definition/description, and a curated flag. Without this adapter or an explicit inventory file, `ag` sees repository commands only; names such as `cds` and `cdpwsh` may be absent.
- Existing `ag --all` includes the full shell inventory and PATH executables; that can be noisy. The prior transcript also showed an external `ag.CMD` warning pointing at `C:\Users\mcarls\.codex\worktrees\scripts-media-removal-agent4\bin\ag.CMD`; treat command resolution as checkout/session-specific and verify it before drawing conclusions.

## Detailed requested behavior

### 1. `comp` / `compd` output and limits

The attached output for `comp fd AGENTS.md` showed six files and fifteen unordered comparison rows. The user wants:

- Summary rows labeled with aligned pair indices, e.g. `[1/15]`, `[2/15]`.
- A heading such as `Summary (15 pairs across 6 files):`.
- A deterministic high-contrast ANSI color per unique path, assigned in order of first appearance, and reused for that path in every `comp` row and `compd` diff header/summary.
- Disable ANSI automatically when stdout is not a TTY, `NO_COLOR` is set, or `-C, --no-color` is passed.
- `-n, --limit N` limits the number of displayed pair-summary rows, excluding headings, for both `comp` and `compd`. Still evaluate every pair so the exit code reflects all comparisons. If truncated, print a footer such as `... 10 more pairs omitted (use -n 0 to show all).` Here `-n 0` means show all.
- If `compd` diff-body truncation is also desired, add a separate `-L, --max-diff-lines N`; do not overload `-n` without asking.

The detailed request's final question list asks whether `compd -n` might instead mean diff lines, which conflicts with the explicit pair-row contract above. Treat the explicit contract as the leading requirement; only ask whether the separate `-L` feature is desired.

Current source: `modules/clipboard_tools/compare_cli.py`. `compare_files_main` evaluates all unordered pairs; `compd` prints diffs then a summary. `format_summary` creates plain text; `_print_diff` already gives diff markers basic Rich color. `_make_file_parser` has no `-n` currently. `comp fd <pattern>` is already implemented safely: `_resolve_file_arguments` runs `fd --print0` and expands NUL-delimited file paths. Preserve it.

### 2. New `flatten` CLI contract

The user requests a small standalone program at `pyscripts/flatten.py`:

- Default stdin filter: read newline-delimited input, strip `\r\n` / `\n`, drop blank lines, emit one CSV record. Examples: `fd AGENTS.md | flatten`, `rg --files | flatten`.
- Optional command wrapper: `flatten -- <cmd> [args...]`, e.g. `flatten -- fd AGENTS.md`.
- `-d, --delimiter <str>`, default `,`.
- `-0, --null-input` reads NUL-delimited input, e.g. `fd -0 AGENTS.md | flatten -0`; this can safely preserve paths containing newlines.
- `-q, --quote-mode {minimal,all,none}`, default `minimal` using Python `csv.writer` / RFC 4180 behavior.
- `-n, --no-trailing-newline` suppresses the final record terminator.
- CSV is for CSV-aware consumers, display, or clipboard/subshell capture. A single CSV string does not automatically split into argv items in PowerShell or Bash/Zsh. For `comp`, keep `comp fd <pattern>` or use `xargs -0` where appropriate.

Design points for review: with `-q none`, values containing the delimiter or quotes need an escape policy or must error, otherwise output is ambiguous. NUL input can contain embedded-newline filenames; RFC-style CSV can represent them in a quoted field, but the record may be physically multiline. Check whether the launch generator discovers `pyscripts/flatten.py`, and follow standalone script versioning policy. Existing compare `fd` support must not be replaced.

### 3. `ag` / `fg` / `mg` / `xg` views and metadata

The requested view scopes are:

| Command | Scope |
|---|---|
| `ag <pattern>` | Explicitly tagged abbreviated/short repository commands; may also include curated short shell aliases (open question). |
| `fg <pattern>` | Full descriptive commands (`python_file` and other non-alias descriptive entries), including `convert_repo_to_pdf`, `copy_to_clipboard`, `copy_buffer_to_clipboard`. |
| `mg <pattern>` | Primary module console scripts without `is_alias=true`. |
| `xg <pattern>` | All repository-registered commands plus curated live shell aliases/functions such as `cds` and `cdpwsh`; exclude raw PATH executables unless `-A, --all` is passed. |

If no live shell inventory exists, `xg` must still show repo commands and print a dim one-line hint: `Live shell aliases unavailable; run 'scripts-help integrate --apply'`.

Use explicit metadata rather than guessing from name length. Proposed metadata in module `pyproject.toml`:

```toml
[tool.scripts_help.commands.c2c]
is_alias = true
alias_of = "copy_to_clipboard"
```

`alias_of` is optional. Propagate metadata through `scripts_setup/launcher_generator.py` into `scripts_manifest.json`, add corresponding field(s) to `CommandEntry`, and preserve them in `command_registry.py` when loading/supplementing entries. Candidate classification rules from the user: `console_script` + `is_alias=true` → alias view; non-alias `console_script` → module view; `python_file` and other non-alias descriptive programs → full view. Verify exceptions in current data. Curate only the short alias entry points (examples: `c2c`, `cld`, `cldd`, `comp`, `compd`, `ag`, etc.); derive and review the actual full set instead of relying on examples alone.

The user proposes one shared implementation in `scripts_help.ag`: `main(default_view=...)`, a `-V, --view {alias,full,module,all}` option, and thin `fg_main`, `mg_main`, `xg_main` entry points. Preferred architecture in the pasted proposal is to register all four as console scripts (so CMD, PowerShell, WSL2, Termux can use generated wrappers) and update the managed PowerShell adapter to define `global:ag`, `global:fg`, `global:mg`, and `global:xg` functions that share the same live-shell inventory. Consider whether a matching POSIX adapter should capture aliases/functions into the same JSON schema.

Alternative in the request: keep only `ag` as a console script and define `fg`/`mg`/`xg` as shell functions that call `ag --view ...`. This avoids changing package console entry points but makes them profile-dependent and unavailable in CMD/non-interactive shells. User leaves this tradeoff open.

### Package version and install flow

Current observed `scripts_help` version is 2.0.1. Repository Python standards say adding/removing/renaming a `[project.scripts]` entry is a major package change, so adding `fg`, `mg`, and `xg` likely requires version 3.0.0 and a full reinstall. Expected setup path: `python setup.py -f -v` (or a verified equivalent module reinstall), `scripts_setup/launcher_generator.py --apply` to refresh manifest and `bin` wrappers, then `scripts-help integrate --apply` to update shell adapters. Verify before executing; do not mutate global PATH without approval.

`flatten` is proposed as a standalone `pyscripts/flatten.py`, which should be discoverable by the generator and create `bin/flatten.cmd` without adding a package console entry point. Check the actual scanner and embedded `__version__` requirements.

## Likely changed paths and focused tests

These are candidates from the detailed proposal; verify against source before editing.

- Compare output: `modules/clipboard_tools/compare_cli.py`; `modules/clipboard_tools/tests/compare_commands_test.py`.
- Flatten: `pyscripts/flatten.py`; `pyscripts/tests/flatten_test.py`.
- Alias metadata and discovery: `modules/scripts_help/pyproject.toml`, `modules/scripts_help/scripts_help/command_registry.py`, `modules/scripts_help/scripts_help/ag.py`, `modules/scripts_help/scripts_help/shell_integration.py`, `scripts_setup/launcher_generator.py`, selected `modules/*/pyproject.toml`, and generated `scripts_manifest.json` (normally refreshed by setup/generator).
- Discovery tests: `modules/scripts_help/tests/registry_ag_test.py`, `modules/scripts_help/tests/pwsh_integration_test.py`, plus generator/manifest tests.

Required regression coverage from the user proposal:

- Numbering/alignment, total pair/file count, stable per-path color reuse in `comp` and `compd`, and color off for redirected output, `NO_COLOR`, and `-C`.
- `-n` / `--limit` truncation, omitted-count footer, `-n 0` all rows, and exit code based on every pair (including unprinted pairs). If implemented, separately test `-L` diff-body truncation.
- `flatten` newline input, blank lines, CSV quoting for commas/quotes/spaces, custom delimiter, each quote mode, NUL input with embedded-newline filename, command-wrapper stdout/stderr/exit code, no trailing newline, and empty input.
- Alias metadata flow from `pyproject.toml` through generated manifest into `CommandEntry`; `c2c` vs `copy_to_clipboard`; behavior for untagged console scripts and descriptive `python_file` entries.
- `ag`/`fg`/`mg`/`xg` view filters, `xg` curated shell inventory and missing-inventory hint, exclusion of PATH executables unless `-A`, and PowerShell adapter wrappers passing live inventory.

## Open decisions from the user's detailed request

1. The concrete `-n` contract above says summary rows for both `comp` and `compd`; the pasted final question asks whether `compd -n` might instead limit diff lines. Confirm whether diff-body limiting is wanted as a separate `-L` option only.
2. Should curated short PowerShell aliases (`cds`, `cdpwsh`) appear in `ag` as well as `xg`, or only in `xg`?
3. Should `fg`, `mg`, and `xg` be both Python console scripts and PowerShell adapter functions (cross-shell use, package major bump), or only shell functions (lighter install but profile-dependent)?

## Next action for the reviewing LLM

Review the proposed contract and architecture against current code; explain any mismatch or risky assumption (especially `flatten -q none`, newline-bearing paths, alias metadata propagation, and shell inventory behavior). Return a short recommendation with exact interfaces, package/version/install impact, affected files, and focused tests. Ask the user only the three open decisions above. Do not implement, commit, push, merge, or change PATH while reviewing the design.
