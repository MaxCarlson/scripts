# H4 Windows Qualification — Read-Only Status

## Scope and safety

This record captures the authorized source merge and the initial, read-only H4 host inventory. No RC package was installed or upgraded; no service or Scheduled Task was changed or restarted; no miner, LM Studio backend, or WSL instance was started, stopped, or controlled; no GPU setting or credential was changed. A localhost status request was attempted as a read-only GET but the execution sandbox denied socket access before a response was received.

Observation context: Windows PowerShell, effective account `XERES\mcarls`; timestamps are local Pacific time on 2026-11-12. This is a bounded observation snapshot, not a claim about current state after that timestamp.

## Source baseline

- Parts 2–3 fast-forward merged and pushed to `main`: `0f983428c2a5e0ae02517f94dec6a38b1a4cec4b`.
- The merge was a fast-forward from `b45f3950595bec5c9af4b076ea8b2db93711eba0`; the review candidate was its ancestor and 16 commits ahead, 0 behind before merge.
- Local `HEAD`, local `main`, and fetched `origin/main` were verified at the merged SHA. No Part 2/3 source changes were made during this H4 check.
- RC source package reports `1.0.0`; source import resolved within this repository. `rc`, `resource-coordinator`, and `gpu-coordinator` entry points target `resource_coordinator.cli:main` in project metadata.
- Post-merge focused source regression: **14 passed, exit 0**. The selection covered Part 2 CLI, automatic-recovery authentication routing, recovery synchronization-marker failure handling, cancellation after durable commit, and exact-holder recovery. Compilation, source provenance, entry-point metadata and scoped diff checks passed.
- Existing evidence preserved: Part 3 broad module suite **849 passed, 7 skipped, 3 deselected, 0 failed**; final review selection **65 passed**; combined Mining/RC H3 **8 passed**. These were not repeated because source/tests are byte-identical to the H3-tested RC implementation. The seven skips are opt-in Windows/Scheduled Task tests; three deselections include two live host tests and the timing-sensitive acceptance test. See `../20261111-part2-part3-review/STATUS.md` for provenance.
- V3 remains unchanged: SHA-256 `BA842936C9DE945EE8463FD41C3E60491A5714DCA1CF481064DC915DBF516F46`; Git blob `3a1c2f7662a54469bb6dc15ad6462a4295ec93e6`.

## Host observations

Snapshot collection was performed at approximately `2026-11-12 00:52–00:59 -08:00`.

| Area | Status | Evidence and limits |
|---|---|---|
| Installed RC distribution in development environment | Observed, not production | The shared repository development `.venv` contains `resource-coordinator 0.6.0` at `scripts/.venv/Lib/site-packages`. Its `direct_url.json` points to a prior Part 2 worktree's temporary restore-test source. This is a development environment only and does not identify the production installation. The merged source tree is `1.0.0`; no installation was attempted. |
| RC runtime/process identity | Unverified | A narrow `Get-Process` scan for Coordinator/miner/LM Studio executable names returned no matches (exit 0). The filtered `psutil` scan likewise found no matching process or inaccessible matching process. `Get-CimInstance Win32_Process` failed with `CimException: Access to a CIM resource was not available to the client`. A GET to `http://127.0.0.1:1235/_coordinator/status` failed before connection with sandbox socket permission denial. Thus no installed-versus-running identity or service readiness is established. |
| Listener/port 1235 | Unavailable | `Get-NetTCPConnection` failed with `MethodInvocationException`; localhost status GET was blocked by execution sandbox socket permissions. No conclusion that the port is free or the service is stopped is warranted. |
| Windows service inventory | Incomplete | `Get-CimInstance Win32_Service` returned no matching RC/KRig service in the available query, but CIM service/process discovery is access-limited. `sc.exe query Schedule` exited 5 with `OpenService FAILED 5: Access is denied`. This does not establish Scheduler service state or task identity. |
| Scheduled Tasks and launch ownership | Unverified | `Get-ScheduledTask` failed because access to a CIM resource was unavailable. `schtasks.exe /query /fo CSV /v` exited 1 with `ERROR: The network address is invalid.` No task was created, run, repaired, disabled, or changed. Duplicate launch paths and task arguments/ACLs remain unknown. |
| Process ownership/descendants | Partial | Narrow name/module scans found no matching RC, KRig/SRBMiner, or LM Studio process at observation time. Full CIM process/parent/descendant inspection was denied. The narrow scan does not prove there is no differently named launcher or inaccessible process. No command lines were retained. |
| Windows identity/build | Observed | PowerShell reported `XERES\mcarls`; `[Environment]::OSVersion.VersionString` returned `Microsoft Windows NT 10.0.26300.0`. This is the runtime API version string, not a complete Windows edition/build qualification. |
| RTX 5090 identity and power | Read-only observed | `nvidia-smi` 621.14 / NVML 621.14 reported `NVIDIA GeForce RTX 5090`, UUID `GPU-d573e046-ec53-77d8-009b-93c6e6bc60b6`, PCI `00000000:01:00.0`, driver/KMD `621.14`, and `power.limit=550.00 W`. These establish that this query path returned values at that time; they do not qualify the RC verifier's native API, restoration tolerance, or repeatability. |
| Clock readback | Incomplete | Read-only query returned current graphics clock `2385 MHz` and memory clock `7001 MHz`. `nvidia-smi --help-query-gpu` lists current clocks and power-limit fields, but the targeted help search exposed no graphics/memory offset readback field. Current operating clocks are not offsets or a saved baseline. The shared development Python environment has no `pynvml`/`nvidia-ml-py` binding. Offset restoration readback is therefore not qualified. |
| GPU process attribution | Unverified | `nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader` exited 0 with zero output rows. This is not evidence of complete WDDM attribution and does not prove there are no GPU-using processes. Do not enable `gpu_process_attribution_confirmed`. |
| LM Studio | Partial | Installed-app registry query returned LM Studio `0.4.28+2`; `lms.exe` file metadata reported `1.3.3`. The narrow process scan found no LM Studio process. Runtime host, daemon state, no-wake semantics, model/queue semantics, direct clients, and Windows/WSL duplication remain unknown. `lms ps` and WSL commands were not run. |

## Read-only commands and outcomes

Commands were bounded and did not invoke setters or process control:

- `nvidia-smi.exe --version` — exit 0; NVIDIA-SMI/NVML `621.14`, KMD `621.14`.
- `nvidia-smi.exe --query-gpu=name,uuid,pci.bus_id,driver_version,power.limit --format=csv,noheader` — exit 0; one RTX 5090 row as recorded above.
- `nvidia-smi.exe --query-gpu=clocks.gr,clocks.mem --format=csv,noheader` — exit 0; current clocks only.
- `nvidia-smi.exe --help-query-gpu` with a bounded clock/offset field filter — returned current clock and power fields; no offset readback field was found in the filtered output.
- `nvidia-smi.exe --query-compute-apps=pid,process_name,used_memory --format=csv,noheader` — exit 0, zero output rows.
- Development venv Python `importlib.metadata` query — exit 0; development distribution `0.6.0`, location and temporary test-source URL above; `pynvml` not installed.
- `Get-Process` narrow name query and filtered `psutil` query — exit 0, no matching processes.
- `Get-CimInstance Win32_Process` — denied; `Get-NetTCPConnection` — failed; `Get-ScheduledTask` — denied; `schtasks.exe /query /fo CSV /v` — exit 1; `sc.exe query Schedule` — exit 5.
- `Invoke-WebRequest http://127.0.0.1:1235/_coordinator/status -Method Get -TimeoutSec 3` — failed at socket access with permission denial; no HTTP status or payload received.

Raw command-line arguments, task credentials, bearer tokens, and environment secret values were not collected or written to this record.

## Readiness disposition

### Source-verified

The merged v1.0.0 source, maintenance/restoration protocol, Part 2/3 recovery behavior, H3 simulated Mining compatibility, and focused recovery synchronization regressions are supported by the recorded offline evidence. This does not imply the installed service runs this source.

### Read-only host-verified

The current read-only `nvidia-smi` query path reports RTX 5090 identity, PCI address, driver/NVML version, power limit, and instantaneous clock values. LM Studio installation metadata is visible. These observations are point-in-time only.

### Blocked or still unknown

Installed/running RC identity; task definitions, ACLs and account; service state; full process ancestry and duplicate launchers; direct-client routing; NVML offset getters; WDDM attribution completeness; LM Studio runtime/no-wake semantics; mining launcher configuration; actual restore and cooldown behavior.

### Disposable Windows acceptance required

Use a disposable VM/host for `WinError 206` upgrade reproduction, task install/replace/start/relaunch, elevated helper and ACL checks, interrupted upgrade rollback, source identity, single-instance ownership, process descendants, and journal migration/rollback. No such mutation was attempted here.

### Controlled live acceptance required

A separately authorized, bounded H5 run is still required for actual RC/KRig ownership, RTX 5090 restoration/readback, inference/miner arbitration, LM Studio/WSL identity and no-wake behavior, and Mining acquisition → registered trial → restoration → release → cooldown. No live workload was run.

### Unattended recovery

Keep disabled. In particular, H4 has not qualified complete Windows/WDDM execution-boundary observation or Case C termination evidence. Existing source-level fail-closed behavior and simulated tests do not authorize host automation.

## Next gate

The follow-up below established the installed-versus-running mismatch and read-only NVML getter capability. Next, use an independently identified, separately authorized disposable Windows host for task/install/upgrade/rollback acceptance; then qualify complete WDDM process attribution. Only after those evidence gates and explicit authorization should a controlled H5 optimizer/inference test be prepared. Keep H4 acceptance, H5 live work, and unattended recovery as separate approvals.

## Follow-up read-only qualification

Follow-up observations were collected on 2026-11-12 at approximately 01:15–01:30 Pacific time from a normal current-user PowerShell context (medium integrity; Administrators group was not elevated). This context had access to several APIs that the earlier restricted execution sandbox blocked. The earlier snapshot above remains historical evidence of the sandbox limitation; later observations below supersede its current-state unknowns only where explicitly stated. No installation, task, service, miner, GPU setting, credential, LM Studio, or WSL state was changed.

### RC installed and running identity

- `GET http://127.0.0.1:1235/_coordinator/status` returned HTTP 200 with `status=online` and a ready service state. The listener PID matched the running Coordinator process identity.
- The running service reports RC **0.11.3**, source path `C:\Users\mcarls\src\scripts\modules\resource_coordinator\resource_coordinator\__init__.py`, and revision `52d59d4803fd04b9bd1fd8b0ea72cc7f7a2f128895348ba37dbe68e44fea0c0d`. Its process creation time was 2026-11-06 20:58:28 Pacific. The merged source in this worktree is **1.0.0**. The shared development `.venv` remains distribution **0.6.0** with a `direct_url.json` pointing to a prior temporary test source. These are three distinct identities; the source merge does not mean the installed/running service was upgraded.
- The running service's maintenance-status route returned HTTP 404, consistent with the older runtime and not evidence that the service is unavailable. Its observed configuration has no `maintenance_verification` section; trusted maintenance verification is therefore not enabled there.
- The service status reported its managed `krig_miner` as running and Coordinator-owned. The reported PID and creation-time identity matched the independently observed Windows process. Numeric process identities are intentionally omitted from this committed report. No process control was performed.
- Three `resource-coordinator.exe` processes were observed as short-lived `status`/`status -j` queries launched under Codex PowerShell; they were not additional Coordinator service instances.
- The configured upstream address was safely projected as `http://127.0.0.1:1234` (no userinfo or query). Which clients bypass the Coordinator remains unknown.

### Task Scheduler and launch ownership

- In the same current-user context, `Get-ScheduledTask` succeeded and returned 221 tasks, including `ResourceCoordinator-KRig-UserLogon` (Running) and `KRig-Live-Output-Viewer` (Ready). The Task Scheduler service was Running (`Get-Service Schedule`, `sc.exe query Schedule`, both successful).
- The Coordinator task runs as the current interactive user at highest run level; its last-run timestamp was 2026-11-06 20:58:26 Pacific. The action is `pwsh.exe` with a sanitized 161-character command that invokes `C:\Users\mcarls\.resource_coordinator\start-coordinator.ps1`; the task XML is 1,779 characters. The script selects the repository `.venv` Python, sets repository module paths, and launches `resource_coordinator.cli serve` with the configured miner alias. Sensitive arguments and credential contents were not collected.
- The process ancestry observed for the service reaches the Task Scheduler service process. A read-only `netstat` listener check also matched the service PID. No duplicate Coordinator service instance was found in the bounded checks, but this is not a complete host-wide launcher audit.
- The configured operator-token file exists. Metadata-only ACL inspection found owner `XERES\\mcarls`, inheritance disabled, two ACL entries and zero broad allow entries for Everyone, Authenticated Users or Users. Token bytes were never read. This is a bounded ACL check, not a full credential-store security certification.
- Earlier sandbox errors from CIM, `schtasks.exe`, and `sc.exe` were environment restrictions: the same current-user context later read the task and Scheduler service successfully. No service ACL or task definition was changed.

### WinError 206 and offline upgrade transport

- The existing installer retains its file-backed protected helper request/result transport and reports native launch errors and path/command lengths. An existing mocked regression confirms a 100,000-character task XML payload remains in a file and the child argv remains below 2,000 characters.
- Two harmless local `subprocess` probes independently reproduced native WinError 206 before process creation: one with a 33,000-character argument and one with a 33,007-character executable path. These show that both command-line and executable-path lengths can produce 206 at the process-creation boundary; they do not identify the cause of the historical upgrade failure.
- The observed task command and XML are short (161 and 1,779 characters). No historical failing request or exact failing upgrade artifact was available. Root cause and end-to-end remediation therefore remain **NOT_TESTED**.
- A safe Windows-focused selection ran with `RC_WINDOWS_INTEGRATION=1`; task/UAC integration flags were unset. Result: **14 passed, exit 0**, JUnit at `modules/resource_coordinator/.pytest_tmp_root/h4-safe-3609e150433a4b79a746961698a9d0e0/junit.xml` in this worktree. It covered restoration-observer regressions, large file-backed payload handling, quoted elevated-CLI arguments, timeout/malformed completion receipts, and a harmless bounded helper process. It did not register a task, invoke UAC, upgrade RC, or test rollback against an installed service. An initial test setup attempt failed because the module-local pytest temp parent did not exist; after creating the ignored parent, the same selection passed. This was test setup, not a product failure.
- A `Get-VM` inventory attempt did not identify a usable disposable VM (the Hyper-V query raised `VirtualizationException: Value cannot be null (Parameter 'name')`). No independently identified, separately authorized disposable Windows host is available in this run. Task installation/replacement, elevated ACLs, upgrade interruption and operational rollback were not attempted on the primary host.

### RTX 5090 / NVML and WDDM

- Read-only `nvidia-smi` observation reported RTX 5090 UUID `GPU-d573e046-ec53-77d8-009b-93c6e6bc60b6`, PCI `00000000:01:00.0`, driver/NVML `621.14`, and power limit 550,000 mW. A separate snapshot reported instantaneous clocks; these are not configured offsets or a restoration baseline.
- A one-off read-only native `nvml.dll` ctypes probe used `nvmlInit_v2`, UUID handle lookup, `nvmlDeviceGetPowerManagementLimit`, `nvmlDeviceGetClockOffsets`, and `nvmlShutdown`; it made no setter calls. Every return code was success. It read 550,000 mW, graphics P0 offset +225 MHz (supported range -1000..+1000 MHz), and memory P0 offset 0 MHz (range -2000..+6000 MHz). The six-field structure was 24 bytes with version value `16777240`; clock domains were graphics 0 and memory 2. This establishes that these getters worked on this device/driver at that timestamp. It does not establish the original/restored values, repeatability, a mutation-and-restore cycle, or automatic-release readiness.
- The RC observer source uses a six-field ctypes structure with the same documented field widths and version encoding. The shared development `.venv` lacks the optional `pynvml` binding, so the production observer class was not invoked against that interpreter; the native getter probe and fake-backed source tests are separate evidence.
- Compute-process enumeration was inconsistent across snapshots: one query returned zero rows; a later query returned 31 WDDM rows with `[N/A]` memory and did not show the Coordinator-reported KRig PID. NVIDIA exposes distinct compute and graphics process APIs, and WDDM may make memory attribution unavailable. Process enumeration is therefore **PARTIAL**, not complete. Do not set `gpu_process_attribution_confirmed`, and do not enable execution-boundary recovery.
- Fixed/locked-clock restoration remains unsupported. Offset getter success alone does not qualify that mode.

### LM Studio, disposable host, and readiness

- Prior installation metadata remains LM Studio `0.4.28+2` and `lms.exe` `1.3.3`. No `lms ps`, WSL command, model operation or inference request was made. At an earlier narrow process snapshot no LM Studio process was found, but current Windows/WSL runtime ownership, no-wake behavior and direct-client routing remain **UNKNOWN**.
- No disposable VM was independently identified. Actual task/UAC/install/rollback acceptance remains **NOT_TESTED** and must run on an isolated authorized host before production deployment.
- The current host is demonstrably running RC 0.11.3 while source is 1.0.0; H5 is **NOT READY**. It requires separate authorization and a controlled environment for upgrade and actual miner/GPU restoration behavior. Unattended recovery remains disabled; incomplete WDDM attribution and unqualified execution-boundary evidence are blocking gates.

## Updated H4 disposition

| Gate | Result | Evidence / remaining work |
|---|---|---|
| Parts 2–3 source merge and offline regressions | PASS | Merged source identity and historical tests remain as recorded above. |
| Current-user RC/task read-only inventory | PARTIAL | Live RC/task identity observed; runtime is v0.11.3, not merged v1.0.0. Full duplicate-launcher/process visibility is not established. |
| Operator-token ACL metadata | PARTIAL | Narrow ACL properties observed; no token content read; not a complete credential-store audit. |
| WinError 206 offline boundary | PARTIAL | Two harmless native reproductions and file-backed transport tests pass; historical upgrade failure root cause and actual upgrade path remain untested. |
| Disposable Windows install/task/rollback | UNAVAILABLE | No independently identified, separately authorized disposable host. |
| RTX 5090 power/offset getters | PARTIAL | Native getter calls succeeded; no controlled restore cycle and RC runtime is older. |
| WDDM process attribution | BLOCKED | Current enumeration is incomplete/inconsistent; trusted process-termination evidence is not qualified. |
| LM Studio no-wake/runtime/client routing | NOT_TESTED | No runtime probing or client traffic analysis was performed. |
| Controlled H5 | NOT READY | Runtime/source mismatch and hardware/process coverage gaps remain; requires separate authorization. |
| Unattended recovery | BLOCKED | Keep disabled until complete process-boundary and deployment qualification plus separate approval. |

The new evidence does not change production state. Exact command families, result codes, test command, and follow-up gates are summarized in `ACCEPTANCE_MATRIX.md`.
