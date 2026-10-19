# Real-Time Hardware & Process Telemetry Bar for CLI TUI

## 1. Intent & The Why

When running computation-heavy operations in `cli_tui`—such as parallel image transcoding, perceptual optimization trials, or batch directory scans—users need immediate visibility into resource consumption. Without inline telemetry, users must leave the TUI or juggle external tools (Task Manager, Resource Monitor, `nvidia-smi`) to check if the machine is CPU-bound, running low on memory, or utilizing the GPU.

Furthermore, host-wide stats alone do not clarify how much of that resource load is driven by the specific task versus background system activity.

This design introduces a **real-time hardware & process telemetry header** in `cli_tui` backed by a dedicated programmatic sampler module in `modules/sysmon`. The header displays host CPU, RAM, and GPU metrics alongside dedicated process-level metrics attributed directly to the active runner and its child worker processes, updated live every ~500ms with hotkey toggle support.

---

## 2. Goals, Non-Goals & Anti-Goals

### Goals
- **Host System Telemetry**: Live host metrics including total CPU %, RAM used/total GB with percentage, and GPU utilization % with VRAM used/total.
- **Process & Worker Attribution**: Process-specific metrics (CPU %, RSS memory, GPU utilization) tracked across the root process PID and all spawned child worker processes (e.g. multiprocessing workers or CLI codec helpers).
- **Smooth Background Polling (~0.5s)**: A non-blocking background daemon thread polling system and process metrics at ~500ms intervals without causing frame drops or cursor stutter in the curses UI.
- **Option A (Full 2-Line Header) as Default**:
  - Line 1: `System: CPU ... │ RAM ... │ GPU ...`
  - Line 2: `Active: CPU ... │ RAM ... │ GPU ... (PID ...)`
- **Option C (Compact 1-Line Header) & Hotkey Cycling**:
  - Compact mode: inline pairings `CPU: XX% (proc YY%) │ RAM: XX% (proc ZZ GB) │ GPU: XX% (proc YY%)`.
  - Hotkey `t` (and/or `Ctrl+H`) cycles dynamically between `Full (Option A)`, `Compact (Option C)`, and `Hidden (Off)`.
- **Reusable Core Module**: Clean programmatic architecture in `modules/sysmon` (`sysmon.sampler` / `sysmon.telemetry`) exporting pure dataclasses and an asynchronous sampler, decoupling telemetry collection from curses rendering and Rich CLI dependencies.
- **Graceful Hardware Degradation**: If an NVIDIA GPU is not present or `nvidia-smi` is unavailable, display `GPU: N/A` or gracefully omit the GPU column without error. If a process terminates, handle `psutil.NoSuchProcess` cleanly.

### Non-Goals
- Historical timeseries graph rendering (sparklines / ASCII graphs in the telemetry bar; that remains in full-screen `sysmon`).
- Per-core CPU breakdown or individual thread-level inspection in the header.
- Modifying OS-level process scheduling or thread priority from within the TUI.

### Anti-Goals
- Performing synchronous CLI calls (`nvidia-smi`) or blocking queries inside the curses draw loop.
- Measuring overhead that consumes substantial CPU/GPU itself (sampling must be negligible: <0.5% CPU overhead).

---

## 3. Constraints & Platform

- **Platform**: Windows 10/11 (PowerShell / Windows Terminal), Linux, macOS.
- **Runtime**: Python 3.10+ standard library.
- **Dependencies**: `psutil` (available in project virtualenv); zero new required third-party runtime dependencies.
- **Hardware Integration**: NVIDIA Management Library (NVML) or `nvidia-smi` CLI query for GPU metrics with caching/rate limiting.

---

## 4. Detailed Architecture & Design

### 4.1 Telemetry Data Models (`modules/sysmon/sysmon/telemetry.py`)

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class TelemetryDisplayMode(Enum):
    FULL = "full"        # Option A: 2 lines (System + Active Process)
    COMPACT = "compact"  # Option C: 1 line (inline pairings)
    HIDDEN = "hidden"    # 0 lines (reclaim maximum vertical space)

@dataclass(frozen=True)
class SystemStats:
    cpu_pct: float
    ram_used_bytes: int
    ram_total_bytes: int
    ram_pct: float
    gpu_name: Optional[str] = None
    gpu_load_pct: Optional[float] = None
    gpu_mem_used_bytes: Optional[int] = None
    gpu_mem_total_bytes: Optional[int] = None
    gpu_temp_c: Optional[float] = None

@dataclass(frozen=True)
class ProcessStats:
    pid: int
    name: str
    cpu_pct: float
    memory_rss_bytes: int
    memory_pct: float
    gpu_load_pct: Optional[float] = None
    gpu_mem_used_bytes: Optional[int] = None
    num_threads: int = 1
    num_children: int = 0
    is_active: bool = True
```

### 4.2 Background Telemetry Sampler (`modules/sysmon/sysmon/sampler.py`)

A thread-safe `HardwareSampler` manages asynchronous metric collection:

```python
class HardwareSampler:
    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self._target_pid: Optional[int] = None
        self._lock = threading.Lock()
        self._system_stats: Optional[SystemStats] = None
        self._process_stats: Optional[ProcessStats] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background sampling thread."""

    def stop(self) -> None:
        """Stop background sampling and join the thread."""

    def set_target_pid(self, pid: Optional[int]) -> None:
        """Set or clear the active process PID to track."""

    def get_snapshots(self) -> Tuple[Optional[SystemStats], Optional[ProcessStats]]:
        """Return the latest sampled system and process telemetry snapshots."""
```

#### Sampling Details
1. **CPU & RAM**: Uses `psutil.cpu_percent(interval=None)` and `psutil.virtual_memory()`.
2. **Process Tree Tracking**: When `target_pid` is set, constructs a `psutil.Process(target_pid)`. Recursively discovers children with `proc.children(recursive=True)`. Aggregates `cpu_percent(interval=None)` and `memory_info().rss` across parent and all surviving children.
3. **GPU Metrics**:
   - Host GPU: Queries GPU load, VRAM, and temperature via `_gpu_info_safe` (using `nvidia-smi` with a 1.0s minimum query cooldown to prevent subprocess flooding).
   - Process GPU: Matches the active PID tree against GPU compute/graphics processes reported by `nvidia-smi pmon -c 1` or compute-apps table.

---

### 4.3 TUI Integration (`modules/cli_tui/cli_tui/app.py`)

#### Lifecycle
- **App Startup**: Instantiates `HardwareSampler(interval=0.5)` and starts the sampling thread.
- **App Teardown**: Stops and joins the sampling thread on exit.
- **Command Launch**: In `_start_execution`, passes `self.runner.proc.pid` to `sampler.set_target_pid(pid)`.
- **Command Completion**: Retains the last process snapshot or marks it finished until a new command is selected.

#### Header Rendering
In `render_virtual_screen(height, width)`:
1. **Full Mode (Option A - 2 Lines)**:
   - Line 0 (System):
     `┌─ System: CPU 28.4% │ RAM 14.2 / 31.9 GB (44%) │ GPU 42% (6.1 / 24 GB) ────`
   - Line 1 (Process):
     `│  Active: CPU 24.1% │ RAM 3.84 GB (12%) │ GPU 40% (pid: 14820) ───────────`
   - Line 2: Pane Tab Strip or Top Frame Border.
2. **Compact Mode (Option C - 1 Line)**:
   - Line 0:
     `┌─ CPU: 28% (proc 24%) │ RAM: 44% (proc 3.8G) │ GPU: 42% (proc 40%) ────────`
   - Line 1: Pane Tab Strip or Top Frame Border.
3. **Hidden Mode (0 Lines)**:
   - Telemetry lines omitted; maximum vertical lines allocated to forms and terminal output.

### 4.4 Builder Decisions & Technical Settlements

1. **GPU Process Telemetry Feasibility on Windows (WDDM)**:
   - Host GPU metrics are polled via `_gpu_info_safe` throttled to a minimum 1.5s interval to ensure negligible CPU overhead.
   - Process-specific GPU utilization and memory under Windows WDDM degrade gracefully to `None` / `N/A` unless a CUDA compute context is actively reported by `nvidia-smi`. The TUI omits or shows `N/A` without blocking or requiring complex Win32 PDH / DirectX C-extensions.
2. **Multi-Pane Workspace Scoping**:
   - Telemetry tracks the **currently active/focused pane**.
   - Switching panes (`switch_pane`, `cycle_pane_prev`, `cycle_pane_next`) automatically updates `sampler.set_target_pid(active_pane.runner.pid if active_pane.runner and active_pane.runner.is_running() else None)`.
   - When viewing an idle pane (menu, form, finished runner, or idle shell), the active process line displays `Active: [idle]` or collapses.
3. **Process CPU % Normalization**:
   - `ProcessStats.cpu_pct` is **system-normalized** (0.0%–100.0%) by dividing the summed raw CPU time deltas across the process tree by `psutil.cpu_count(logical=True) or 1`.
   - This ensures direct visual consistency with `System: CPU` (e.g. `System: CPU 28% │ Active: CPU 24%`).
4. **Packaging & Dependency Contract (`cli_tui` -> `sysmon`)**:
   - `cli_tui` utilizes a soft/optional import for `sysmon.sampler`. If `sysmon` or `psutil` is unavailable in the environment, `cli_tui` gracefully disables telemetry and defaults to `HIDDEN` mode without raising import errors.
   - In the repository virtual environment, `sysmon` is already present with `psutil` installed.

### 4.5 Responsive Layout & Truncation

- **Wide Terminals (>= 100 cols)**:
  `┌─ System: CPU 28.4% │ RAM 14.2 / 31.9 GB (44%) │ GPU 42% (RTX 5090: 6.1 / 32.6 GB 35°C) ──`
- **Standard Terminals (80–99 cols)**:
  `┌─ System: CPU 28% │ RAM 14.2G (44%) │ GPU 42% (6.1G 35°C) ────────────────────`
- **Narrow Terminals (< 80 cols)**:
  Abbreviates metrics to `SYS: C 28% M 44% G 42%` and `APP: C 24% M 3.8G G 40%` to prevent horizontal line wrapping.

#### Dynamic Height Adjustment
`OutputViewport` and form scrolling dynamically adjust their available row budget based on `telemetry_mode` (Full uses 2 rows, Compact uses 1 row, Hidden uses 0 rows).

#### Hotkey Navigation & Footer
- Primary key: `t` (in menu, form, and runner views when not editing a text input).
- Global key: `Ctrl+H` (works everywhere, including active forms).
- Footer status badge: `[t] Telemetry: Full` / `[t] Telemetry: Compact` / `[t] Telemetry: Off`.

---

## 5. Verification & Testing Strategy

### 5.1 Unit Tests (`modules/sysmon/tests/`)
- `test_sampler_lifecycle`: Sampler starts, ticks in background, and stops cleanly without hanging.
- `test_system_stats_ranges`: System CPU % (0-100), RAM bytes (>0), RAM % (0-100) are valid.
- `test_process_tree_attribution`: Spawns a test subprocess that forks workers; verifies CPU and RAM sum across parent and child processes.
- `test_process_exit_handling`: Verifies sampler handles child process termination (`NoSuchProcess`) gracefully without unhandled exceptions.
- `test_gpu_fallback`: Mocks unavailable GPU / missing `nvidia-smi` and verifies `gpu_load_pct is None` without errors.

### 5.2 TUI Integration Tests (`modules/cli_tui/tests/`)
- `test_telemetry_rendering_full_and_compact`: Verifies virtual screen output in Full, Compact, and Hidden modes.
- `test_telemetry_hotkey_cycling`: Pressing `t` cycles `FULL -> COMPACT -> HIDDEN -> FULL` and adjusts header lines.
- `test_telemetry_viewport_budget`: Confirms viewport available height adjusts appropriately depending on active telemetry mode.
