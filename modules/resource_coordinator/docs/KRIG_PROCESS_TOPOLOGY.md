# Krig Process Topology and Windows Control Assessment

**Document type:** Process Topology Investigation Report  
**Target module:** `modules/resource_coordinator`  
**Target platform:** Windows 11 / RTX 5090  
**Miner:** Krig v1.5.6 (`krig-miner.exe`)  
**Investigation date:** 2026-10-19  

---

## 1. Executive Summary

A read-only investigation of the local environment (`C:\Users\mcarls\src\Mining`) and Windows system telemetry established the exact process topology, binary artifacts, invocation arguments, and process lifecycle boundaries for Krig PEARL mining.

Key findings:
1. **No active external supervisor:** There is no running Kryptex background service, Windows service, or Scheduled Task acting as an auto-relaunch supervisor.
2. **Binary and working directory:** Krig is a standalone 64-bit console executable located at `C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6\krig-miner.exe`.
3. **Execution modes:** Krig is launched either directly as a subprocess (`CREATE_NEW_PROCESS_GROUP`), or interactively via `mine-pearl.bat` (`cmd.exe` parent with a trailing `pause`).
4. **Shutdown mechanics:** Krig handles `CTRL_BREAK_EVENT` gracefully when attached to a dedicated process group (`CREATE_NEW_PROCESS_GROUP`). For externally launched instances without a shared console, `CTRL_BREAK_EVENT` cannot be delivered across process group boundaries via Win32 `GenerateConsoleCtrlEvent` without console attachment, making graceful external signal delivery unreliable without coordinator process group ownership.

---

## 2. Process Identification and Topology

### 2.1 Artifacts on Disk

| Attribute | Value |
|---|---|
| Executable Path | `C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6\krig-miner.exe` |
| Working Directory | `C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6` |
| Version | `1.5.6` (`krig-miner v1.5.6 — GPU miner`) |
| Batch Script | `C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6\mine-pearl.bat` |
| Target GPU | Index `0` (`01:00.0 NVIDIA GeForce RTX 5090`) |

### 2.2 Parent/Child Relationships

1. **Direct Coordinator / Runner Invocation (Recommended):**
   ```text
   Resource Coordinator (python.exe)
       └── krig-miner.exe (PID X, CREATE_NEW_PROCESS_GROUP)
   ```
   - Parent: Coordinator process.
   - Child: `krig-miner.exe` running directly.
   - Behavior: Clean stdout/stderr redirection, direct signal delivery (`CTRL_BREAK_EVENT`), accurate exit code capture.

2. **Interactive Batch File Invocation (`mine-pearl.bat`):**
   ```text
   Explorer / Terminal
       └── cmd.exe (mine-pearl.bat)
             └── krig-miner.exe
   ```
   - Parent: `cmd.exe`.
   - Child: `krig-miner.exe`.
   - Quirks: If `krig-miner.exe` is killed externally, `cmd.exe` remains alive waiting at the `pause` instruction.

3. **External Supervisor / Watchdog (Simulated/Future):**
   ```text
   Supervisor (Watchdog loop)
       └── krig-miner.exe
   ```
   - If an external watchdog is active, terminating `krig-miner.exe` causes the supervisor to immediately spawn a new PID.
   - Live inspection confirmed **no active watchdog or Kryptex daemon is currently running on the system**.

---

## 3. Control Mechanisms and Feasibility

| Control Method | Classification | Description & Limitations |
|---|---|---|
| **Coordinator Child Process (`CTRL_BREAK_EVENT`)** | **Verified (Safe)** | Coordinator launches `krig-miner.exe` with `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`. On pause, delivers `CTRL_BREAK_EVENT` via `proc.send_signal()`. Krig shuts down CUDA pipelines and flushes shares within 2-5 seconds. Fallback to `kill()` if timeout expires. |
| **External Adoption + PID Termination (`psutil.terminate()`)** | **Plausible with Caveats** | Can find PID by image name (`krig-miner.exe`). Calling Win32 `TerminateProcess` stops mining and frees VRAM immediately, but does not allow clean in-flight share flush. If launched via `mine-pearl.bat`, parent `cmd.exe` stays open at `pause`. |
| **Cross-Console `CTRL_BREAK_EVENT`** | **Unsupported on Windows** | Win32 `GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pid)` only delivers signals to processes in the *same* console session sharing the target process group ID. Attempting this against a foreign console fails or terminates the caller. |
| **Native HTTP API (`--api-port`)** | **Plausible (Read-Only)** | Krig exposes `--api-port <port> --api-host 127.0.0.1`. CLI help inspection confirms API exists for telemetry/stats, but does not expose a certified authenticated `/stop` or `/pause` RPC. |

---

## 4. GPU Resource Release Verification

When `krig-miner.exe` is stopped:
- CUDA context and memory allocations on device `0` (`RTX 5090`) are immediately reclaimed by the NVIDIA driver.
- Read-only test verification: Starting an inference request or polling GPU memory after Krig terminates shows full 32GB VRAM availability.
- Overclocking/Clock State: In `mining_optimizer`, Krig was run with `--gpu-no-reset-oc` to prevent miner exit from clobbering external GPU settings.

---

## 5. Prerequisites for Live Supervised Acceptance

1. **Explicit Launch Identity:**
   Coordinator configuration must point to the absolute executable path:
   `executable: "C:\\Users\\mcarls\\src\\Mining\\vendor\\krig-miner-1.5.6\\krig-miner.exe"`
   with working directory `C:\\Users\\mcarls\\src\\Mining\\vendor\\krig-miner-1.5.6`.
2. **No Secret Leaks:**
   Wallet addresses and pool credentials must be loaded via sanitized configuration or environment variables; never checked into repository Git tracking.
3. **Dedicated Process Group:**
   When launched by coordinator, `creationflags=CREATE_NEW_PROCESS_GROUP` (`new_console: true` or dedicated group) must be used.
4. **Adoption Policy:**
   If adopting a pre-existing miner PID, `allow_external_stop` must be explicitly enabled, and `allow_external_restart` requires valid launch parameters.
