# Stage 1: Reusable CLI TUI Engine (`modules/cli_tui`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this stage task-by-task.

**Goal:** Create a standalone, reusable package `modules/cli_tui` that can inspect any `argparse.ArgumentParser`, generate interactive curses/termdash menus and forms for option selection, stream process output in real-time with scrollback, and handle universal navigation (`q`, `Q`, `Esc`).

---

### Task 1.1: Package Scaffolding & Argparse Introspection (`cli_tui.schema`)

**Files:**
- Create: `modules/cli_tui/pyproject.toml`
- Create: `modules/cli_tui/cli_tui/__init__.py`
- Create: `modules/cli_tui/cli_tui/schema.py`
- Test: `modules/cli_tui/tests/test_schema.py`

**Interfaces:**
- Produces:
  - `CliArgument`: data model representing an extracted CLI option (flags, dest, type, default, choices, required, help, action_type).
  - `CliCommand`: data model representing a command/subcommand with child arguments and subcommands.
  - `introspect_parser(parser: argparse.ArgumentParser) -> CliCommand`: recursive parser inspector.

**Steps:**
- [ ] **Step 1.1.1: Write failing test for parser introspection**
  Test extracting positional arguments, optional flags, choices, boolean flags (`BooleanOptionalAction`, `store_true`), and nested subparsers (`git -> remote -> add`).
- [ ] **Step 1.1.2: Run test to verify failure**
- [ ] **Step 1.1.3: Implement `cli_tui/schema.py`**
  Walk `parser._actions`, inspect `_SubParsersAction.choices`, extract metadata, ignore `argparse.SUPPRESS` options.
- [ ] **Step 1.1.4: Run test to verify pass**
- [ ] **Step 1.1.5: Commit Task 1.1**

---

### Task 1.2: TUI Navigation & Form State Models (`cli_tui.state`)

**Files:**
- Create: `modules/cli_tui/cli_tui/state.py`
- Test: `modules/cli_tui/tests/test_state.py`

**Interfaces:**
- Produces:
  - `TuiScreenMode`: Enum (`MENU`, `FORM`, `RUNNING`, `CONFIRM_QUIT`).
  - `NavigationStack`: Manages breadcrumb path and screen transitions (`push_screen`, `pop_screen`).
  - `FormState`: Stores modified argument values, tracks active field index, editing mode vs navigation mode, and builds the generated command line (`build_argv() -> list[str]`).

**Steps:**
- [ ] **Step 1.2.1: Write failing test for state navigation and argv synthesis**
  Verify `build_argv()` converts field values (e.g. `destination="path"`, `format="webp"`, `quality=[85, 70]`, `sort=True`) into exact CLI tokens.
- [ ] **Step 1.2.2: Run test to verify failure**
- [ ] **Step 1.2.3: Implement `cli_tui/state.py`**
- [ ] **Step 1.2.4: Run test to verify pass**
- [ ] **Step 1.2.5: Commit Task 1.2**

---

### Task 1.3: Form Field Widgets & Rendering (`cli_tui.widgets`)

**Files:**
- Create: `modules/cli_tui/cli_tui/widgets.py`
- Test: `modules/cli_tui/tests/test_widgets.py`

**Interfaces:**
- Produces:
  - `Widget`: Base widget protocol with `handle_key(key: int) -> bool` and `render(window, row, col, width, is_focused: bool)`.
  - `BooleanWidget`: `[X] / [ ]` toggled with Space / Enter.
  - `ChoiceWidget`: `< webp >` cycled with Left / Right or opened in selection dialog.
  - `TextWidget` / `PathWidget`: Text editing with cursor position, backspace, and path completion.
  - `MultiChoiceWidget`: Checkable list of values (e.g. qualities `85`, `70`).

**Steps:**
- [ ] **Step 1.3.1: Write failing test for widget key handling and value toggling**
- [ ] **Step 1.3.2: Run test to verify failure**
- [ ] **Step 1.3.3: Implement `cli_tui/widgets.py` using termdash color and rendering conventions**
- [ ] **Step 1.3.4: Run test to verify pass**
- [ ] **Step 1.3.5: Commit Task 1.3**

---

### Task 1.4: Real-time Streaming Process Runner (`cli_tui.process_runner`)

**Files:**
- Create: `modules/cli_tui/cli_tui/process_runner.py`
- Test: `modules/cli_tui/tests/test_process_runner.py`

**Interfaces:**
- Produces:
  - `ProcessRunner`: Spawns subprocess, reads stdout/stderr asynchronously into thread-safe deque buffer, exposes process status, exit code, elapsed duration, and cancellation (`terminate`, `kill`).
  - `OutputViewport`: Manages viewport scrolling offset, auto-scroll to bottom, scroll lock when user scrolls up, and ANSI line parsing.

**Steps:**
- [ ] **Step 1.4.1: Write failing test for process execution, streaming buffer, and cancellation**
- [ ] **Step 1.4.2: Run test to verify failure**
- [ ] **Step 1.4.3: Implement `cli_tui/process_runner.py`**
- [ ] **Step 1.4.4: Run test to verify pass**
- [ ] **Step 1.4.5: Commit Task 1.4**

---

### Task 1.5: Main Application Controller & Keybindings (`cli_tui.app`)

**Files:**
- Create: `modules/cli_tui/cli_tui/app.py`
- Test: `modules/cli_tui/tests/test_app.py`

**Interfaces:**
- Produces:
  - `CliTuiApp`: Main curses loop handling screen transitions, quit dialog, force quit, and back navigation.
  - Keybinding dispatch:
    - `q`: If in edit mode, inputs character; if in navigation mode, triggers `CONFIRM_QUIT` popup (`"Quit? (y/n)"`).
    - `Q`: Unconditional immediate exit across all screens.
    - `Esc`: If in edit mode, exits edit mode; if in form, returns to menu; if in running screen and finished, returns to form.

**Steps:**
- [ ] **Step 1.5.1: Write failing test for universal keybinding dispatch and dialog flows**
- [ ] **Step 1.5.2: Run test to verify failure**
- [ ] **Step 1.5.3: Implement `cli_tui/app.py`**
- [ ] **Step 1.5.4: Run test to verify pass**
- [ ] **Step 1.5.5: Commit Task 1.5**
