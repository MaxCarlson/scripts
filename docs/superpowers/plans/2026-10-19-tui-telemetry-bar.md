# Real-Time Hardware & Process Telemetry Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a real-time host (CPU, RAM, GPU) and active process hardware telemetry header in `cli_tui` backed by a reusable, lightweight background sampler in `modules/sysmon`.

**Architecture:** A thread-safe `HardwareSampler` in `modules/sysmon/sysmon/sampler.py` collects host metrics and tracks a target PID process tree asynchronously every ~500ms using `psutil` and rate-limited `_gpu_info_safe` queries. `cli_tui/app.py` soft-imports the sampler, rendering Full (Option A: 2-line), Compact (Option C: 1-line), or Hidden (0-line) headers above the tab bar, synchronizing target PID with the focused pane, and providing dynamic hotkey cycling via `t` and `Ctrl+H`.

**Tech Stack:** Python 3.10+, `curses` / `windows-curses`, `psutil`, `modules/sysmon`, `modules/cli_tui`.

**Spec:** [`docs/superpowers/specs/2026-10-19-tui-telemetry-bar-design.md`](file:///C:/Users/mcarls/src/scripts/docs/superpowers/specs/2026-10-19-tui-telemetry-bar-design.md)

---

## Global Constraints

- Platform: Windows 10/11, Linux, macOS.
- Language Floor: Python 3.10+.
- Zero new mandatory third-party runtime dependencies (`psutil` is already installed in the virtualenv; `cli_tui` must soft-import `sysmon`).
- Process CPU percentage is system-normalized (0.0%–100.0%) by dividing by `psutil.cpu_count(logical=True) or 1`.
- Host GPU queries are throttled to a minimum 1.5s interval to ensure negligible CPU overhead (<0.5%).
- Process-specific GPU stats degrade gracefully to `None` / `N/A` on platforms/drivers lacking per-process GPU accounting (such as Windows WDDM graphic mode).

---

## Review Focus

1. **Target process termination mid-sample**: Child process terminates while `proc.children(recursive=True)` or `cpu_percent` is executing (`psutil.NoSuchProcess` / `psutil.AccessDenied`). Handled cleanly without raising or terminating the sampler thread.
2. **Missing GPU / non-NVIDIA system**: System without an NVIDIA GPU or with unavailable `nvidia-smi` returns `gpu_load_pct = None` without delay or error, and TUI renders `GPU: N/A` cleanly.
3. **Narrow terminal widths (<80 columns)**: Telemetry lines must not wrap horizontally or overflow curses buffers; metrics must abbreviate gracefully (e.g. `SYS: C 28% M 44% G 42%`).
4. **Soft-import failure in standalone `cli_tui`**: When `sysmon` or `psutil` is missing, `cli_tui` launches normally, defaulting `telemetry_mode` to `HIDDEN` without crashing.
5. **Multi-pane navigation across mixed pane states**: User switches between running commands, idle forms, and shell consoles. Target PID updates accurately and displays `Active: [idle]` when no process is active.

---

### Task 1: Telemetry Data Models & Host Sampler in `modules/sysmon`

**Files:**
- Create: `modules/sysmon/sysmon/sampler.py`
- Modify: `modules/sysmon/sysmon/__init__.py:1-10`
- Test: `modules/sysmon/tests/test_sampler.py`

**Interfaces:**
- Produces:
  - `TelemetryDisplayMode(Enum)`: `FULL = "full"`, `COMPACT = "compact"`, `HIDDEN = "hidden"`
  - `SystemStats(cpu_pct, ram_used_bytes, ram_total_bytes, ram_pct, gpu_name, gpu_load_pct, gpu_mem_used_bytes, gpu_mem_total_bytes, gpu_temp_c)`
  - `ProcessStats(pid, name, cpu_pct, memory_rss_bytes, memory_pct, gpu_load_pct, gpu_mem_used_bytes, num_threads, num_children, is_active)`
  - `HardwareSampler(interval: float = 0.5)` with `start()`, `stop()`, `get_snapshots() -> Tuple[Optional[SystemStats], Optional[ProcessStats]]`

- [ ] **Step 1: Write failing tests for `HardwareSampler` host metrics and lifecycle**

In `modules/sysmon/tests/test_sampler.py`:
```python
import time
from sysmon.sampler import HardwareSampler, SystemStats, TelemetryDisplayMode

def test_sampler_lifecycle_and_system_metrics():
    sampler = HardwareSampler(interval=0.1)
    sampler.start()
    try:
        time.sleep(0.25)
        sys_stats, proc_stats = sampler.get_snapshots()
        assert isinstance(sys_stats, SystemStats)
        assert 0.0 <= sys_stats.cpu_pct <= 100.0
        assert sys_stats.ram_used_bytes > 0
        assert sys_stats.ram_total_bytes > 0
        assert 0.0 <= sys_stats.ram_pct <= 100.0
        assert proc_stats is None
    finally:
        sampler.stop()

def test_sampler_graceful_gpu_fallback(monkeypatch):
    import sysmon.sampler as sm
    monkeypatch.setattr(sm, "_gpu_info_safe", lambda: ([], "GPU query failed"))
    sampler = HardwareSampler(interval=0.1)
    sampler._sample_tick()
    sys_stats, _ = sampler.get_snapshots()
    assert sys_stats is not None
    assert sys_stats.gpu_load_pct is None
    assert sys_stats.gpu_mem_used_bytes is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest modules/sysmon/tests/test_sampler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sysmon.sampler'`

- [ ] **Step 3: Implement `TelemetryDisplayMode`, `SystemStats`, `ProcessStats`, and `HardwareSampler` in `modules/sysmon/sysmon/sampler.py`**

Implement background daemon thread loop calling `psutil.cpu_percent(interval=None)`, `psutil.virtual_memory()`, and `_gpu_info_safe` rate-limited to >=1.5s interval with thread-safe lock around snapshot writes. Export in `sysmon/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest modules/sysmon/tests/test_sampler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/sysmon/sysmon/sampler.py modules/sysmon/sysmon/__init__.py modules/sysmon/tests/test_sampler.py
git commit -m "feat(sysmon): implement HardwareSampler core and system telemetry models"
```

---

### Task 2: Process Tree Attribution & Normalization in `HardwareSampler`

**Files:**
- Modify: `modules/sysmon/sysmon/sampler.py`
- Test: `modules/sysmon/tests/test_sampler.py`

**Interfaces:**
- Consumes: `HardwareSampler`, `ProcessStats` from Task 1.
- Produces:
  - `HardwareSampler.set_target_pid(pid: Optional[int]) -> None`
  - Populated `ProcessStats` with normalized `cpu_pct` (0.0%–100.0%), aggregated RSS memory, and process state.

- [ ] **Step 1: Write failing tests for process tree attribution and exception handling**

In `modules/sysmon/tests/test_sampler.py`:
```python
import os
import sys
import subprocess
from sysmon.sampler import HardwareSampler, ProcessStats

def test_process_tree_attribution_and_normalization():
    # Spawn child python process executing sleep
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.0)"])
    sampler = HardwareSampler(interval=0.05)
    sampler.set_target_pid(proc.pid)
    try:
        sampler._sample_tick()
        _, proc_stats = sampler.get_snapshots()
        assert isinstance(proc_stats, ProcessStats)
        assert proc_stats.pid == proc.pid
        assert proc_stats.is_active is True
        assert 0.0 <= proc_stats.cpu_pct <= 100.0
        assert proc_stats.memory_rss_bytes > 0
    finally:
        proc.terminate()
        proc.wait()

def test_process_exit_and_nosuchprocess_handling():
    sampler = HardwareSampler(interval=0.05)
    # Set non-existent PID
    sampler.set_target_pid(9999999)
    sampler._sample_tick()
    _, proc_stats = sampler.get_snapshots()
    assert proc_stats is None or proc_stats.is_active is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest modules/sysmon/tests/test_sampler.py -k "test_process" -v`
Expected: FAIL (`set_target_pid` or process attribution not yet implemented)

- [ ] **Step 3: Implement `set_target_pid` and process tree sampling in `sampler.py`**

Implement process discovery via `psutil.Process(target_pid)` and `proc.children(recursive=True)`. Catch `psutil.NoSuchProcess` and `psutil.AccessDenied`. Compute sum of CPU deltas and divide by `psutil.cpu_count(logical=True) or 1`. Aggregate RSS memory.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest modules/sysmon/tests/test_sampler.py -v`
Expected: PASS (all tests pass)

- [ ] **Step 5: Commit**

```bash
git add modules/sysmon/sysmon/sampler.py modules/sysmon/tests/test_sampler.py
git commit -m "feat(sysmon): implement process tree resource attribution and CPU normalization"
```

---

### Task 3: TUI Integration: Header Rendering & Dynamic Viewport Height

**Files:**
- Modify: `modules/cli_tui/cli_tui/app.py`
- Test: `modules/cli_tui/tests/test_telemetry.py`

**Interfaces:**
- Consumes: `HardwareSampler`, `TelemetryDisplayMode`, `SystemStats`, `ProcessStats` from `sysmon.sampler`.
- Produces:
  - `CliTuiApp.telemetry_mode: TelemetryDisplayMode`
  - `CliTuiApp._format_telemetry_lines(width: int) -> List[str]`
  - Dynamic screen height rendering in `render_virtual_screen`.

- [ ] **Step 1: Write failing tests for telemetry header rendering in Full, Compact, and Hidden modes**

In `modules/cli_tui/tests/test_telemetry.py`:
```python
import argparse
from cli_tui.app import CliTuiApp
from sysmon.sampler import TelemetryDisplayMode, SystemStats, ProcessStats

def test_telemetry_header_rendering_modes():
    parser = argparse.ArgumentParser(prog="testapp")
    app = CliTuiApp(parser=parser)
    # Mock sample data
    mock_sys = SystemStats(cpu_pct=25.0, ram_used_bytes=8*1024**3, ram_total_bytes=16*1024**3, ram_pct=50.0, gpu_name="RTX", gpu_load_pct=30.0, gpu_mem_used_bytes=4*1024**3, gpu_mem_total_bytes=8*1024**3, gpu_temp_c=45.0)
    mock_proc = ProcessStats(pid=1234, name="worker", cpu_pct=15.0, memory_rss_bytes=1024**3, memory_pct=6.25, gpu_load_pct=None, gpu_mem_used_bytes=None, num_threads=4, num_children=0, is_active=True)
    app._last_sys_stats = mock_sys
    app._last_proc_stats = mock_proc

    # 1. Full Mode (Option A: 2 lines)
    app.telemetry_mode = TelemetryDisplayMode.FULL
    screen_full = app.render_virtual_screen(height=20, width=80)
    assert any("System: CPU 25%" in line and "RAM" in line for line in screen_full[:3])
    assert any("Active: CPU 15%" in line and "worker" in line for line in screen_full[:3])

    # 2. Compact Mode (Option C: 1 line)
    app.telemetry_mode = TelemetryDisplayMode.COMPACT
    screen_compact = app.render_virtual_screen(height=20, width=80)
    assert any("CPU: 25% (proc 15%)" in line for line in screen_compact[:2])

    # 3. Hidden Mode (0 lines)
    app.telemetry_mode = TelemetryDisplayMode.HIDDEN
    screen_hidden = app.render_virtual_screen(height=20, width=80)
    assert not any("System: CPU" in line or "CPU: 25%" in line for line in screen_hidden[:3])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest modules/cli_tui/tests/test_telemetry.py -v`
Expected: FAIL (`telemetry_mode` not an attribute of `CliTuiApp`)

- [ ] **Step 3: Implement telemetry header formatting and virtual screen integration in `modules/cli_tui/cli_tui/app.py`**

Add `self.telemetry_mode = TelemetryDisplayMode.FULL`. Implement `_format_telemetry_lines(width)` with responsive formatting for >=100, 80-99, and <80 column widths. Insert lines at top of `render_virtual_screen` and deduct used lines from content viewport budget.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest modules/cli_tui/tests/test_telemetry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/cli_tui/cli_tui/app.py modules/cli_tui/tests/test_telemetry.py
git commit -m "feat(cli_tui): integrate telemetry header rendering and responsive width formatting"
```

---

### Task 4: TUI Process Targeting, Multi-Pane Synchronization & Hotkey Cycling

**Files:**
- Modify: `modules/cli_tui/cli_tui/app.py`
- Test: `modules/cli_tui/tests/test_telemetry.py`

**Interfaces:**
- Consumes: `HardwareSampler.set_target_pid`, `TelemetryDisplayMode`.
- Produces:
  - Hotkey `t` and `Ctrl+H` cycling `FULL -> COMPACT -> HIDDEN -> FULL`.
  - Process targeting in `_start_execution` and multi-pane switching.
  - Hotkey bar badge updates.

- [ ] **Step 1: Write failing tests for hotkey cycling and multi-pane target PID synchronization**

In `modules/cli_tui/tests/test_telemetry.py`:
```python
import curses
from cli_tui.app import CliTuiApp
from sysmon.sampler import TelemetryDisplayMode

def test_telemetry_hotkey_cycling_and_footer():
    app = CliTuiApp(parser=argparse.ArgumentParser(prog="sample"))
    assert app.telemetry_mode == TelemetryDisplayMode.FULL
    assert "[t] Telemetry: Full" in " ".join(app._get_active_hotkey_badges())

    # Press 't' -> COMPACT
    app.process_key(ord("t"))
    assert app.telemetry_mode == TelemetryDisplayMode.COMPACT
    assert "[t] Telemetry: Compact" in " ".join(app._get_active_hotkey_badges())

    # Press 't' -> HIDDEN
    app.process_key(ord("t"))
    assert app.telemetry_mode == TelemetryDisplayMode.HIDDEN
    assert "[t] Telemetry: Off" in " ".join(app._get_active_hotkey_badges())

    # Press Ctrl+H (ASCII 8) -> FULL
    app.process_key(8)
    assert app.telemetry_mode == TelemetryDisplayMode.FULL

def test_multi_pane_telemetry_pid_synchronization(monkeypatch):
    app = CliTuiApp(parser=argparse.ArgumentParser(prog="sample"))
    # Create two panes
    p1 = app.pane_workspace.create_pane("pane 1")
    p2 = app.pane_workspace.create_pane("pane 2")
    # Simulate runner on pane 1
    class FakeRunner:
        def is_running(self): return True
        class proc: pid = 4321
    p1.runner = FakeRunner()
    
    app._switch_to_pane(p1.id)
    assert app.sampler._target_pid == 4321
    
    app._switch_to_pane(p2.id)
    assert app.sampler._target_pid is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest modules/cli_tui/tests/test_telemetry.py -k "cycling or synchronization" -v`
Expected: FAIL

- [ ] **Step 3: Implement hotkey handling and multi-pane sync in `app.py`**

Bind `ord("t")` in menu, form, and runner key handlers (when not editing text) and `8` / `curses.KEY_BACKSPACE` (`Ctrl+H`) globally. Update `_switch_to_pane`, `cycle_pane_prev`, `cycle_pane_next`, and `_start_execution` to update `self.sampler.set_target_pid`. Add `[t] Telemetry: ...` badge to `_get_active_hotkey_badges`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest modules/cli_tui/tests/test_telemetry.py -v`
Expected: PASS (all tests pass)

- [ ] **Step 5: Run full test suite across modules**

Run:
```powershell
.venv\Scripts\python.exe -m pytest modules/sysmon/tests/ -v
.venv\Scripts\python.exe -m pytest modules/cli_tui/tests/ -v
.venv\Scripts\python.exe -m pytest modules/mangadl/tests/tui_test.py -v
.venv\Scripts\python.exe -m ruff check modules/sysmon modules/cli_tui
.venv\Scripts\python.exe -m ruff format --check modules/sysmon modules/cli_tui
```
Expected: All suites PASS with 0 errors.

- [ ] **Step 6: Commit**

```bash
git add modules/cli_tui/cli_tui/app.py modules/cli_tui/tests/test_telemetry.py
git commit -m "feat(cli_tui): bind telemetry hotkeys and synchronize active pane PID targeting"
```
