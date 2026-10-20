# Supervised test environment preflight

Date: 2026-10-19
Reviewed coordinator: `e548941f7cea477decf571825769abc42e36e433` on `resource-coordinator-phase-d`
Result: **NO-GO for execution. No live test or process control was performed.**

This preflight applies the exact gates in [Phase D safety review](PHASE_D_SAFETY_REVIEW.md), [acceptance plan](SUPERVISED_LIVE_ACCEPTANCE_PLAN.md), and [emergency abort procedure](EMERGENCY_ABORT_PROCEDURE.md). The review's conditional recommendation is not execution authorization.

## Verified environment

- The reviewed worktree is `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-phase-d`, at the exact reviewed commit. The user's other `main` checkout has unrelated pre-existing changes and was not edited.
- Krig is **not running** in the observed process snapshots. `Get-Process` returned no names matching `krig|kryptex|mining|miner`; the NVIDIA process list likewise showed no Krig. Therefore there is no live Krig PID, parent, process identity, command line, working directory, group, or console to verify.
- A local binary exists at `C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6\krig-miner.exe`. File metadata reports file version `1.0.0.0`; product metadata starts `1.0.0+...`. The directory and launch script select it as Krig 1.5.6, but no miner version command was run. Static inspection of `start-prl.ps1` shows it changes working directory to the executable's containing directory, then invokes it with Pearl, Kryptex US SSL port 8048, and a username/worker argument. The saved account value was not copied here. That script's external launch is not coordinator ownership and does not prove an inherited-console process group.
- The read-only search found no matching Kryptex/Krig/miner Windows service, startup command, scheduled task action, or HKCU/HKLM Run entry. LM Studio does have a Run entry using `--run-as-service`; that supervises LM Studio startup, not Krig. These name/path searches cannot exclude an arbitrarily named wrapper, Kryptex UI setting, delayed task, or watchdog.
- LM Studio reports version `0.4.26+4`; the `lms` CLI says the server is running on port `1234`. TCP inspection reports listener `127.0.0.1:1234`, PID `40312`, image `C:\Program Files\LM Studio\LM Studio.exe`. No established connection to port 1234 appeared in the connection snapshot. Port 1235 had no listener. A later snapshot showed `127.0.0.1:4096` listening under PID `73276`, image `C:\Users\mcarls\AppData\Roaming\npm\node_modules\opencode-ai\bin\opencode.exe`; its endpoint configuration is unknown.
- `lms ps` reports loaded model `qwen38-27b-q4km`, identifier `qwen38_23GB`, status `IDLE`, size `16.81 GB`, context `32768`, parallel `4`. This is evidence of a resident model and the CLI's point-in-time idle label; it does not independently prove that no request is queued or in flight.
- `nvidia-smi` reports RTX 5090, 32,607 MiB total, 19,124 MiB used, 13,064 MiB free, 4% GPU utilization. WDDM reports per-process GPU memory as `N/A`; the compute process list includes `llama-server.exe` but no per-process allocation. Current free memory does not establish headroom for Qwen plus Krig, whose VRAM demand is not measured. No model was loaded/unloaded and no inference was sent.
- The current app/process inventory includes LM Studio, OpenCode, ChatGPT/Codex, Antigravity, Claude, Gemini, Firefox, Chrome, VS Code, and `llama-server.exe`. These are potential independent clients or launch paths only; their LM Studio endpoint settings were not inspected. OpenCode is actively listening on port 4096, but no established connection to 1234 or 1235 was present in the socket snapshot.

## Evidence commands

Read-only commands used (run from the `scripts` workspace unless noted):

```powershell
git worktree list --porcelain
git rev-parse resource-coordinator-phase-d
Get-CimInstance Win32_Process
Get-Process
Get-ScheduledTask
Get-CimInstance Win32_Service
Get-CimInstance Win32_StartupCommand
Get-ItemProperty HKCU:\Software\Microsoft\Windows\CurrentVersion\Run
Get-ItemProperty HKLM:\Software\Microsoft\Windows\CurrentVersion\Run
Get-NetTCPConnection -State Listen
Get-NetTCPConnection -State Established
netstat -ano
lms ps
lms server status
nvidia-smi
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
(Get-Item 'C:\Program Files\LM Studio\LM Studio.exe').VersionInfo
Get-ChildItem C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6 -Recurse -File -Filter *.exe
```

`lms server status` also emitted a home-path `EPERM` diagnostic before reporting the server running. The status and model observations are point-in-time snapshots. Standard process inventory does not expose working directory or console/process-group membership; no alternate process-inspection tool was used.

## Required gates and current state

| Gate | State | Evidence still needed |
| --- | --- | --- |
| Exact reviewed branch and safety config | Partial | Reviewed commit is pinned and the ignored draft has the required control flags, but its operator identity is a sentinel and exact launch arguments are not complete for execution. |
| Exact Krig launch identity and owned console group | Open | The binary path and static launcher arguments are known. A later authorized coordinator-owned launch must establish PID plus creation time, exact image/arguments, parent, working directory, session, group and shared-console behavior. Do not externally launch Krig to gather this. |
| No competing launcher/watchdog | Open | Operator must inspect Kryptex settings/UI, startup apps, all scheduled tasks/services, wrappers and any delayed relaunch policy. The current filtered searches do not prove absence. |
| Qwen loaded and idle | Partial | `lms ps` says resident and IDLE. Independently establish no queued/in-flight request and no unknown direct client. |
| Qwen plus miner GPU headroom | Open | Measure actual memory/compute demand under the separately approved miner configuration; current free VRAM is not enough evidence. |
| One client and protected path | Open | No listener on 1235 exists now, so there is no coordinator path to inspect. Apply and verify the isolation procedure below before a test. |
| Abort token and independent recovery | Open | Prepare private coordinator operator token and operator terminal; confirm out-of-band identities and operator availability before any authorized run. |
| Separate execution authorization | Not granted | Must explicitly authorize this one request, the exact launch, endpoint/model, stop conditions and operator intervention. |

## Proposed inactive configuration

The ignored private file `config.supervised.private.yaml` preserves the reviewed process-control choices: `new_console: false`; external stop/restart/adoption and force all false; 10-second stop timeout; 30-second cooldown; shared `gpu.inference`; only restart if stopped by this coordinator; loopback gateway `127.0.0.1:1235` to LM Studio `127.0.0.1:1234`. It uses the observed Krig executable and its containing directory, plus the pool and non-secret static arguments from the local launcher. The username/worker is deliberately an invalid sentinel and must not be used as-is. No operator token or account credential is stored in the file. State persistence and bounded drain are omitted because the reviewed implementation rejects them. The file has not been loaded, validated through the CLI, or activated.

No custom callbacks, model hooks, tool use, streaming, native API, standalone gateway, recovery, or second request belong in the first test. The test remains one non-streaming `/v1/chat/completions` request with normal `finish_reason=stop`, followed by the full configured cooldown and graceful coordinator shutdown.

If a later authorization is granted and all open gates are closed, the reviewed CLI flags are `--start-miner --stop-miner-on-shutdown`; the current draft invocation shape is `python -m resource_coordinator.cli serve --config config.supervised.private.yaml --start-miner --stop-miner-on-shutdown --drain-timeout 30`. This is recorded for review only and was not run. The configured drain value is not a guaranteed total wall-clock bound.

## Single-client isolation procedure for a separately authorized run

1. Close or suspend other local model clients and scripts, including the LM Studio interactive chat, coding assistants, browser integrations and any automation that may call localhost. Keep only the designated test client pointed to `http://127.0.0.1:1235`.
2. In LM Studio Server Settings, enable Require Authentication and create a dedicated API token with only the required inference permission. Store it outside source and shell history. LM Studio 0.4.26 meets the documented minimum for API-token authentication ([LM Studio authentication docs](https://lmstudio.ai/docs/developer/core/authentication)). Do not change that shared setting during this preflight.
3. Use a dedicated one-shot client for the single request. Confirm its configured base URL is port 1235. Keep the LM Studio UI from submitting chat while the server remains available.
4. Immediately before and during the test, record listeners and established sockets on ports 1234, 1235 and 4096 with `Get-NetTCPConnection`/`netstat -ano`, map each PID to executable and creation time, and review LM Studio server request logs. Require only the designated client-to-coordinator connection and coordinator-to-LM Studio upstream connection, correlated with the single request. Any direct client, unexplained socket, or uncorrelated request is NO-GO/abort. The current OpenCode listener must be explicitly excluded or selected as the one designated client; the present snapshot does not establish which.

The coordinator implementation currently has no configured upstream-token injection field. The isolated test client must therefore supply the LM Studio bearer token on its request through the coordinator, whose reviewed proxy preserves ordinary request headers; the same token must remain unavailable to other running clients. If the token appears in coordinator or client logs, stop and rotate it after the test. API authentication restricts callers to token holders, but does not itself prove that a token holder used port 1235; socket and request-log correlation is still required.

## Crash-abort and manual recovery

Before launch, have a second operator view or independent terminal with the exact service, miner and LM Studio process identities. Record PID, creation time, full executable path, parent, arguments with secrets redacted, session, console/group, and known descendants. Agree a human wall-clock response threshold, while recognizing it is an escalation trigger only: the coordinator has no guaranteed total shutdown bound, and synchronous OS calls or callbacks can stall its event loop.

If the coordinator is responsive, use the authenticated `resource-coordinator abort` procedure in `EMERGENCY_ABORT_PROCEDURE.md`; verify `reconciliation_required` and `is_ready=false`. This closes admission and restart eligibility for that process instance but does not stop Krig or cancel upstream inference.

If it hangs or crashes, treat the run as failed immediately. Stop the one-shot client and all other clients; do not restart the coordinator or clear/recover its latch. Use the operator's independent control of the identified Kryptex/UI, scheduled task, service, startup entry or wrapper to inhibit relaunch, and verify each control remains disabled. Independently identify every possibly forwarded request and wait for positive terminal evidence. Then identify Krig and all descendants by PID plus creation time and full path. Use a graceful control event only if the recorded dedicated group and shared console are positively verified. If that fails or cannot be proven, the operator must use the exact-process manual intervention path agreed before launch (for example, Process Explorer or Task Manager after matching PID, creation time and full image path); never kill by image name or an unverified/reused PID. Manual force termination is outside the coordinator's `allow_force_termination: false` setting and requires separate advance operator authority. Recheck that miner, descendants and watchdogs remain absent, and that LM Studio has no active request. If any identity or upstream state remains uncertain, keep the machine out of inference/mining use and escalate to the operator; do not restart either workload to probe it.

Manual recovery authority and console access are required in advance. A fixed timer cannot prove shutdown, and waiting the coordinator's configured 10 seconds is not a wall-clock bound. The test cannot proceed until the operator identifies the actual Kryptex watchdog/auto-relaunch mechanism (or documents why none exists), names the exact external intervention method, and confirms they can inhibit every relaunch source if the coordinator is gone.

## Handoff checklist for Sol Medium

- **NO-GO now:** Krig is stopped; no owned group, process identity or stop behavior has been live-verified; port 1235 has no listener; OpenCode is listening on 4096 with unknown LM Studio endpoint settings; no one-client condition is established; actual Qwen-plus-Krig headroom and watchdog absence are unproven.
- The Phase D code review gates are extracted above; current host state does not satisfy them all.
- The proposed configuration is local, ignored and inactive. It contains no credentials and cannot identify the operator's Kryptex account until a future authorized update.
- No test, inference, process signal, miner start/stop, model operation, LM Studio setting change, OpenCode/Kryptex change, or telemetry merge occurred.
- Before any future execution review, obtain the operator's watchdog inventory and manual intervention method; independently confirm Qwen queue state and headroom; establish single-client isolation; then obtain fresh, explicit user authorization for the exact one-request run.
