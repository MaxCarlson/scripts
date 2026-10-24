# cli_tui

Reusable argparse-to-termdash TUI engine. Automatically converts any `argparse.ArgumentParser` (including nested subparsers) into an interactive curses TUI with live streaming process execution, multi-pane workspace management, embedded shell consoles, and a native side-by-side comparison image viewer.

## Key Features

- **Automatic Parser Introspection**: Recursively inspects supported Python `argparse.ArgumentParser` actions, including nested subparsers, to extract command hierarchies, arguments, defaults, choices, flags, and help text. Unsupported custom actions are rejected explicitly.
- **Dynamic Form Widgets**: Automatically generates interactive form widgets for boolean flags (`[X]`), choice dropdowns (`◀ opt ▶`), text inputs (`[ value ]`), counter flags (`-v`, `-vv`), and multi-choice selections.
- **Live Streaming Process Runner**: Runs child processes asynchronously, streaming stdout and stderr into a thread-safe circular buffer with ANSI color rendering (8-color palette) and virtual terminal in-place overwrite (`\r`) support.
- **Scrollable Output Viewport**: Top-aligned, width-aware line wrapping that preserves table borders and ANSI formatting, with real-time status, execution duration, and line scroll indicators (`Lines X-Y of Z`).
- **Persistent Pane Workspaces**: Save and restore pane navigation, forms, scrollback, console directory, and active pane. Layouts are scoped to the canonical launch directory and app ID; running commands are restored as read-only output and are never relaunched.
- **Pane Output Capture**: Use `Ctrl+O` to choose a directory and filename, then stream the pane's current output and new process output into a UTF-8 file. Existing files require overwrite confirmation.
- **Multi-Pane Workspace Manager**:
  - Top tab strip navigation (`[1: title (status)] ▶ [2: title (status)] [+ Shift+Esc]`).
  - Hotkey pane cycling (`[` / `]`).
  - Branching with argument inheritance (`Shift+Esc`, `Ctrl+T`, or `s` when finished).
  - Split 30/70 Pane Manager overlay (`p`) with a live scrollable preview of background jobs.
  - Modal new pane dialog (`n`) to open fresh command trees or interactive shell consoles.
- **Interactive Shell Console Pane**: Embedded shell REPL with working directory tracking, `cd` navigation, and subprocess command execution without leaving the curses interface.
- **Side-by-Side Comparison Image Viewer**: Native Tkinter + Pillow viewer for visual comparisons (e.g. compression preview sets), featuring aspect-ratio-preserving scaling, 1:1 zoom toggle, and keyboard navigation.
- **Universal Key Navigation**:
  - `q`: Exit confirmation prompt (context-aware: types 'q' in text fields, prompts in navigation).
  - `Q`: Unconditional immediate exit (kills direct child processes and restores the terminal).
  - After confirming `q`, choose whether to save the pane layout before exiting.
  - `Ctrl+S`: Save the current pane layout immediately.
  - `Ctrl+O`: Choose a destination file for the active pane's output.
  - `Esc`: Hierarchical back navigation (running -> form -> parent menu -> exit prompt).
- **Post-Run Action Hooks**: Register custom callback actions (e.g. `[v] View Previews`) triggered upon process completion.
- **100% Headless Testability**: Includes virtual screen rendering (`render_virtual_screen`) and keystroke dispatch (`process_key`) for comprehensive unit testing without an interactive terminal.

---

## Architecture & Modules

| Module | Description | Key Classes / Functions |
|---|---|---|
| `cli_tui.schema` | Argparse AST inspection and data models | `introspect_parser`, `CliCommand`, `CliArgument` |
| `cli_tui.state` | Navigation, form state, and multi-pane workspace models | `FormState`, `NavigationStack`, `PaneSession`, `PaneWorkspace`, `copy_matching_form_values` |
| `cli_tui.widgets` | Interactive form field widgets | `BooleanWidget`, `ChoiceWidget`, `TextWidget`, `CountWidget`, `MultiChoiceWidget`, `create_widget_for_arg` |
| `cli_tui.process_runner` | Subprocess streaming, ANSI buffer, and viewport | `ProcessRunner`, `OutputViewport`, `VirtualTerminalBuffer`, `wrap_ansi_line` |
| `cli_tui.console_pane` | Interactive shell console runner | `ConsolePaneRunner` |
| `cli_tui.app` | Main curses application controller and overlays | `CliTuiApp`, `PostRunAction`, `addstr_ansi` |
| `cli_tui.layout_store` | Root/app-scoped atomic pane-layout storage | `PaneLayoutStore` |
| `cli_tui.output_capture` | UTF-8 pane transcript and live output writer | `OutputFileCapture` |
| `cli_tui.preview_set` | Preview discovery and variant grouping | `scan_preview_directory`, `PreviewSet`, `PreviewItem`, `PreviewVariant` |
| `cli_tui.image_viewer` | Native Tkinter side-by-side comparison viewer | `SideBySideImageViewer`, `ImageViewerState`, `launch_image_viewer` |

## Parser-Only Integration

Python tools that only need parser metadata can import `cli_tui.schema` without
loading the curses app, widgets, or image viewer:

```python
from cli_tui.schema import introspect_parser

command_tree = introspect_parser(parser)
```

`CliCommand` and `CliArgument` are Python objects, not a JSON wire format. Their
defaults, choices, or `type_fn` may contain non-serializable values. See
[`docs/argparse-and-browser-boundary.md`](docs/argparse-and-browser-boundary.md)
for the supported argparse subset and a provisional browser metadata direction.
The owning application parser remains responsible for validating and executing
commands.

---

## Keyboard Shortcuts

### Global & Navigation

| Key | Context | Action |
|---|---|---|
| `q` | Navigation | Prompt to exit (`Are you sure you want to exit? (y/n)`) |
| `Q` | Any screen | Force quit immediately (kills active runner, exits 0) |
| `Esc` | Menu / Form / Running | Navigate back up the command hierarchy |
| `[` / `]` | Global | Cycle to previous / next workspace pane |
| `p` | Global | Toggle Split Pane Manager overlay |
| `Shift+Esc` / `Ctrl+T` | Global | Branch from active pane to a new pane with argument inheritance |
| `Ctrl+S` | Global | Save the current pane layout |
| `Ctrl+O` | Global | Choose a file for the active pane's output |

### Form Configuration Screen

| Key | Action |
|---|---|
| `↑` / `↓` (or `k` / `j`) | Move focus between argument fields and buttons |
| `←` / `→` (or `h` / `l`) | Cycle choices or adjust counter values |
| `Space` / `Enter` | Toggle checkbox, cycle choice, or activate button (`[ Run ]`, `[ Preview CLI ]`, `[ Back ]`) |
| `e` (or `Enter`) | Enter inline text editing mode on text inputs |
| `Esc` | Cancel / exit inline text editing mode |

### Process Running & Output Viewport

| Key | Action |
|---|---|
| `↑` / `↓` (or `k` / `j`) | Scroll output up / down by 1 line |
| `PgUp` / `PgDn` | Scroll output by 15 lines |
| `Home` (or `g`) | Jump to top of output |
| `End` (or `G`) | Jump to bottom of output (enables auto-scroll) |
| `c` | Cancel / terminate running process |
| `s` | Branch into a new command pane |
| `r` | Re-run command after completion |
| `Enter` | Return to argument form after completion |

### Split Pane Manager Overlay (`p`)

| Key | Action |
|---|---|
| `↑` / `↓` (or `k` / `j`) | Move highlight through list of active panes |
| `PgUp` / `PgDn` | Scroll live preview of highlighted pane |
| `Enter` | Switch to highlighted pane and close manager |
| `n` | Open New Pane dialog (`[1] Command Menu`, `[2] Shell Console`) |
| `d` | Delete highlighted pane (terminates runner if active) |
| `D` | Delete all panes and reset to single clean workspace |
| `Esc` | Close Pane Manager overlay |

### Side-by-Side Image Viewer (`tkinter`)

| Key | Action |
|---|---|
| `←` / `→` (or `h` / `l`) | Cycle quality levels / recipe variants for current image |
| `↑` / `↓` (or `k` / `j`) | Cycle between sample images in preview set |
| `Space` | Toggle 1:1 pixel zoom vs fit-to-panel scaling |
| `Esc` / `q` / `Q` | Close image viewer and return to TUI |

---

## Pane Layout Storage

`CliTuiApp` loads a saved layout for the current launch directory and parser program name. Layouts are stored under `%LOCALAPPDATA%\cli_tui\layouts` on Windows, or `$XDG_CONFIG_HOME/cli_tui/layouts` (default `~/.config/cli_tui/layouts`) elsewhere. Set `CLI_TUI_LAYOUT_DIR` to override the store location, or pass `layout_dir`, `launch_dir`, and `app_id` to `CliTuiApp` for explicit scoping.

A saved layout keeps pane order, active pane, navigation path, form values, each pane's scroll position, console directory/history, and the last visible output. A running command is not restarted when its layout is restored. Press `Ctrl+S` to save at any time; confirming `q` asks whether to save before exit. `Q` retains its immediate force-quit behavior.

`Ctrl+O` opens the output capture dialog. Choose a directory and filename; an existing file is never overwritten without a separate confirmation. Capture starts with the pane's current scrollback and follows new output from the active process or later commands in a console pane.

---

## Quickstart & Usage

### 1. Minimal Integration (Wrap Existing Argparse CLI)

```python
import argparse
from cli_tui import CliTuiApp

def main():
    parser = argparse.ArgumentParser(prog="mytool", description="Sample CLI")
    subparsers = parser.add_subparsers(dest="command")

    build_cmd = subparsers.add_parser("build", help="Build project")
    build_cmd.add_argument("--release", action="store_true", help="Build in release mode")
    build_cmd.add_argument("--target", choices=["x86", "arm64"], default="x86")

    # Launch interactive curses dashboard
    app = CliTuiApp(parser=parser, title="MyTool Dashboard")
    return app.run()

if __name__ == "__main__":
    main()
```

### 2. Custom Executable & Subcommand Filtering

```python
import sys
from cli_tui import CliTuiApp, introspect_parser
from mytool.cli import build_parser

def launch_dashboard():
    parser = build_parser()
    root_cmd = introspect_parser(parser)

    # Optionally filter out self-referential 'tui' subcommand
    filtered_subcommands = {
        name: sub_cmd for name, sub_cmd in root_cmd.subcommands.items() if name != "tui"
    }
    root_cmd = root_cmd.__class__(
        name="mytool",
        prog="mytool",
        description=root_cmd.description,
        help=root_cmd.help,
        epilog=root_cmd.epilog,
        arguments=root_cmd.arguments,
        subcommands=filtered_subcommands,
        subparsers_dest=root_cmd.subparsers_dest,
    )

    app = CliTuiApp(
        root_command=root_cmd,
        title="MyTool Interactive Dashboard",
        executable=[sys.executable, "-m", "mytool"],
    )
    return app.run()
```

### 3. Registering Post-Run Action Hooks

```python
from cli_tui import CliTuiApp, PostRunAction

def on_view_results(app: CliTuiApp):
    from cli_tui.image_viewer import launch_image_viewer
    dest = app.current_form.get_value("destination") if app.current_form else None
    launch_image_viewer(destination=dest)

app.add_post_run_action(
    PostRunAction(
        key=ord("v"),
        label="[v] View Results",
        callback=on_view_results,
        predicate=lambda a: a.runner is not None and a.runner.exit_code == 0,
    )
)
```

### 4. Standalone Image Viewer

```python
from pathlib import Path
from cli_tui.image_viewer import launch_image_viewer

# Scan and display preview variants under a directory
launch_image_viewer(preview_dir=Path(".mangadl/my_book/previews"))
```

---

## Testing

Run unit tests via `pytest`:

```powershell
python -m pytest modules/cli_tui/tests/
```
