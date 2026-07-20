# Stage 04: History Search, Replay, and Summary

Status: implementation in progress; user validation pending

## User-visible result

History becomes a first-class command launcher rather than a diagnostic dump.
The newest history entry has ID `0`, the next-newest has ID `1`, and so on.
These are global recency IDs from the complete history: filtering, frequency
views, interactive browsing, and fzf must display the original global ID and
must never renumber the filtered result set from zero.

Examples:

```powershell
runmux history
runmux history --starts-with ytaedl
runmux history --contains archive
runmux history --most-common
runmux history --most-common 25 --starts-with ytaedl
runmux history --interactive
runmux history --fzf
runmux run --history --id 1
runmux run --history --id 1 --path
```

## History identity and ordering

- Build the displayed history ID from the entry's position in the complete,
  newest-first history, so the latest run is always `0`.
- Preserve that global ID after prefix/contains filters, limits, frequency
  grouping, interactive selection, and fzf selection.
- Treat separate executions as separate history entries even when their command
  lines match, because time, working directory, status, and runtime can differ.
- In a most-common grouped view, show the most recent matching occurrence's
  global replay ID plus the total occurrence count.
- Retain the managed run UUID in storage as the durable internal identity.
- Route runs created with isolated/test `--state-dir` registries to isolated
  history storage so tests and smoke probes never enter normal user history.
- Record normal history only for `runmux run` launch paths, including saved and
  history replay variants; do not append restart/duplicate clones.
- Hide known legacy internal probes (`python -V`, `runmux-ok`, history smoke,
  and pytest temp-root runs) before assigning visible global IDs.
- Keep interactive views newest-first, with the newest real user command
  selected and visible immediately. Print normal text history oldest-to-newest
  so the final visible command is the most recent one (global ID `0`).

## Replay from history

- Add `-H/--history` and `-i/--id ID` to `runmux run` so
  `runmux run -H -i 1` launches the exact argv stored for global history ID 1.
- Preserve normal `run` behavior such as detach, view, interact, name, terminal
  dimensions, color handling, and save-command behavior during replay.
- Add `-P/--path` for history replay. When present, validate the stored working
  directory and launch only after selecting that directory as the child cwd.
- Add `-V/--verify` to history replay. Show the exact command, effective path,
  and instance count, then require `y` to proceed or allow `n` to cancel.
- Without `--path`, use explicit `-c/--cwd` when supplied, otherwise use the
  caller's current directory.
- Reject missing IDs, invalid IDs, `--path` without `--history`, conflicting
  cwd choices, missing original directories, and history replay combined with
  an unrelated positional program.
- Expose a general `run` path argument (`-c/--cwd` plus a discoverable
  `-p/--run-path` alias) so any new command can be launched from an explicit
  directory independently of the caller's current directory.

## Search, frequency, and limits

- Add `-b/--starts-with TEXT` for case-insensitive command-prefix matching.
- Add `-c/--contains TEXT` for case-insensitive substring matching.
- Allow prefix and contains filters to be combined in one invocation; an entry
  must satisfy both when both are supplied.
- Add `-m/--most-common [COUNT]`. With no count, show 10 commands; accept a
  positive integer to override the count.
- Apply prefix/contains matching before frequency grouping so most-common views
  can describe all commands or only matching commands.
- Keep `-l/--limit` for newest-entry views and define validation when it is
  combined with `--most-common`.
- Preserve structured `-j/--json` output, including global history ID,
  occurrence count where applicable, argv, cwd, timing, and status metadata.

## Default and optional output

- Default text output shows only the global history ID and command line, one
  command per row. Use a visibly distinct red `(ID).` marker. Print rows
  oldest-to-newest while retaining newest-first global IDs.
- Add `-d/--date` to include the run date/time.
- Add `-P/--path` to include the recorded working directory.
- Add `-S/--status` to include lifecycle status and exit code.
- Add `-r/--runtime` to include elapsed runtime.
- Retain `-p/--plain` to disable color.
- Keep IDs visually distinct and commands directly copyable.
- Fully left-align history IDs with no leading field padding.
- Render the recorded path on a new, fully left-aligned line below its command;
  omit a `path=` label and use a distinct path color.
- Render status/exit code on another line, with runtime adjacent when enabled.
- Render date/time on its own information line in both normal and interactive
  views. Color status, date/time, and
  runtime according to the entry lifecycle status; keep the ID color distinct.
- Record exit code and runtime at supervisor completion so new history entries
  can populate these optional fields.

## Interactive history browser

- Display multiple history rows with a movable selection, preserving global
  IDs beside every command.
- Keep the available hotkeys visible in a wrapped bottom console bar; narrow
  terminals must show every hotkey rather than clipping the bar.
- Required hotkeys: Up/Down or `j`/`k` to move, `r` to run, `s` to save the
  selected command, Enter to print/copy the command, and `q`/Esc to exit.
- Show a short result/error message after save attempts without leaving the
  browser.
- Run the selected entry with its recorded argv and original cwd after safely
  restoring cursor visibility and terminal input mode.
- Add incremental prefix and contains search controls without assigning local
  IDs to the narrowed result set.
- Allow prefix and contains filters to coexist, be replaced, or be cleared from
  inside the browser even when an initial filter came from CLI arguments.
- Add a detail-mode hotkey that cycles path, status/date/runtime, all metadata,
  and compact command-only rows.
- Add a full-content hotkey that toggles clipped single-line rows versus wrapped
  full commands, full paths, and metadata.
- Enter opens a dedicated, fully colored inspector for the selected entry. It
  must show the complete stored command, argv, path, timing, status, IDs, and
  other known metadata; `r` opens its run dialog and Esc/q returns to the
  multi-command browser. Add `p` to leave the browser and print the complete
  colorized command record for copying or review.
- Support arrows and `j`/`k` for single-entry navigation and Page Up/Page Down
  for page-sized movement in all selectable runmux interactive views.
- Preserve a saved command's argv, cwd, friendly name, terminal dimensions,
  and forced-color mode. A saved-command replay uses those values unless an
  explicit `run` option overrides them.
- Replace the prompt-only `cmd` viewer with `load` (keeping `cmd` as a
  compatibility alias). `load` must provide normal, filtered, JSON, fzf, and
  interactive saved-command browsing with the same inspect/print/run controls
  as history; saved IDs stay stable and are usable with `runmux run load -i ID`.
- Make `ls` active/paused-only by default, with `--all` for active-first plus
  terminal records and repeatable status filters. Provide optional cwd/date/
  exit-code detail rows and an interactive action browser for viewing,
  interacting, duplicating, pausing/resuming, killing, and restarting runs.
- Add persistent module-local configuration, initially with
  `terminal_record_limit=500`, and prune older terminal records automatically
  so bulk `remove-finished` is unnecessary.
- Standardize `-A/--all-details` as cosmetic-only: it enables every display
  field for history, saved-command load, and run-list output without changing
  filtering, retention, selection, or execution behavior.
- On `r`, open a run dialog before launching. Prompt for instance count
  (default 1), then launch location (default original recorded cwd, current cwd,
  or a manually entered path). Pressing Enter through both defaults launches
  one instance from the original cwd.
- For multiple instances, create every requested managed run before attaching
  to the final instance so one interactive attachment cannot block the rest.

## fzf mode

- Add `-f/--fzf` and detect `fzf` with an actionable error when unavailable.
- Feed fzf rows containing global history ID and command text, after applying
  any CLI prefix/contains/common filters.
- Preserve the selected global history ID when mapping the fzf result back to
  its history entry.
- Support Enter to print the command, `r` to run it, and `s` to save it when
  fzf's expected-key support is available; Esc/q exits without action.

## Storage and migration

- Add locked `history.jsonl`, `saved_commands.json`, and configuration storage.
- Migrate `commands.json` idempotently with a preserved backup.
- Enforce configurable retention.
- Record exact argv, display command, cwd, start/end times, status, exit code,
  run relationships, and lifetime attachment statistics.
- Keep saved commands separate from per-run history and preserve cwd when a
  history entry is saved.
- Update README, CLI help, and scripts-help registry.

## Saved-command deletion and unique-command ledger

- Add an interactive `d` delete action in `runmux load -I`. It must show the
  selected saved command and require a y/n confirmation before deletion.
- Add `runmux load delete` with composable `--starts-with`, `--contains`,
  `--before DATE`, and `--not-run-for DAYS` filters. The default is a dry run
  that prints every matching saved command and requested display details;
  `-A/--apply` performs the deletion.
- Deleting a saved command must never remove its run history or unique-command
  statistics.
- Store a module-local JSON unique-command ledger. For every unique command it
  records total run count, first/last run timestamps, every run timestamp and
  runtime, and every distinct effective cwd used for the command.
- Update the ledger only with the effective child cwd. A caller's own cwd must
  not be recorded when a specific command cwd was supplied.
- Add history options for unique-command-only views, unique command paths, and
  complete run timestamp/runtime lists.

## Tests

- Migration, backup, retention, and corrupt-data errors.
- Concurrent writers.
- Newest-first global IDs (`0` is latest) and filtered-ID preservation.
- Prefix and contains matching, including case-insensitive and empty results.
- Recent and frequency ordering, grouped counts, and most-recent replay IDs.
- `runmux run -H -i ID` argv replay and `-P/--path` cwd restoration.
- Replay validation for bad IDs, missing cwd, conflicting arguments, and every
  attach/detach mode.
- Default command-and-ID-only output plus each optional metadata field.
- Interactive `r`, `s`, Enter, navigation, search, and quit hotkeys with a
  persistent bottom help row.
- Interactive filter replacement/removal, combined filters, metadata cycling,
  full-content wrapping, and multi-instance/path run dialog.
- fzf selection/action mapping and missing-fzf errors.
- Runtime, exit-code, success-rate, and attachment summaries.

## Verification boundary

- Run the previously passing suite before changing expectations.
- Run focused history/storage/CLI tests and the entire runmux suite together.
- Run Ruff, Black check, compileall, coverage, CLI help smoke tests, JSON-output
  smoke tests, and a real replay from a non-default working directory.
- Stop for manual validation before committing this stage.

Last edited: 2026-07-19 08:18:00 -07:00
