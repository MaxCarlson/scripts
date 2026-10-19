# Stage 2: MangaDL TUI Integration (`mangadl tui`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this stage task-by-task.

**Goal:** Integrate the reusable `cli_tui` module into `mangadl`, exposing `mangadl tui` and `mangadl --tui`, configuring tailored menu hierarchies for MangaDL operations (`run`, `compress`, `covers`, `repair`, `archive`), and integrating the real-time execution dashboard with MangaDL processes.

---

### Task 2.1: MangaDL Parser Exposure & CLI Wiring

**Files:**
- Modify: `modules/mangadl/mangadl/cli_core.py`
- Modify: `modules/mangadl/mangadl/cli.py`
- Test: `modules/mangadl/tests/cli_test.py`

**Interfaces:**
- Produces:
  - `mangadl tui` command definition in argparse subparsers.
  - `mangadl --tui` top-level argument flag.
  - Dispatching to `mangadl.tui.launch_tui()`.

**Steps:**
- [ ] **Step 2.1.1: Write failing test for `mangadl tui` and `--tui` argument parsing**
  Verify `build_parser().parse_args(["tui"])` sets operation to `"tui"`.
- [ ] **Step 2.1.2: Run test to verify failure**
- [ ] **Step 2.1.3: Add `tui` parser to `cli_core.py` and `cli.py`**
- [ ] **Step 2.1.4: Run test to verify pass**
- [ ] **Step 2.1.5: Commit Task 2.1**

---

### Task 2.2: MangaDL TUI Launcher & Menu Customization (`mangadl.tui`)

**Files:**
- Create: `modules/mangadl/mangadl/tui.py`
- Test: `modules/mangadl/tests/tui_test.py`

**Interfaces:**
- Produces:
  - `launch_tui(argv: Sequence[str] | None = None) -> int`: Launches `cli_tui.CliTuiApp` configured with MangaDL command tree.
  - Grouped categories:
    - 📥 Downloads (`run normal`, `run optimize`, `run benchmark`)
    - 🗜️ Compression (`compress estimate`, `compress preview`, `compress apply`, `compress inventory`, `compress compare`)
    - 🖼️ Covers & Kavita (`covers`)
    - 🛠️ Maintenance & Repair (`repair`, `destination-audit`)
    - 📊 History & Database (`archive`)
    - 🔍 Image Viewer (Direct shortcut to side-by-side preview comparator)

**Steps:**
- [ ] **Step 2.2.1: Write failing test for MangaDL TUI configuration and category grouping**
- [ ] **Step 2.2.2: Run test to verify failure**
- [ ] **Step 2.2.3: Implement `mangadl/tui.py`**
- [ ] **Step 2.2.4: Run test to verify pass**
- [ ] **Step 2.2.5: Commit Task 2.2**

---

### Task 2.3: Live Process Execution & Action Callbacks

**Files:**
- Modify: `modules/mangadl/mangadl/tui.py`
- Test: `modules/mangadl/tests/tui_test.py`

**Interfaces:**
- Produces:
  - Subprocess command assembly: Formats `python -m mangadl ...` command strings correctly.
  - Post-execution callbacks:
    - If a `compress preview` operation completes successfully, present prompt: `[ Press 'v' to View Previews ]`.
    - If a `compress estimate` operation completes, show key findings summary and next-step actions.

**Steps:**
- [ ] **Step 2.3.1: Write failing test for post-preview action trigger and command formatting**
- [ ] **Step 2.3.2: Run test to verify failure**
- [ ] **Step 2.3.3: Implement post-run callbacks in `mangadl/tui.py`**
- [ ] **Step 2.3.4: Run test to verify pass**
- [ ] **Step 2.3.5: Commit Task 2.3**
