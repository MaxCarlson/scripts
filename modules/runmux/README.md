# runmux

`runmux` is a cross-platform managed process runner. It starts programs under a small
supervisor process, stores run metadata in a shared local registry, writes byte-preserving
ANSI output logs, and lets any later shell list, view, kill, restart, duplicate, or interact
with managed programs.

## Quick start

```powershell
runmux run -- pwsh -NoLogo -NoProfile -Command "1..10 | ForEach-Object { Write-Host \"tick $_\"; Start-Sleep -Seconds 1 }"
```

```powershell
runmux list
```

```powershell
runmux ls
```

```powershell
runmux view -i 0
```

```powershell
runmux interact -i 0
```

```powershell
runmux stats
runmux history
runmux history --starts-with ytaedl
runmux history --contains archive --most-common 10
runmux history --interactive
runmux history --fzf
runmux run --history --id 1 --path
runmux load
```

## Notes

- `runmux list` opens the live list. Use Up/Down to select a run, `v` to view,
  `i` to interact, and `q` to quit.
- `runmux ls` prints a non-interactive one-shot list.
- `runmux run ...` now enters interact mode by default. Use `-D/--detach` to
  start and return to the shell, or `-w/--view` / `-a/--attach` to view without
  forwarding ordinary keys to the program. Use `-c/--cwd` or its
  `-p/--run-path` alias to launch from an explicit directory without changing
  the caller's current directory.
- User-facing IDs are numeric and are reused after terminal runs are removed
  from the registry with `runmux remove -i ID`.
- `runmux rm` and `runmux remove` are aliases for removing one terminal record
  by ID. Terminal records are otherwise retained automatically up to the
  persistent `terminal_record_limit` (default 500).
- `runmux ls` shows active and paused runs by default. Add `-T/--terminal` to
  append terminal records, `-s/--status STATUS` (repeatable) to filter, and
  `-I/--interactive` for view/interact/duplicate/pause/kill/restart controls.
- `runmux config` displays persistent settings. For example:
  `runmux config -s terminal_record_limit 1000`.
- `runmux ls -P -d -e` adds cwd, timing, and exit-code detail rows. In
  `runmux ls -I`, select with arrows/`j`/`k` or Page Up/Page Down, then use
  `i` interact, `v` view, `s` save, `d` duplicate, `p` pause/resume, `k` kill, or `r`
  restart (terminal records only).
- `-A/--all-details` is the cosmetic shortcut for commands with multiple
  display toggles: history/load enable path, date, status, and runtime; `ls`
  enables path, date, and exit code. It never changes filtering or launches
  actions.
- `runmux history` assigns newest-first global history IDs (the newest entry is
  ID 0), but prints normal text rows oldest-to-newest so the latest command is
  last. Filter with `-b/--starts-with` and/or `-c/--contains`,
  and use `-m/--most-common [COUNT]` for frequency ordering (default 10).
  Filtered results retain their global IDs, so any displayed entry can be run
  with `runmux run -H/--history -i/--id ID`. Add `-P/--path` to replay it from
  its recorded working directory, and `-V/--verify` to require confirmation
  after showing the full command and effective path.
- History metadata is opt-in: `-d/--date`, `-P/--path`, `-S/--status`, and
  `-r/--runtime`. `-I/--interactive` opens a multi-row browser with visible
  hotkeys (arrows or `j`/`k` move, Page Up/Page Down move a page, `r` run,
  Enter inspect, `p` print full details, `s` save, `/` contains search, `b`
  prefix search, `c` clear filters, `v` cycle metadata, `w`/`x` wrap full
  content, and `q`/Esc exit). The inspector shows the full
  stored entry and can open its run dialog. The run dialog accepts an instance count and
  defaults to the command's original path; it can instead use the current
  directory or a manually entered path. `-f/--fzf` uses fzf when it is
  available on PATH.
- History and saved commands are stored repo-locally under
  `modules/runmux/.runmux/`.
- Save commands with `runmux run -s ...` or `runmux save -i ID`. Saved commands
  retain argv, cwd, name, terminal dimensions, and forced-color setting; replay
  uses that context unless a new `run` option overrides it. Use `runmux load`
  for normal or interactive (`-I`) saved-command browsing; it accepts the same
  filters and viewer controls as history. `cmd` remains an alias. Use
  `runmux load -T/--stats` for saved-command stats and
  `runmux run load -i ID` to launch a saved command by its stable saved ID.
- `runmux save -i RUN_ID` saves any existing managed run, including a running
  or paused one, with its current execution context. Use
  `runmux save -H HISTORY_ID` to save a history entry and its recorded cwd.
- `runmux stats` shows active run process count, thread count, CPU, RSS memory,
  disk read/write rates, system network rates, and best-effort NVIDIA process
  GPU memory. Quit with `q` then `y`, `Ctrl-Q`, or `Ctrl-C`.
- Linux, WSL2, macOS, and Termux use a real PTY, so programs generally see a terminal.
- Windows uses `pywinpty`/ConPTY when available, so full-screen TUI programs can see
  a pseudo-console. If `pywinpty` is missing, runmux falls back to pipe-backed capture;
  ANSI bytes are still preserved, but programs that require a real console/TTY may
  fall back or exit.
- `Ctrl-X` is the default interact prefix. Press `Ctrl-X` then `q` to detach.
