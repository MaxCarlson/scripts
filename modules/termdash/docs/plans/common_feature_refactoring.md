### Core Architectural Gaps in TermDash

TermDash currently operates as an immediate-mode terminal rendering library providing UI primitives (`LiveBlock`, `Table`, `ProgressBar`, `InteractiveList`), but it lacks a stateful application layer. Across consumer modules (`compresser`, `agent_benchmark`, `mangadl`, `ytaedl`, `file_utils`), developers repeatedly reimplement identical operational scaffolding:

* Windowed rate calculation, rolling throughput smoothing, and time-to-completion (ETA) estimations.


* Refresh cadence throttling and frame rate clamping.


* Screen layout budgeting and dynamic row/column truncation based on terminal geometry.


* Multi-panel coordination (e.g., headline metrics over an active task table with a scrolling event tail).


* Terminal input polling (raw keyboard reads via platform-specific routines like Windows `msvcrt`).


* Fallback handling for headless/CI/non-TTY execution versus alternate screen buffers versus inline live rewriting.



Consolidating these patterns into TermDash requires moving from standalone rendering widgets to a modular monitor runtime.

---

### Features to Bring into TermDash

#### 1. Semantic Progress Engine (`ProgressTracker` & `MultiPhaseProgress`)

Every major consumer (`compresser`, `mangadl`, `agent_benchmark`) duplicates rate calculation, exponential moving averages, and ETA estimation. TermDash should decouple progress mathematics from progress rendering.

* **Core State Tracker**:
* Tracks completed units, total units, elapsed duration, windowed transfer rates (bytes/sec, items/sec), and time remaining.


* Configurable exponential moving average ($\alpha$ smoothing) to avoid jitter in fluctuating I/O tasks.
* Native indeterminate / spinner mode for phases where the total item count is undiscovered (e.g., initial directory inventory scans or remote HTTP scraping).




* **Phase Coordination**:
* A phase coordinator object managing sequential and hierarchical sub-tasks (e.g., *Phase 1: Scan $\to$ Phase 2: Estimate $\to$ Phase 3: Compress*).




* **Direct Widget Binding**:
* Allow `ProgressBar` to take a `ProgressTracker` instance directly, automatically populating percentage, filled cells, rate text, and ETA without manual formatting strings in client code.



```python
# Target API Pattern
tracker = ProgressTracker(
    total=1500, unit="files", smoothing=0.15, indeterminate=False
)
tracker.advance(10)
# Automatically yields: "[=====>    ] 45% | 120 files/s | ETA: 00:01:12"

```

---

#### 2. Composite Live Monitor (`LiveMonitor`)

`agent_benchmark` (`dashboard.py`), `ytaedl` (`archive_validator.py`), and `compresser` (`inventory_ui.py`, `ui.py`) all hand-assemble three recurring visual tiers:

1. **Headline / Metric Banner**: 2–4 key metrics (e.g., Elapsed, Completed, Active Workers, Peak Memory/VRAM).


2. **Active State Body**: A structured table or worker pool list.


3. **Recent Event Log**: A bounded FIFO ring buffer showing the last $N$ events or diagnostic messages.



TermDash should offer a cohesive `LiveMonitor` view model:

* **Slots Architecture**: Header metrics bar, body table/list, and rolling event log.
* **Thread-Safe Data Ingestion**:
* Methods `monitor.set_metric(key, value)`, `monitor.update_row(row_id, data)`, and `monitor.log_event(msg)`.


* **Built-in Redraw Throttling**: Clamps render loops to a user-defined refresh interval (e.g., 10 Hz) while allowing background worker threads to post state updates at arbitrary frequencies without terminal flicker.



---

#### 3. Responsive Layout Budgeting & Adaptive Density

Applications currently clip strings manually or experience visual corruption when the terminal window shrinks. TermDash's tables format cleanly, but the containing view lacks vertical budgeting.

* **Height-Bounded Render Engine**:
* Queries terminal lines via `os.get_terminal_size()`.
* Calculates static overhead (header borders, margins, prompt lines).
* Dynamically calculates row budgets for tables: `visible_rows = max(min_rows, term_lines - fixed_overhead - log_lines)`.




* **Priority-Based Section Degradation**:
* Priority 1 (Always Visible): Header status and summary progress bar.
* Priority 2: Active worker/task table (clamped to fit remaining lines).
* Priority 3: Event log stream (contracts to 3 lines, then collapses entirely if terminal height $< 18$).


* **Horizontal Field Prioritization**:
* Columns marked with priority tags (`HIGH`, `MEDIUM`, `LOW`). Low-priority columns drop automatically below 100 columns rather than wrapping and breaking row layouts.



---

#### 4. Interactive Navigation & Detail Inspector (`InteractiveMonitor`)

`ytaedl` implements custom worker selection to reveal worker-specific logs; `file_utils` provides pause, resume, and setting adjustments via a custom input loop. While TermDash has `InteractiveList`, it is separated from the live updating `LiveBlock` components.

* **Cross-Platform Asynchronous Keyboard Poller**:
* Unified non-blocking key reader (`msvcrt.kbhit()`/`getch()` on Windows, non-blocking `select()` on Unix/macOS).




* **Interactive Live Modes**:
* **Navigation**: Up/Down arrows to move selection across live worker/trial rows without stalling background worker threads.


* **Detail Drawer / Split Inspector**: Pressing `Enter` or `Space` expands a side or bottom pane containing the selected worker's real-time log buffer or extended task metadata.


* **Standard Action Hooks**: Built-in handling for `p` (pause/resume), `q` / `Ctrl+C` (graceful termination signal), and `/` (quick filter).



---

#### 5. Output Lifecycle & Terminal Modes

Consolidate conflicting display logic into an explicit terminal session mode:

| Mode | Use Case | Terminal Behavior |
| --- | --- | --- |
| **`InlineLive`** | Standard CLI pipelines (`compresser`, `agent_benchmark`)

 | Rewrites $N$ lines in place via ANSI cursor positioning; prints a persistent static summary on completion.

 |
| **`AppendHistoryWithFooter`** | Continuous long-running monitors (`file_growth_monitor`)

 | Logs scroll normally up terminal history, while a sticky live status bar stays anchored at the bottom line.

 |
| **`AltScreen`** | Full-screen worker inspection (`ytaedl`, full dashboards)

 | Enters terminal alternate buffer (`\033[?1049h`), captures entire terminal space, cleans up completely on exit. |
| **`Headless / Quiet`** | Redirection, CI, non-TTY, `--quiet` flags

 | Suppresses cursor escape codes, emits periodic plain text line logs (e.g., every 10% or 30s) or stays silent.

 |

---

### Consumer Module Integration Mapping

```
                                  +------------------------------------+
                                  |         TermDash Runtime           |
                                  |------------------------------------|
                                  | ProgressTracker | LayoutBudget     |
                                  | LiveMonitor     | KeyPoller        |
                                  +------------------------------------+
                                            /       |        \
        +----------------------------------+        |         +----------------------------------+
        |                                           |                                            |
        v                                           v                                            v
+-------------------------------+  +-------------------------------+  +-------------------------------+
|       agent_benchmark         |  |          compresser           |  |        ytaedl / mangadl       |
|-------------------------------|  |-------------------------------|  |-------------------------------|
| - Retires custom dashboard.py |  | - Eliminates ui.py duplicate  |  | - Replaces custom worker loop |
|   experiment state management |    rolling rates & ETA calc      |    and msvcrt key poller in      |
| - Native model row capping    |  | - Standardizes progress across|    archive_validator.py          |
| - Automatic quiet/plain mode  |    inventory, estimation, and    |  | - Unifies audit_console and   |
|   reporting via session mode  |    compression phases            |    repair_ui phase & rate loops  |
+-------------------------------+  +-------------------------------+  +-------------------------------+

```

---

### Verification and Implementation Checklist

1. **Phase 1: Progress & Telemetry Foundation**
* [ ] Implement `termdash.progress.ProgressTracker` supporting unit types (`bytes`, `items`), EMA rate smoothing, and indeterminate status.
* [ ] Implement `termdash.progress.MultiPhaseTracker` for pipeline workflows.
* [ ] Add unit tests verifying rate calculation consistency, zero-division safety, and time formatters.


2. **Phase 2: Terminal Session & Lifecycle**
* [ ] Implement `termdash.session.TerminalSession` encapsulating TTY detection, `NO_COLOR`, quiet switches, and cleanup signals (`SIGINT`, `SIGTERM`).
* [ ] Implement `InlineLive` renderer and `AppendHistoryWithFooter` renderer.
* [ ] Add tests simulating redirected `stdout` to verify clean fallback to periodic plain text logs.


3. **Phase 3: Responsive Bounded Layouts**
* [ ] Implement `termdash.layout.LayoutBudget` to allocate vertical lines across header, table body, and event buffer based on dynamic terminal dimensions.
* [ ] Add tests with simulated terminal sizes (80x24, 120x40, 60x15) verifying table row clamping and low-priority element collapse.


4. **Phase 4: Live Monitoring & Worker Inspection**
* [ ] Implement `termdash.monitor.LiveMonitor` connecting slots (metrics, tabular rows, rolling logs) to the auto-throttled render loop.
* [ ] Implement `termdash.input.KeyPoller` with cross-platform non-blocking key reads for row selection and log drawer expansion.
* [ ] Refactor `modules/compresser/compresser/inventory_ui.py` and `modules/agent_benchmark/agent_benchmark/dashboard.py` to consume the new primitives, validating lines-of-code reduction and functional parity.
