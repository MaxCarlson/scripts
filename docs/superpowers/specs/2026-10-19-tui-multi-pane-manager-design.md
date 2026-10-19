# Multi-Pane Management & Live Preview for CLI TUI

## 1. Intent & The Why

When users run long or complex CLI processes inside the curses TUI (such as `mangadl compress inventory`), the command output displays extensive diagnostic summaries, data tables, and candidate counts. Currently, exiting the running view (`Esc`) to configure a downstream command (such as `mangadl compress plan`) clears the screen and discards the visual context. Users must choose between losing access to the summary tables or restarting the command.

This design introduces a **Multi-Pane Workspace Manager** into `cli_tui`. Users can preserve finished or active runs in background panes, switch between panes with single keystrokes, view a split tree/preview browser, and launch interactive console shells or additional menu commands concurrently.

---

## 2. Goals, Non-Goals & Anti-Goals

### Goals
- **Context Preservation**: Save completed command output and tables in persistent pane buffers that remain accessible across tasks.
- **Top Tab Strip Navigation**: Render a clean numbered tab bar along the top header when multiple panes are active (`[1: inventory (done)]  ▶ [2: plan (editing)]`).
- **Instant Hotkey Cycling**: Jump between active panes using `[` / `]` or `Alt+Left` / `Alt+Right` without opening any menu.
- **Split Pane Tree & Live Preview (`p`)**: Provide a dual-pane manager overlay:
  - Left column (30% width): List of active panes with name and status indicators (`FINISHED`, `RUNNING`, `CONFIG FORM`, `CONSOLE`).
  - Right column (70% width): Full-fidelity, scrollable live preview of the highlighted pane's output or form.
- **Concurrent Subprocesses**: Support background execution so long-running commands continue streaming while the user works in another pane.
- **Manual Pane Creation (`n`) with Choice**: Prompt the user to choose between:
  1. `New Command (Menu)`: Launches a fresh command selection tree.
  2. `Interactive Console Shell`: Launches an interactive shell (`powershell.exe` / `cmd.exe`) embedded in the TUI runner.
- **Pane Deletion**: Close the selected pane (`d`) with process termination, or delete all panes (`D`) to collapse back to a single dashboard.

### Non-Goals
- Full terminal emulation (e.g. VT100 terminal multiplexer like tmux or screen with arbitrary full-screen ncurses apps inside ncurses apps).
- Tiling multiple panes side-by-side simultaneously on the primary screen (screens are full-width; multi-pane browsing is via tabs and the manager split overlay).
- Cross-session persistence to disk across application restarts (panes are session-scoped).

### Anti-Goals
- Blocking the main TUI loop when a background pane produces output or waits on I/O.
- Dropping or mutating unrelated panes when one pane finishes or errors.

---

## 3. Constraints & Platform

- **Platform**: Windows PowerShell / Windows Terminal, Linux, macOS.
- **Runtime**: Python 3.10+ standard library and `cli_tui` module.
- **Rendering**: Standard curses / windows-curses with existing `VirtualTerminalBuffer` and ANSI color support.
- **Zero Third-Party Dependencies**: Pure standard library (`curses`, `subprocess`, `threading`, `codecs`).

---

## 4. Detailed Design & Architecture

### 4.1 Data Architecture: `PaneSession`
Each pane is represented by an isolated `PaneSession` object:

```python
class PaneType(Enum):
    COMMAND = "command"     # Menu, form, or executed CLI command
    CONSOLE = "console"     # Interactive shell console

@dataclass
class PaneSession:
    id: str                             # Unique UUID or sequential identifier
    title: str                          # e.g., "compress inventory", "PowerShell"
    pane_type: PaneType
    screen_mode: TuiScreenMode          # MENU, FORM, RUNNING, CONSOLE
    navigation: NavigationStack         # Isolated breadcrumb stack for this pane
    current_form: Optional[FormState]   # Form arguments state if in FORM mode
    runner: Optional[ProcessRunner]     # Background or completed process runner
    viewport: OutputViewport            # Scrollable viewport for output/console
    created_at: float
```

The top-level `CliTuiApp` maintains:
- `panes: List[PaneSession]`: List of all currently open panes.
- `active_pane_index: int`: Index of the currently active/focused pane.
- `is_pane_manager_open: bool`: Toggle state for the split Pane Manager overlay.
- `manager_cursor: int`: Highlighted item in the Pane Manager list.

### 4.2 Top Tab Strip Layout
When `len(panes) > 1`, the top header of the virtual screen renders the tab bar:

```
┌─ [1: inventory (done)]  ▶ [2: compress plan (editing)]  [+ Shift+Esc] ───────────────┐
```

- Inactive tabs display: `[<index>: <title> (<status>)]` (dim / normal).
- Active tab displays: `▶ [<index>: <title> (<status>)]` (bold / cyan highlight).
- A shortcut hint `[+ Shift+Esc]` is displayed at the right end of the tabs.

### 4.3 Keybindings & Navigation

| Key | Context | Action |
|---|---|---|
| `Shift+Esc` (or `s` when finished) | Running / Form / Menu | Preserves current pane, creates new pane, and opens Command Menu |
| `[` or `Alt+Left` | Global | Cycle to previous pane |
| `]` or `Alt+Right` | Global | Cycle to next pane |
| `p` | Global (when not typing text) | Open / close the Split Pane Manager overlay |
| `Enter` | Pane Manager | Switch into the highlighted pane and close manager |
| `n` | Pane Manager | Open "New Pane" choice dialog (`[1] Command Menu`, `[2] Shell Console`) |
| `d` | Pane Manager | Delete highlighted pane (terminates runner if active) |
| `D` | Pane Manager | Delete all panes and collapse to single clean workspace |
| `Esc` | Pane Manager | Close Pane Manager and return to current active pane |

### 4.4 Split Pane Manager Overlay (`p`)
When `is_pane_manager_open` is `True`, the entire screen renders the two-column manager layout:

```
┌─ MangaDL Pane Manager ───────────────────────────────────────────────────────┐
│ PANES (2 Active)          │ PREVIEW: Pane 1 (compress inventory)                     │
│ ─────────────────────────┼───────────────────────────────────────────────────────────│
│ ▶ 1. compress inventory  │   Status: FINISHED (Success)  |  Elapsed: 206.2s          │
│    FINISHED (0 errors)   │                                                           │
│                          │   Inventory Summary           Target: B:\Hent\hent1...    │
│   2. compress plan       │   ┌─────────────────────────────┬─────────────────────┐   │
│    CONFIG FORM           │   │ Gallery folders with images │               1,104 │   │
│                          │   │ Eligible image headers      │              66,233 │   │
│                          │   │ File bytes                  │            29.36 GB │   │
│                          │   │ Unreadable candidates       │                   0 │   │
│                          │   │ Headers reused / inspected  │          66,233 / 0 │   │
│                          │   └─────────────────────────────┴─────────────────────┘   │
└──────────────────────────┴───────────────────────────────────────────────────────────┘
└─ [Enter] Switch  [n] New Pane  [d] Delete  [D] Delete All  [Esc] Close ──────────────┘
```

- **Left column (30%)**:
  - `↑` / `↓` moves `manager_cursor`.
  - Shows index, title, and colored status badge (`FINISHED` green, `RUNNING` cyan, `CONFIG` yellow, `CONSOLE` magenta).
- **Right column (70%)**:
  - Dynamically renders `panes[manager_cursor]` using that pane's viewport lines and scroll offset.
  - Allows scrolling the preview window (`PgUp` / `PgDn`) while keeping focus in the manager list.

### 4.5 Interactive Console Pane (`PaneType.CONSOLE`)
When the user chooses `Interactive Shell Console`:
- Operates as a command REPL runner inside `cli_tui` (pure standard library).
- Displays a prompt showing the active working directory: `[B:\Hent]> ` with an editable command input line at the bottom.
- Executing a command (Enter) invokes `ProcessRunner` with `VirtualTerminalBuffer` streaming, capturing output and exit codes into the pane viewport.
- Internal commands like `cd <dir>` update the pane's active working directory for subsequent commands.
- Typing `exit` or pressing `d` in the Pane Manager closes and deletes the console pane.

### 4.6 Argument & Context Inheritance Across Panes
When a user branches via `Shift+Esc` (or `s`) from an existing pane into a new command pane:
- Compatible argument values (e.g. `destination`, `workspace`, `target`, `url`, etc.) configured in the source pane's `FormState` are automatically pre-populated into the destination command's form.
- The new pane's working directory matches the source pane's working directory.
- This enables fluid sequential workflows (e.g. running `compress inventory -d hent1`, then pressing `Shift+Esc` to immediately have `compress plan` pre-filled with `-d hent1`).

### 4.7 Finished Pane Preservation Policy
To fulfill the core requirement of never losing visual findings:
- Finished command panes are preserved as immutable inspection views.
- While viewing a finished pane, pressing `Esc` navigates back to the previously active pane (or opens the Pane Manager) rather than wiping the runner output.
- A dedicated hotkey `r` (Re-run) is available if the user explicitly wants to re-execute the command in that pane.

---

## 5. Builder Calls & Decisions

The following implementation calls were settled during the builder check review:
- **Interactive Console Architecture**: Implemented as a clean command REPL runner using standard `ProcessRunner` and `VirtualTerminalBuffer`. This provides zero-dependency compatibility across Windows, Linux, and macOS without requiring external pseudo-terminal libraries.
- **Finished Pane Navigation**: `Esc` in a finished pane safely returns to the previously active working pane, protecting output tables from accidental loss.
- **Keybinding Fallbacks**: Because terminal emulators handle `Shift+Esc` inconsistently (some emit `\033`, some `\033[27;2;27~`), both `Shift+Esc` and `s` (when on a finished/running screen) trigger pane preservation and branching. Additionally, `[` and `]` provide single-key pane switching alongside `Alt+Left` / `Alt+Right`.

---

## 6. What is Left to the Builder

- Implementing `PaneSession` dataclass and container in `cli_tui/state.py`.
- Adding `render_tab_strip()` and `render_pane_manager()` in `cli_tui/app.py`.
- Connecting argument inheritance helper `copy_matching_values(source_form, target_form)`.
- Adding unit test suite for multi-pane lifecycle, tab cycling, argument inheritance, and split manager rendering.
