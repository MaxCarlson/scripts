# `procwatch`

Windows 11 live console/terminal popup guard, event-driven process catcher, and causal diagnostic CLI.

## Phase 1 Scope (Implemented)

- **Live Window Observer (`win_event.py`):** Event-driven `SetWinEventHook` + `MsgWaitForMultipleObjects` observer for `CREATE`, `SHOW`, `DESTROY`, and `FOREGROUND` window transitions with bounded callbacks and HWND-instance lifecycle tracking.
- **Targeted Window Guard (`window_guard.py`):** Preserves the `NeutralizeEngine` suppression sequence (`LockSetForegroundWindow`, `WS_EX_NOACTIVATE`, off-screen `SetWindowPos`, `SW_SHOWMINNOACTIVE`, `AttachThreadInput`) while fixing empty-title over-suppression, style/placement restoration, HWND reuse, and foreground-lock cleanup.
  - Modes: `observe` (safe default), `smart` (positive automation evidence only), `all-consoles` (opt-in broad console suppression), and `all-windows` (experimental/unsafe).
- **Event-Driven Process Watcher (`wmi_trace.py`):** COM-threaded `Win32_ProcessStartTrace` / `Win32_ProcessStopTrace` collector with bounded queue, clean `Ctrl+C` shutdown, and explicit `access_denied` degradation when run unprivileged.
- **Process Ancestry & Payload Decoders (`ancestry.py`, `decoders.py`, `redactor.py`):** `CreateToolhelp32Snapshot` + `psutil` seeded cache keyed by durable process identity (handling PID reuse and fast-exiting parents), safe UTF-16LE PowerShell `-EncodedCommand` / `cmd /c` / `wsl -e` unwrapping, and pre-output secret redaction.
- **Live CLI (`cli.py`):** `procwatch watch` and `procwatch guard` (consistent with `python -m procwatch`).

## Planned Future Phases

- **Phase 2:** Persistent SQLite WAL flight recorder, Sysmon & Task Scheduler Event Log ingestion, Git/worktree & agent context, `history`, `explain`, `mark`, `doctor`.
- **Phase 3:** Static AST/PowerShell scanner, Scheduled Task/Startup auditor, periodicity analyzer (`scan`, `audit`, `analyze`).
- **Phase 4:** Supervised headless Job Object runner (`exec`).

## Usage

```powershell
# Observe console/terminal windows and process events (read-only default)
procwatch watch

# Observe popups only, with smart guard enabled and redacted JSONL output
procwatch watch -p -g -m smart -o .\popups.jsonl

# Run dedicated guard in observe mode (safe default)
procwatch guard

# Run dedicated guard in smart mode
procwatch guard -m smart
```
