# Terminal Launcher

`terminal-launcher` turns process descriptions into ordered tabs and panes. Its plan models do not depend on a terminal program; `WindowsTerminalBackend` is the first backend. The package has no runtime dependencies and does not import or depend on `agent_continuity`.

## Quick start

The module can be imported with the repository's `modules` directory on `PYTHONPATH`, or installed with `pip install -e modules/terminal_launcher`.

```python
from terminal_launcher import PaneSpec, WindowsTerminalBackend, group_panes

panes = [
    PaneSpec("Build", ("python", "-m", "compileall", "src"), cwd=r"C:\work\project"),
    PaneSpec("Tests", ("python", "-m", "pytest", "tests"), cwd=r"C:\work\project"),
]

plan = group_panes(panes, panes_per_tab=2)
backend = WindowsTerminalBackend()

preview = backend.preview(plan)  # Builds a safe summary; it does not launch processes.
result = backend.launch(plan)    # Submits one wt.exe command for all tabs and panes.
```

The package-level API is:

```python
from terminal_launcher import (
    PaneSpec,
    TabSpec,
    TerminalLaunchPlan,
    WindowsTerminalBackend,
    group_panes,
    powershell_plan,
)
```

## Open PowerShell 7 in a named window

Use `powershell_plan()` when work should stay in the same Windows Terminal window. The first launch creates the named
window if it does not exist; later calls with the same name add tabs to that window.

```python
from terminal_launcher import WindowsTerminalBackend, powershell_plan

backend = WindowsTerminalBackend()
plan = powershell_plan(target_window="scripts-work", cwd=r"C:\src\scripts")
result = backend.launch(plan)
```

The plan starts `pwsh.exe -NoLogo -NoExit` with the requested working directory. Call `powershell_plan()` again with
`target_window="scripts-work"` to add another PowerShell 7 tab to the same window. `launch()` still reports request
submission; it does not claim that PowerShell started. Use process instrumentation or an explicit startup receipt when
the caller needs positive runtime acknowledgment.

The default tab title `PowerShell 7` matches ProcWatch's existing interactive-title rule in `smart` mode. ProcWatch's
`all-consoles` mode still suppresses every console window by design; Terminal Launcher does not set an exclusion or
bypass for its launches.

`PaneSpec.argv` is an argument vector. Windows Terminal accepts child commands as command-line text and uses semicolons to separate its own operations. The backend therefore passes a URL-safe encoded payload to a small Python relay, which starts the requested executable with the original argument vector and working directory using `shell=False`. The payload prevents shell metacharacters and semicolons in child arguments or paths from being interpreted by Windows Terminal. This uses the same Python interpreter that runs the library. The relay file ships inside this package.

Windows Terminal's command separator also constrains metadata. The backend rejects tab titles and `target_window` values containing semicolons instead of silently changing them. Spaces and Unicode are supported in titles, window names, executable paths, working directories, and child arguments.

## Layouts

`group_panes` accepts `panes_per_tab` from 1 through 4, defaults to 2, and preserves pane order. Each resulting tab uses a canonical layout:

| Panes | Layout | Arrangement |
| --- | --- | --- |
| 1 | `single` | One pane |
| 2 | `two-column` | Side by side |
| 3 | `three-left` | One large left pane; two stacked right panes |
| 4 | `grid` | 2×2 grid |

`TabSpec.layout` also accepts `auto`; a backend resolves it from the pane count. An empty input to `group_panes` produces an empty plan, and launching an empty plan is a no-op.

## Preview and launch results

`preview()` returns immutable operation summaries, capability names, and warnings. It does not invoke a process. It deliberately excludes executable arguments and environment data from diagnostics.

`launch()` returns `LaunchResult` with one of these request statuses:

- `submitted`: Windows Terminal accepted the command-line submission.
- `failed`: the request could not be submitted or Windows Terminal returned a failure status.
- `no_op`: the plan contains no tabs.

`result.process_state` remains `unknown` after submission. A zero exit status from `wt.exe` does not prove that every pane process started. Missing executables, unsupported platforms, invalid plans, and unsupported layouts use typed exceptions during preview/build validation; a missing executable during launch is returned as a failed request.

## Windows Terminal behavior and limits

- Tabs and panes are sent in one `wt.exe` invocation.
- The relay sets each child process's working directory. The composite tab title is applied to every pane, and `--suppressApplicationTitle` keeps applications from replacing it.
- `target_window` maps to Windows Terminal's `--window` option. When it is `None`, Windows Terminal applies the user's `windowingBehavior` preference; preview warns about this choice.
- The backend uses documented `new-tab`, `split-pane`, and `move-focus` commands, plus `--window`, `--title`, and `--suppressApplicationTitle` options. It does not change Windows Terminal's global settings. See [Microsoft's Windows Terminal command-line reference](https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments).
- Side-effect-free preview does not invoke `wt.exe` to discover its version. Compatibility is assumed from the documented command interface and reported as a warning. Exact geometry and child process startup require a separate live Windows Terminal check.

The backend reports terminal request submission only. It does not attach to panes later, monitor child processes, manage sessions, or implement dispatcher/provider behavior. Future backends can expose different capability sets without changing `PaneSpec`, `TabSpec`, or `TerminalLaunchPlan`.

## Development checks

From this directory:

```powershell
python -m pytest
ruff check .
```
