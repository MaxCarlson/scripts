# runmux

## Native terminal workspace

The native interface is optional. From the scripts repository root, install
the repository-local `cli_tui` package and the Runmux `tui` extra:

```powershell
python -m pip install -e .\modules\cli_tui
python -m pip install -e ".\modules\runmux[tui]"
```

Then start the workspace with `runmux tui`. The base Runmux CLI does not need
these terminal UI dependencies; if they are missing, the command prints these
installation steps and exits without opening the registry.

## Authenticated browser view and process launch

Install the reusable browser service and Runmux's optional web extra:

```powershell
python -m pip install -e .\modules\web_ui_tools
python -m pip install -e ".\modules\runmux[web]"
```

Start the dashboard with `runmux web`. The service binds to `127.0.0.1:8787` by default and prints a startup login code in the launching terminal. Open the printed local URL and enter that code. It remains valid until the server exits; the browser receives a short-lived opaque `HttpOnly`, `SameSite=Strict` cookie, and neither code nor session value is placed in a URL or returned to page JavaScript. Treat this code as process-execution access: an authenticated browser session can launch commands under the account running `runmux web`. Access logs are disabled to keep request details out of logs. Only loopback IP bind addresses are accepted, and API calls require the matching local browser origin or a browser same-origin fetch marker, plus an authenticated session.

Use `runmux web -H 127.0.0.1 -p 8787 -s <state-directory>` to choose the bind address, port, and existing registry. `-H/--host`, `-p/--port`, and `-s/--state-dir` are available in short and long forms. The default state directory follows Runmux's existing `RUNMUX_HOME`, `LOCALAPPDATA`, and XDG rules.

The browser shows the full stable run ID, optional user name, executable basename, status, PID, exit code, runtime, and timestamps. Names and executable basenames may themselves identify private projects or tools, so anyone with the local browser session can see them. The view hides existing-run command arguments, working directories, environment overrides, log paths, IPC ports, and credentials. User-provided names and process output are treated as untrusted text. Output is decoded incrementally as UTF-8 (invalid bytes become replacement characters), ANSI/control sequences are stripped across chunk boundaries, each response is limited to 64 KiB, and the visible transcript is capped at 512 Ki characters.

The explorer groups runs by their recorded status and supports searching by name, executable, status, or full run ID. Selecting a run opens a browser-only workspace tab; switching or closing a tab changes only the browser view. Each process workspace keeps the Output, Terminal, and Details views together, and the process tab strip scrolls horizontally when needed.

The browser opens the existing SQLite registry with `mode=ro`; missing registries display as empty without initialization. The authenticated New Process tab is the explicit write operation: it launches through the same `create_managed_run` path as `runmux run`, registering and supervising the process. Enter the executable in Command and put each argument on its own line; each line is passed literally as one argv element, so shell quoting and shell expansion are not applied. The working-directory field defaults to the directory from which `runmux web` was started. A successful launch opens the new run tab and its output. Invalid commands, names, and directories keep the form available with an actionable error. Existing-run lifecycle controls are not exposed from the browser. Closing a process view or the web server does not stop managed processes.

The **Terminal** process view uses locally packaged xterm.js assets to render the original ANSI output. Its same-origin WebSocket requires the authenticated browser session cookie and trusted loopback host/origin checks. Opening the view creates a normal Runmux viewer attachment; requesting control creates an interact attachment through the supervisor. Keystrokes are sent only when that session holds the supervisor's FIFO input lock, and the supervisor remains authoritative if ownership changes. Resizing is sent only while the browser session reports the input lock. Reconnecting creates a fresh viewer attachment and replays at most the latest 128 KiB before following output in bounded chunks. Terminal scrollback is capped at 5,000 lines.

Closing the terminal view, locking the browser session, losing the WebSocket, or shutting down `runmux web` closes only the browser attachment and releases its input-lock ownership. It does not stop, restart, or otherwise change the supervised process. The existing Output and Details views remain available; browser-based process lifecycle controls are still not exposed.

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
runmux tui
```

```powershell
runmux web --host 127.0.0.1 --port 8787
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

- `runmux tui` opens the native persistent process workspace. Press `?` for
  the hotkeys. It supports process selection and details, live and historical
  output views, tabs, saved workspace state, command history and saved commands,
  and process operations. Closing a view or the TUI never stops a managed
  process. Workspace state is scoped to the canonical directory where Runmux
  starts and the selected Runmux state directory.
- `runmux web` starts the authenticated local browser interface. The New Process
  tab can launch supervised commands; other lifecycle controls remain unavailable.
  The Terminal view can send program input
  only while its authenticated attachment owns the supervisor input lock. It
  prints a one-time startup login code that remains valid until the web server
  exits. Closing the browser or stopping the web server only detaches browser
  sessions and never stops managed processes. Install browser dependencies with
  the `web` extra; they are loaded only when this command is selected.
  When `RUNMUX_LLM_MONITOR_ENABLED=true` is set, the web dashboard enables an
  "LLM Monitor" workspace tab providing read-only observability over local OpenCode
  or LM Studio sessions, context utilization, alerts, hardware metrics, and timeline
  events.
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
- In `runmux load -I`, press `d` and confirm `y` to delete the selected saved
  command. `runmux load delete` is a dry run; combine `-b/--starts-with`,
  `-c/--contains`, `-B/--before DATE`, and `-N/--not-run-for DAYS`, then add
  `-a/--apply` to delete matching saved commands. This never removes history or
  unique-command statistics.
- `runmux history -u/--unique` views the module-local unique-command ledger.
  Add `-X/--unique-paths` for every effective cwd and `-R/--run-details` for
  every recorded run timestamp/runtime.
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


## Optional LLM Monitor Integration

Runmux Web optionally integrates the read-only observability and diagnostics API from the `llm_monitor` module.

### Configuration & Activation

The integration is disabled by default and requires explicit server-side opt-in:

```powershell
$env:RUNMUX_LLM_MONITOR_ENABLED = "1"
$env:RUNMUX_LLM_MONITOR_OPENCODE_URL = "http://127.0.0.1:4096"
$env:RUNMUX_LLM_MONITOR_LMSTUDIO_URL = "http://127.0.0.1:1234"
# Optional existing telemetry database (never created if missing):
# $env:RUNMUX_LLM_MONITOR_DATABASE = "C:\path\to\existing_telemetry.db"
runmux web
```

### Safety & Architecture

- **Read-Only Invariant:** Monitoring endpoints never trigger recording, model inference, parameter mutation, job recovery, or Runmux process termination.
- **Python Compatibility:** Ordinary Runmux runs on Python 3.10+. Monitoring capabilities require Python 3.11+ and the optional `llm_monitor` package; when running on Python 3.10 or without `llm_monitor`, Runmux starts normally and reports the integration status as `unavailable`.
- **Existing-Only Database:** If a telemetry database is configured, Runmux verifies it is an existing file before opening it in read-only mode. It will never create a database or start a background recorder.
- **Authenticated REST Endpoints:**
  - `GET /api/llm-monitor/v1/status`: Capability availability and configuration (no provider I/O).
  - `GET /api/llm-monitor/v1/snapshot`: In-process cached system and session snapshot.
  - `GET /api/llm-monitor/v1/sessions/detail`: Detailed session diagnostics and MCP correlations.
  - `GET /api/llm-monitor/v1/sessions/timeline`: Keyset-paginated historical events page.
  - `GET /api/llm-monitor/v1/alerts`: Persisted alerts filterable by status (`active`, `acknowledged`, `resolved`).
  - `GET /api/llm-monitor/v1/hardware`: Point-in-time GPU metrics.
