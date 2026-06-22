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
runmux cmd
```

## Notes

- `runmux list` opens the live list. Use Up/Down to select a run, `v` to view,
  `i` to interact, and `q` to quit.
- `runmux ls` prints a non-interactive one-shot list.
- `runmux run ...` now enters interact mode by default. Use `-D/--detach` to
  start and return to the shell, or `-w/--view` / `-a/--attach` to view without
  forwarding ordinary keys to the program.
- User-facing IDs are numeric and are reused after terminal runs are removed
  from the registry with `runmux remove -i ID`.
- `runmux rm` and `runmux remove` are aliases. With no ID they remove all
  terminal records; with an ID or `-i/--id` they remove one terminal run.
- `runmux remove-finished` removes all terminal runs, including finished, failed,
  killed, and lost records. Add `-C/--clean-only` to remove only cleanly
  finished runs.
- `runmux history` prints commands launched through runmux. History and saved
  commands are stored repo-locally under `modules/runmux/.runmux/`. Commands
  are printed on `cmd>` lines for easy copying; `runmux history -I` opens an
  Up/Down history browser that prints the selected command with Enter.
- Save commands with `runmux run -s ...` or `runmux save -i ID`. Use `runmux cmd`
  to browse saved command bases and commands, `runmux cmd -S` for saved-command
  stats, and `runmux run cmd -i` to pick and run a saved command interactively.
- `runmux stats` shows active run process count, thread count, CPU, RSS memory,
  disk read/write rates, system network rates, and best-effort NVIDIA process
  GPU memory. Quit with `q` then `y`, `Ctrl-Q`, or `Ctrl-C`.
- Linux, WSL2, macOS, and Termux use a real PTY, so programs generally see a terminal.
- Windows uses `pywinpty`/ConPTY when available, so full-screen TUI programs can see
  a pseudo-console. If `pywinpty` is missing, runmux falls back to pipe-backed capture;
  ANSI bytes are still preserved, but programs that require a real console/TTY may
  fall back or exit.
- `Ctrl-X` is the default interact prefix. Press `Ctrl-X` then `q` to detach.
