# DLManager Project Overview and Development Guide

## Purpose

**DLManager** is a Python module designed to provide a unified, extensible interface for managing file transfers across **multiple transfer mechanisms** (e.g., `rsync`, `rclone`, `scp`, `Google Drive`, local file copies, etc.).  
It functions both as a **transfer orchestrator** and an **interactive TUI** that allows users to monitor, pause, and manage transfers in real time.

The goal is to create a robust, fault-tolerant “Transfer Manager” that abstracts away the details of various copy/upload methods, automatically selecting the best option and retrying lower-priority methods if earlier ones fail.

---

## High-Level Architecture

### Core Components

- **`dlmanager.py`** – Central process managing active and historical transfers.
  - Handles spawning and supervising worker processes.
  - Receives structured JSON status updates from workers.
  - Maintains an in-memory and persistent record of all transfers (active, paused, completed, failed).
  - Provides both a **CLI interface** and an **interactive TUI** via `TermDash`.

- **Worker scripts (e.g., `rsync_dler.py`, `rclone_dler.py`, `scp_dler.py`)**
  - Each worker is a subprocess responsible for a single transfer.
  - They parse program-specific output (like verbose `rsync` logs) into structured JSON messages.
  - Output format is standardized:
    ```json
    {
        "bytes_dl": 123456789,
        "total_bytes": 456789000,
        "bytes_per_s": 1234567,
        "current_filename": "/path/to/file",
        "cur_file_bytes_dl": 98765,
        "cur_file_total_bytes": 123456,
        "file_number": 3,
        "total_file_count": 20
    }
    ```
  - JSON messages are streamed to stdout for `dlmanager` to consume.
  - Each worker writes detailed logs to its own log file (`~/.dlmanager/logs/<transfer_id>.log`).

- **`TermDash` Integration**
  - The TUI (via the `termdash` module) dedicates a line or small block to each active transfer.
  - Displays dynamic stats: filename, speed, percentage, ETA, bytes transferred.
  - Allows navigation, filtering, pausing/resuming/stopping/retrying transfers interactively.

- **Cross-Platform Integration**
  - Uses `cross_platform` utilities for OS and path normalization.
  - Auto-detects whether the target is Windows (via Cygwin path syntax) or a POSIX system.
  - Correctly formats paths for remote destinations (`user@ip:/path`) and local operations.

---

## Key Features (Planned and Existing)

| Feature | Description | Status |
|----------|--------------|--------|
| **Automatic transfer method selection** | Attempts best available protocol in order of efficiency: `rsync` → `rclone` → `scp` → fallback copy. | Planned |
| **Worker process orchestration** | Manager spawns one process per transfer, manages lifecycle. | Implemented (core structure present) |
| **Structured JSON worker output** | Workers report detailed stats in JSON for TUI consumption. | Implemented in prototype |
| **Interactive TUI** | Real-time progress display for all active transfers. | Partially implemented via TermDash |
| **Transfer queue/history** | Maintains a record of completed and failed transfers, viewable in UI. | Planned |
| **Pause/resume/retry** | User can pause or resume active transfers or retry failed ones. | Planned |
| **Logging per transfer** | Each worker writes to its own log file. | Implemented |
| **Cross-platform compatibility** | Handles path and syntax differences between Termux, Linux, Windows (Cygwin), etc. | Partially implemented via `cross_platform` |
| **CLI interface** | Allows adding, listing, and removing transfers from command line. | Implemented (basic) |
| **TUI auto-launch** | If `dlmanager` is invoked without arguments, launches TUI. | Planned |
| **Persistent history** | Stores previous transfers (JSON or SQLite). | Planned |
| **Parallelism** | Multiple simultaneous transfers, each in its own process. | Implemented |

---

## CLI Behavior

### Usage

```bash
dlmanager [command] [options]
```

### Commands

| Command | Description |
|----------|--------------|
| `add` | Add a new transfer job. |
| `list` | Show active and historical transfers. |
| `pause <id>` | Pause a transfer. |
| `resume <id>` | Resume a paused transfer. |
| `cancel <id>` | Cancel and remove a transfer. |
| `tui` | Launch the full-screen TUI manager. |

### Example

```bash
dlmanager add --source ~/Videos --dest user@192.168.1.2:/mnt/data --replace --method auto
```

Automatic mode:
1. Tries `rsync`.
2. If that fails, tries `rclone`.
3. Falls back to `scp`.

---

## Worker Design (Example: `rsync_dler.py`)

- Launches `rsync` with maximum verbosity (`-avz --progress`).
- Parses stdout line by line to extract:
  - Bytes transferred
  - Speed
  - Current file
  - Percentage
- Outputs structured JSON updates to stdout for ingestion by `dlmanager`.
- Writes detailed logs under `~/.dlmanager/logs/rsync_<timestamp>.log`.

---

## Manager <-> Worker Communication Protocol

- **Transport:** Workers write structured JSON to stdout.
- **Manager ingestion:**  
  `dlmanager` reads each line from the subprocess’s stdout and parses it as JSON.
- **Internal state:**  
  Manager updates its in-memory record for that transfer ID and pushes updates to the TUI.
- **Thread safety:**  
  Uses `asyncio` queues or multiprocessing-safe IPC.

---

## TUI/GUI Behavior

- **Default launch mode:**  
  If `dlmanager` is launched with no active transfers and no CLI arguments, the TermDash-based UI starts.
- **Displays:**  
  - List of active transfers (each line updates live)
  - Transfer speed, ETA, total progress bar
  - Total bandwidth usage
  - Option to pause/resume/stop
  - Navigation keys to select a transfer and view details/logs
- **Keyboard shortcuts (planned):**
  - `a` – Add new transfer
  - `p` – Pause
  - `r` – Resume
  - `s` – Stop
  - `h` – View history
  - `l` – View logs
  - `q` – Quit

---

## Transfer History

- Each completed transfer is recorded with:
  - `transfer_id`
  - start/end timestamps
  - total bytes transferred
  - average speed
  - success/failure flag
  - method used
- Stored either in:
  - JSON file: `~/.dlmanager/history.json`, or
  - SQLite DB: `~/.dlmanager/history.db`
- Accessible in TUI under “History” menu.

---

## Error Handling & Recovery

- Workers report failure as JSON:
  ```json
  {"status": "error", "message": "rsync failed with code 23"}
  ```
- Manager automatically retries with next available method if in `--auto` mode.
- Failed transfers appear in UI under “Failed Jobs”.

---

## Possible Issues / Challenges

| Category | Concern | Possible Solution |
|-----------|----------|-------------------|
| **Concurrent UI updates** | Many workers updating stats concurrently could cause flicker. | Use `TermDash`’s async-safe drawing routines. |
| **Cross-device IPC** | CLI-initiated transfers must connect to already-running manager. | Unix socket or file-based queue (e.g., `~/.dlmanager/socket`). |
| **Parsing reliability** | Different rsync/rclone/scp versions have varied output formats. | Implement robust regex-based parsers per tool. |
| **Platform differences** | Windows (Cygwin) vs Termux path styles. | Centralize path translation via `cross_platform` utils. |
| **Resumable transfers** | Rsync supports this natively, but others don’t. | Implement partial checkpoint support only for rsync/rclone. |

---

## Next Development Steps for the LLMCLI

1. **Review current implementation** of `dlmanager.py` and existing worker scripts.
2. **Audit modules**: verify imports from `cross_platform`, `termdash`, and logging utilities.
3. **Implement persistent job tracking** (`~/.dlmanager/history.json` or SQLite).
4. **Implement TUI interactivity** (keyboard-driven controls via `TermDash`).
5. **Design & implement IPC layer** for adding transfers to a running manager instance.
6. **Add structured retry logic** for `--method auto` mode.
7. **Finalize JSON schemas** for worker → manager communication.
8. **Extend `cross_platform`** to handle path translation for rsync→Windows transfers.
9. **Enhance test coverage**:
   - Spawn simulated transfers with dummy outputs.
   - Validate manager parsing and TUI updates.
10. **Document CLI API** (help text, examples, aliases).

---

## Summary

This project aims to become a **universal, intelligent transfer orchestrator** — managing multiple concurrent data transfers across devices, automatically picking the best method, and providing an interactive TUI for complete visibility and control.

After ingesting this file and the current codebase, the LLMCLI should:
- Recognize the multi-process architecture and JSON IPC protocol.
- Continue implementation toward full TUI interactivity and transfer persistence.
- Use the same structured design conventions as `ytaedl`.
- Leverage existing modules (`cross_platform`, `termdash`) as building blocks.

---

**End of File: `docs/DLManager_Overview.md`**
