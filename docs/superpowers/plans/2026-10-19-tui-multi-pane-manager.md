# Multi-Pane Management & Live Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a multi-pane workspace manager for `cli_tui` enabling users to preserve finished/running command outputs into persistent background panes, cycle between panes via top tab strip or hotkeys, inspect panes side-by-side in a split manager with live preview, and launch embedded console shells.

**Architecture:** A `PaneWorkspace` state manager tracks isolated `PaneSession` objects (each maintaining its own `NavigationStack`, `FormState`, `ProcessRunner`, and `OutputViewport`). `CliTuiApp` integrates the workspace into its rendering loop, displaying a top numbered tab strip when multiple panes exist, routing global cycling keys (`[` / `]`), handling `Shift+Esc` branching with argument inheritance, and rendering a 30/70 split Pane Tree & Preview Manager overlay.

**Tech Stack:** Python 3.10+, `curses` / `windows-curses`, standard library (`subprocess`, `threading`, `codecs`, `dataclasses`, `enum`).

**Spec:** [`docs/superpowers/specs/2026-10-19-tui-multi-pane-manager-design.md`](file:///C:/Users/mcarls/src/scripts/docs/superpowers/specs/2026-10-19-tui-multi-pane-manager-design.md)

## Global Constraints

- Pure Python standard library: zero external runtime dependencies (`curses`, `subprocess`, `threading`, `codecs`).
- Zero breakage of existing single-pane behavior: when only 1 pane exists, the top tab strip is hidden and standard navigation operates unchanged.
- Preserve finished command output: finished panes must be immutable inspection buffers; `Esc` must never clear finished results.
- Cross-pane context inheritance: branching via `Shift+Esc` copies compatible argument values from source to target form.
- Terminal width/height safety: all new overlays (tab strip, split manager, choice dialog) must clamp to terminal bounds without raising `curses.error`.

## Review Focus

1. **Terminal Keycode Diversity on `Shift+Esc`**: Some Windows terminal emulators emit raw `\033` (ASCII 27), while others emit extended escape sequences `\033[27;2;27~` or ignore shift. Provide single-key `s` (when in finished/running view) and `Ctrl+T` as rock-solid fallbacks.
2. **Concurrent Background Runner Output**: When a pane runs in the background while the user edits a form in another pane, the background runner's reader thread must continue updating its `VirtualTerminalBuffer` thread-safely without interfering with the active pane.
3. **Pane Deletion Lifecycle**: Deleting an actively running pane must terminate the underlying subprocess and join the reader thread before removing the session from the workspace list.
4. **Console REPL Working Directory Persistence**: Changing directories via `cd` in an embedded console pane must update the pane's active working directory for subsequent commands executed in that console.
5. **Narrow Terminal Responsiveness in Split View**: If terminal width is less than 60 columns, the split manager must gracefully degrade by stacking list and preview vertically or collapsing the preview.

---

### Task 1: `PaneSession` & `PaneWorkspace` State Model with Argument Inheritance

**Files:**
- Modify: `modules/cli_tui/cli_tui/state.py`
- Test: `modules/cli_tui/tests/test_pane_state.py`

**Interfaces:**
- Consumes: `FormState`, `NavigationStack`, `TuiScreenMode` from `cli_tui.state`, `ProcessRunner`, `OutputViewport` from `cli_tui.process_runner`.
- Produces: `PaneType`, `PaneSession`, `PaneWorkspace`, `copy_matching_form_values(source, target)`.

- [ ] **Step 1: Write the failing tests for `PaneSession` and `PaneWorkspace`**

```python
# modules/cli_tui/tests/test_pane_state.py
import argparse
from cli_tui.schema import introspect_parser
from cli_tui.state import (
    FormState,
    NavigationStack,
    PaneSession,
    PaneType,
    PaneWorkspace,
    TuiScreenMode,
    copy_matching_form_values,
)

def test_pane_workspace_lifecycle():
    ws = PaneWorkspace()
    assert len(ws.panes) == 1
    assert ws.active_index == 0
    p1 = ws.active_pane
    assert p1.title == "Main"
    assert p1.pane_type == PaneType.COMMAND

    # Add second pane
    p2 = ws.create_pane(title="compress plan", pane_type=PaneType.COMMAND)
    assert len(ws.panes) == 2
    assert ws.active_index == 1
    assert ws.active_pane == p2

    # Cycling
    ws.cycle_prev()
    assert ws.active_index == 0
    ws.cycle_next()
    assert ws.active_index == 1

    # Deletion
    assert ws.delete_pane(1) is True
    assert len(ws.panes) == 1
    assert ws.active_index == 0

def test_copy_matching_form_values():
    p1 = argparse.ArgumentParser()
    p1.add_argument("-d", "--destination", default="default_dest")
    p1.add_argument("-w", "--workspace", default="./")
    p1.add_argument("-s", "--sample-size", type=int, default=10)
    cmd1 = introspect_parser(p1)
    form1 = FormState(cmd1)
    form1.set_value("destination", "custom_dest")
    form1.set_value("workspace", "/custom/work")
    form1.set_value("sample_size", 50)

    p2 = argparse.ArgumentParser()
    p2.add_argument("-d", "--destination", default="")
    p2.add_argument("-w", "--workspace", default="")
    p2.add_argument("-t", "--threads", type=int, default=4)
    cmd2 = introspect_parser(p2)
    form2 = FormState(cmd2)

    copied = copy_matching_form_values(form1, form2)
    assert copied == 2
    assert form2.get_value("destination") == "custom_dest"
    assert form2.get_value("workspace") == "/custom/work"
    assert form2.get_value("threads") == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest modules/cli_tui/tests/test_pane_state.py`
Expected: FAIL with `ImportError: cannot import name 'PaneSession'`

- [ ] **Step 3: Implement `PaneType`, `PaneSession`, `PaneWorkspace`, and `copy_matching_form_values` in `modules/cli_tui/cli_tui/state.py`**

Define `PaneType(Enum)`, `PaneSession` dataclass, and `PaneWorkspace` managing pane creation, switching, deletion, and parameter propagation.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest modules/cli_tui/tests/test_pane_state.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/cli_tui/cli_tui/state.py modules/cli_tui/tests/test_pane_state.py
git commit -m "feat(cli_tui): add PaneSession and PaneWorkspace state models with argument inheritance"
```

---

### Task 2: Top Tab Strip Rendering & Quick Navigation in `CliTuiApp`

**Files:**
- Modify: `modules/cli_tui/cli_tui/app.py`
- Test: `modules/cli_tui/tests/test_pane_tab_strip.py`

**Interfaces:**
- Consumes: `PaneWorkspace`, `PaneSession` from `cli_tui.state`.
- Produces: `render_tab_strip(width: int) -> str`, hotkey cycling (`[` / `]` and `Alt+Left` / `Alt+Right`).

- [ ] **Step 1: Write the failing tests for Tab Strip and cycling**

```python
# modules/cli_tui/tests/test_pane_tab_strip.py
import argparse
from cli_tui.app import CliTuiApp
from cli_tui.state import PaneType

def test_tab_strip_hidden_when_single_pane():
    p = argparse.ArgumentParser(prog="tool")
    app = CliTuiApp(parser=p)
    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    # Should not display tab strip indicators when only 1 pane exists
    assert "▶ [1:" not in screen

def test_tab_strip_shown_and_cycles_when_multiple_panes():
    p = argparse.ArgumentParser(prog="tool")
    app = CliTuiApp(parser=p)
    # Add second pane
    app.workspace.create_pane(title="compress plan", pane_type=PaneType.COMMAND)
    screen = "\n".join(app.render_virtual_screen(height=24, width=80))

    # Top line must render tabs
    assert "1:" in screen[0:100]
    assert "2: compress plan" in screen[0:100]
    assert "▶" in screen[0:100]

    # Cycle to previous pane with '['
    app.process_key(ord("["))
    assert app.workspace.active_index == 0

    # Cycle to next pane with ']'
    app.process_key(ord("]"))
    assert app.workspace.active_index == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest modules/cli_tui/tests/test_pane_tab_strip.py`
Expected: FAIL with `AttributeError: 'CliTuiApp' object has no attribute 'workspace'`

- [ ] **Step 3: Integrate `PaneWorkspace` into `CliTuiApp` in `modules/cli_tui/cli_tui/app.py`**

- Initialize `self.workspace = PaneWorkspace()` in `CliTuiApp.__init__`.
- Replace single-pane fields with active pane delegates (or synchronize active pane with app fields).
- Prepend tab strip line when `len(self.workspace.panes) > 1`.
- Handle `[` (ord('[')) and `]` (ord(']')) in `process_key()` to cycle panes.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest modules/cli_tui/tests/test_pane_tab_strip.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/cli_tui/cli_tui/app.py modules/cli_tui/tests/test_pane_tab_strip.py
git commit -m "feat(cli_tui): add top tab strip rendering and hotkey pane cycling"
```

---

### Task 3: `Shift+Esc` Branching, Context Inheritance & Preservation of Finished Panes

**Files:**
- Modify: `modules/cli_tui/cli_tui/app.py`
- Test: `modules/cli_tui/tests/test_pane_branching.py`

**Interfaces:**
- Consumes: `copy_matching_form_values` from `cli_tui.state`.
- Produces: `branch_to_new_command_pane()`, finished pane immutable policy.

- [ ] **Step 1: Write the failing tests for `Shift+Esc` branching and preservation**

```python
# modules/cli_tui/tests/test_pane_branching.py
import argparse
from cli_tui.app import CliTuiApp
from cli_tui.state import TuiScreenMode

def build_test_parser():
    p = argparse.ArgumentParser(prog="tool")
    sub = p.add_subparsers(dest="subcommand")
    cmd1 = sub.add_parser("inventory")
    cmd1.add_argument("-d", "--destination", default="")
    cmd2 = sub.add_parser("plan")
    cmd2.add_argument("-d", "--destination", default="")
    return p

def test_branching_preserves_run_and_inherits_args():
    app = CliTuiApp(parser=build_test_parser())
    # Enter inventory form
    app.process_key(10)
    assert app.screen_mode == TuiScreenMode.FORM
    assert app.current_form is not None
    app.current_form.set_value("destination", "hent1")

    # Start run (mocked)
    app.process_key(10) # Run
    assert app.screen_mode == TuiScreenMode.RUNNING

    # Press 's' (or Shift+Esc trigger) to branch
    app.process_key(ord("s"))
    assert len(app.workspace.panes) == 2
    # Old pane 0 is preserved in RUNNING mode with its output intact
    assert app.workspace.panes[0].screen_mode == TuiScreenMode.RUNNING
    # Active pane 1 is at MENU mode
    assert app.workspace.active_index == 1
    assert app.screen_mode == TuiScreenMode.MENU

    # Select 'plan' command in pane 1
    # Move down to 'plan' and enter
    app.process_key(curses.KEY_DOWN if hasattr(curses, "KEY_DOWN") else 258)
    app.process_key(10)
    assert app.screen_mode == TuiScreenMode.FORM
    # Argument 'destination' must be pre-filled with 'hent1'
    assert app.current_form.get_value("destination") == "hent1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest modules/cli_tui/tests/test_pane_branching.py`
Expected: FAIL with `AssertionError: assert len(app.workspace.panes) == 2`

- [ ] **Step 3: Implement `branch_to_new_command_pane()` and finished pane protection in `app.py`**

- When `s` or `Shift+Esc` is pressed while running or finished:
  - Freeze current pane in `PaneSession`.
  - Create new pane at `MENU` mode.
  - Store source form reference in workspace for matching argument inheritance.
- When entering a new form: call `copy_matching_form_values` from the parent pane's form.
- In `_handle_running_key()`: when runner is finished, `Esc` switches back to previous pane instead of resetting to FORM.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest modules/cli_tui/tests/test_pane_branching.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/cli_tui/cli_tui/app.py modules/cli_tui/tests/test_pane_branching.py
git commit -m "feat(cli_tui): implement Shift+Esc branching with argument inheritance and finished pane preservation"
```

---

### Task 4: Split Pane Manager (`p`) with Dual 30/70 Column Layout & Live Preview

**Files:**
- Modify: `modules/cli_tui/cli_tui/app.py`
- Test: `modules/cli_tui/tests/test_pane_manager_overlay.py`

**Interfaces:**
- Consumes: `OutputViewport`, `PaneSession` preview rendering.
- Produces: `render_pane_manager(height, width) -> List[str]`, management actions (`[Enter]`, `[d]`, `[D]`, `[Esc]`).

- [ ] **Step 1: Write the failing tests for the Pane Manager overlay**

```python
# modules/cli_tui/tests/test_pane_manager_overlay.py
import argparse
from cli_tui.app import CliTuiApp
from cli_tui.state import PaneType

def test_pane_manager_overlay_rendering_and_actions():
    p = argparse.ArgumentParser(prog="tool")
    app = CliTuiApp(parser=p)
    app.workspace.create_pane(title="compress inventory", pane_type=PaneType.COMMAND)
    app.workspace.panes[0].viewport.get_visible_lines = lambda lines, **kw: ["Sample Summary Table", "Files: 100"]

    # Press 'p' to open Pane Manager
    app.process_key(ord("p"))
    assert app.is_pane_manager_open is True

    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    # Must show dual column divider and titles
    assert "MangaDL Pane Manager" in screen or "Pane Manager" in screen
    assert "PANES" in screen
    assert "PREVIEW" in screen
    assert "[d] Delete" in screen

    # Close with Esc
    app.process_key(27) # Esc
    assert app.is_pane_manager_open is False

    # Reopen and delete pane
    app.process_key(ord("p"))
    app.process_key(ord("d"))
    # One pane remains
    assert len(app.workspace.panes) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest modules/cli_tui/tests/test_pane_manager_overlay.py`
Expected: FAIL with `AttributeError: 'CliTuiApp' object has no attribute 'is_pane_manager_open'`

- [ ] **Step 3: Implement `render_pane_manager` and manager navigation in `app.py`**

- Add `is_pane_manager_open` and `manager_cursor`.
- Implement `render_pane_manager()` formatting a 30% left list and 70% right live preview with border box characters.
- Add manager key handling: `↑`/`↓` navigates list, `Enter` switches active pane, `d` deletes highlighted pane, `D` deletes all panes, `Esc` dismisses.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest modules/cli_tui/tests/test_pane_manager_overlay.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/cli_tui/cli_tui/app.py modules/cli_tui/tests/test_pane_manager_overlay.py
git commit -m "feat(cli_tui): implement split pane manager overlay with live preview and pane lifecycle actions"
```

---

### Task 5: Interactive Console Shell Pane & New Pane Choice Dialog (`[n]`)

**Files:**
- Create: `modules/cli_tui/cli_tui/console_pane.py`
- Modify: `modules/cli_tui/cli_tui/app.py`, `modules/cli_tui/cli_tui/state.py`
- Test: `modules/cli_tui/tests/test_console_pane.py`

**Interfaces:**
- Consumes: `ProcessRunner`, `VirtualTerminalBuffer`, `OutputViewport`.
- Produces: `ConsolePaneRunner`, `cmd_choice_dialog` handling `[1] New Command`, `[2] Shell Console`.

- [ ] **Step 1: Write the failing tests for Console Pane and choice dialog**

```python
# modules/cli_tui/tests/test_console_pane.py
import argparse
from cli_tui.app import CliTuiApp
from cli_tui.console_pane import ConsolePaneRunner

def test_console_pane_runner_executes_command():
    runner = ConsolePaneRunner(cwd=".")
    assert runner.is_running is False
    # Execute simple echo command
    runner.execute_line("echo hello_console")
    runner.wait(timeout=3.0)
    lines = runner.lines
    assert any("hello_console" in line for line in lines)

def test_pane_manager_n_key_opens_choice_dialog():
    p = argparse.ArgumentParser(prog="tool")
    app = CliTuiApp(parser=p)
    app.process_key(ord("p")) # Open manager
    app.process_key(ord("n")) # Press 'n'

    # Must open choice dialog
    assert getattr(app, "is_showing_new_pane_choice", False) is True
    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    assert "New Command (Menu)" in screen
    assert "Interactive Shell Console" in screen

    # Select [2] for console pane
    app.process_key(ord("2"))
    assert app.workspace.active_pane.pane_type.value == "console"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest modules/cli_tui/tests/test_console_pane.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'cli_tui.console_pane'`

- [ ] **Step 3: Implement `ConsolePaneRunner` in `modules/cli_tui/cli_tui/console_pane.py` and choice dialog in `app.py`**

- `ConsolePaneRunner`: Runs commands line-by-line via `ProcessRunner` and `VirtualTerminalBuffer`, tracking current working directory and capturing output history.
- `app.py`: When `n` is pressed in Pane Manager, open the choice modal (`[1] Menu`, `[2] Console`). Selecting `2` creates a `PaneSession` of type `CONSOLE`.
- Handle text input for the console pane in `_curses_loop`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest modules/cli_tui/tests/test_console_pane.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/cli_tui/cli_tui/console_pane.py modules/cli_tui/cli_tui/app.py modules/cli_tui/tests/test_console_pane.py
git commit -m "feat(cli_tui): add interactive console pane and new pane choice dialog"
```

---

### Task 6: Full Integration Verification with MangaDL & Regression Test Suite

**Files:**
- Modify: `modules/cli_tui/tests/test_app.py`, `modules/mangadl/tests/tui_test.py`
- Test: Full `cli_tui` and `mangadl` pytest suites

- [ ] **Step 1: Run complete `cli_tui` test suite**

Run: `python -m pytest modules/cli_tui/tests/ -v`
Expected: All tests pass (including existing 34 tests + new pane tests).

- [ ] **Step 2: Run complete `mangadl` test suite**

Run: `python -m pytest modules/mangadl/tests/tui_test.py -v`
Expected: All 7 MangaDL TUI integration tests pass.

- [ ] **Step 3: Lint and format checks**

Run: `python -m ruff check modules/cli_tui/`
Run: `python -m ruff format --check modules/cli_tui/`
Expected: All checks pass clean with no warnings.

- [ ] **Step 4: Commit**

```bash
git add modules/cli_tui/ modules/mangadl/tests/tui_test.py
git commit -m "chore(cli_tui): finalize multi-pane integration and verify test suite"
```
