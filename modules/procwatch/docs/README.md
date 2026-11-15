# ProcWatch Documentation

`procwatch` is a Windows 11 live console/terminal popup guard, event-driven process catcher, and causal diagnostic CLI.

## Architecture (Phase 1)

- `procwatch/guard/window_guard.py`: Focused WinEvent hook (`EVENT_SYSTEM_FOREGROUND`, `EVENT_OBJECT_CREATE..SHOW`, `DESTROY`) + `MsgWaitForMultipleObjects` loop + `NeutralizeEngine` suppression (`LockSetForegroundWindow`, `WS_EX_NOACTIVATE`, off-screen `SetWindowPos`, `SW_SHOWMINNOACTIVE`, `AttachThreadInput`) with `WindowBackend` abstraction.
- `procwatch/collectors/win_event.py`: Bridges `NeutralizeEngine` `RawWindowEvent`s to `WindowObservation` and bounded queues.
- `procwatch/collectors/wmi_trace.py`: COM-threaded `Win32_ProcessStartTrace` / `Win32_ProcessStopTrace` collector with clean `Ctrl+C` shutdown and `access_denied` degradation when unprivileged.
- `procwatch/correlator/ancestry.py`: `CreateToolhelp32Snapshot` + `psutil` process cache with PID-reuse handling, missing-parent transparency, and `.venv\Scripts\python.exe` shim collapsing.
- `procwatch/correlator/decoders.py`: Bounded, non-executing unwrapping of PowerShell `-EncodedCommand` (UTF-16LE), `cmd /c`, `powershell -Command`, and `wsl -e`.
- `procwatch/correlator/engine.py`: Joins window observations with candidate initiating processes.
- `procwatch/redactor.py`: Fail-closed pre-output secret scrubber.
- `procwatch/mutex.py`: Single-collector named mutex (`Local\ProcWatchCollectorMutex`) and owner heartbeat.
- `procwatch/cli.py` & `procwatch/renderers/console.py`: `procwatch watch` and `procwatch guard` CLI.

## Documentation Map

- `docs/HANDOFF.md`: Current module state, branch, verification, and next action.
- `docs/plans/HANDOFF.md`: Plan index and active phase pointer.
- `docs/plans/procwatch_plan/`: Copied Master Plan, Phase 1–4 specifications, and original research sources.
