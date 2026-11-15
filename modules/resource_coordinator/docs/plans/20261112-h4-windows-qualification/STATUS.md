# H4 Windows Qualification — Read-Only Status

## H4.7 release integrity & portable guest bundle (2026-11-15)

- Branch: `agent/rc-h4-release-integrity-20261115` (descended from H4.6 `555cf4804ee4f62d8691b61a663da162a829e808` and `origin/main` `0d29b59c722b998dc84ed80caa1c383f04b2cae9`).
- Replaced unsorted `os.walk` hashing with canonical `rc-h4-tree-sha256-v2` (`tools/h4_qualification/source_integrity.py`) and enforced `--source-manifest` verification in `windows_acceptance.py` before test/mutation execution.
- Added `tools/h4_qualification/bundle_builder.py` to export immutable `1.0.0` + `0.14.0` + `resource-metrics` snapshots, dependency lock (`dependencies/dependency-lock.json`), PowerShell 7 preflight script (`scripts/Verify-H4GuestBundle.ps1`), external non-self-referential `manifest.json`, and deterministic `.zip` archive with fresh-extraction verification.
- Disposable Windows guest execution (`task`, `install`, `upgrade`, `rollback`, `full`, `cleanup`) remains `NOT_TESTED` pending an authorized disposable Windows VM.

## H4.6 operational acceptance readiness (2026-11-15)

- Reviewed H4.5 integration candidate: `integration/rc-h4-5-windows-review-20261115` at `83849e3e5b55d1bb7851dd9daaa6ef53bc02a47b` (reconciled with `origin/main` `0d29b59c722b998dc84ed80caa1c383f04b2cae9`); `main` merge remains gated on explicit protected-branch authorization.
- Operational acceptance branch: `agent/rc-h4-operational-acceptance-20261115`.
- Pinned guest execution manifest: `tools/h4_qualification/source-manifest.json` (`1.0.0` at `83849e3e5b55d1bb7851dd9daaa6ef53bc02a47b`, tree SHA-256 `4a7b5a0c307b22b867edb9c6a2451ac213ce3dc67ac444ecdd8f2592f88277e8`; `0.14.0` at `873a49382a5e03da47f793608d3519f7e69da646`, tree SHA-256 `847ca50aa85f58e1804f920d986ba80d15cc70e4754f9ea103c90320dc109529`).
- Read-only `Get-VM` check confirmed no disposable Windows VM is available or authorized on this host; no VM was provisioned and no production state was touched. Actual Windows guest execution (`task`, `install`, `upgrade`, `rollback`, `full`, `cleanup`) remains `NOT_TESTED` pending an authorized disposable Windows VM with a clean checkpoint.

## H4.5 implementation status (2026-11-15)

- Starting candidate: `agent/rc-h4-disposable-windows-wddm-20261114` at `a618d6b0edcdb9e15f019a9e5109914643c20e99`; current `origin/main` at start: `04835a8c93c90881614d55651688800d5f646cad`.
- Implementation worktree: `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-h4-full-windows-lifecycle-20261115`, branch `agent/rc-h4-full-windows-lifecycle-20261114`.
- V3 is tracked and matches SHA-256 `BA842936C9DE945EE8463FD41C3E60491A5714DCA1CF481064DC915DBF516F46` and blob `3a1c2f7662a54469bb6dc15ad6462a4295ec93e6`.
- Work is limited to guest-only installer isolation, H4 acceptance runner/tests, and this qualification record. Production CLI defaults, production task identities, and `main` remain unchanged.
- Existing H4 observation says no suitable authorized guest was available; no virtualization inventory or WDDM resampling is planned without new evidence.
- Status: offline implementation checkpoint is ready for review; actual guest acceptance is `NOT_TESTED`. No guest or production mutation has been attempted.

## Scope and safety

This record captures the authorized source merge and the initial, read-only H4 host inventory. No RC package was installed or upgraded; no service or Scheduled Task was changed or restarted; no miner, LM Studio backend, or WSL instance was started, stopped, or controlled; no GPU setting or credential was changed. A localhost status request was attempted as a read-only GET but the execution sandbox denied socket access before a response was received.

Observation context: Windows PowerShell, effective account `XERES\mcarls`; timestamps are local Pacific time on 2026-11-12. This is a bounded observation snapshot, not a claim about current state after that timestamp.

## Source baseline

H4 follow-up branch: `agent/rc-h4-disposable-windows-wddm-20261114`. Before publication, `origin/main` advanced from the RC source baseline to `04835a8c93c90881614d55651688800d5f646cad`, one `mangadl` commit touching only seven `modules/mangadl/` paths. The H4 branch merged that commit without conflict; the RC source delta remains confined to H4 qualification paths. H4 implementation commit: `1f5269043cc99776d66e0f5d3cf82b65c617c20e`; mainline reconciliation merge commit: `1e5bdf7a23e86bc56f845437ac651d19a1649d5d`.

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

## H4 disposable-host and WDDM follow-up (2026-11-14)

### Environment selection

The completed read-only preflight found Windows 11 Pro build 26300, Hyper-V enabled, Windows Sandbox disabled, and no local Hyper-V VM in the explicit local inventory. Hyper-V management/compute, WSL, and Docker services were already running. At the time of the preflight, 61.6 GB RAM was installed and approximately 3.4 GB was free while KRig, Docker, and WSL activity existed. This host is not a suitable target for guest creation/start: it would require an unapproved host mutation and would compete with current workloads. No host feature, VM, service, task, or workload was changed.

The preferred environment is a separately authorized idle Windows host with a dedicated Hyper-V guest and checkpoints. A restrictive Sandbox is suitable only for a smaller task/helper test after feature enablement on an idle test host. See `DISPOSABLE_ENVIRONMENT.md`.

### Acceptance harness

Added `tools/h4_qualification/windows_acceptance.py` and fake-backed guard tests. Default mode is read-only and records an isolated preflight. Its offline profile invokes mock-backed installation tests; its task profile is gated by observed WMI guest identity, successful task/service/process inventories, an isolated absolute `h4-rc-*` root, no RC/miner task/service/process, and an explicit operator phrase. The task integration test repeats the guest/inventory guard itself and uses a random exact task name; cleanup failure fails the test. It stores sanitized task summaries and an exact cleanup manifest, not task XML or credentials.

The current runner does not invoke the real `ManagedInstallation.setup()` or `.upgrade()` flow: those paths still bind to fixed production RC task names, shared credential lookup, service status, and runtime activation. The full install/upgrade/interruption/rollback sequence remains an explicitly documented disposable-guest procedure, not a completed acceptance. No task profile was run because no suitable authorized guest was available.

The runner's final read-only primary-host preflight (2026-11-14 23:27 Pacific) successfully queried OS, WMI, tasks, services, and filtered process identity using a test root outside the source tree. It refused the task profile for `guest_identity_not_independently_verified`, `rc_task_present`, and `rc_or_miner_process_present` (exit 3). Its output and raw identities are in `%TEMP%\h4-rc-host-preflight-release-20261115\`; no command lines or credentials were retained.

### WDDM samples

Added `tools/h4_qualification/wddm_probe.py`, which queries NVML compute and graphics process APIs separately, runs vendor reads in bounded helper processes, and independently correlates PID, creation time, and executable identity. Final samples on 2026-11-14 at 23:25:28–23:25:32 Pacific observed the RTX 5090 UUID and driver 621.14 consistently; compute API returned 41 rows and graphics API 39 rows in each sample. The RC-reported KRig PID appeared in the compute rows all three times and matched Windows creation-time/executable identity; it was absent from the graphics rows. All 41 union PIDs could be independently inspected in each sample. Its `usedGpuMemory` field was unavailable under WDDM, which does not indicate absence of the PID.

This repeatable known-process match corrects the earlier snapshot's observation that the PID was missing in sampled compute output. It does not prove complete host/GPU-process coverage: both APIs are dynamic, report separate process classes, and this sampling has no authoritative completeness signal. Keep `gpu_process_attribution_confirmed=false`; Case C and unattended recovery remain unavailable. Raw snapshots, including ephemeral PIDs and paths, remain in ignored `.pytest_tmp_root/h4-wddm-probe-20261114/` and are not committed. See `WDDM_ATTRIBUTION.md`.

### Validation run

- New fake-backed probe/harness selection: final run 19 passed, exit 0. It covers WDDM memory sentinel handling, API classification, identity reuse/mismatch, UUID/driver mismatch, query timeout, guest guard, inventory refusal, artifact initialization, dry-run task profile, short/long CLI options, and offline-profile gating.
- Harness offline profile: 110 tests, 109 passed, 1 skipped, 0 failures, exit 0. Final JUnit is in ignored `.pytest_tmp_root/h4-rc-offline-release-final-20261115/`. The skipped helper integration test was not enabled in that profile.
- Read-only live NVML process sampling: final 3/3 samples (23:25:28–23:25:32 Pacific) returned successful compute/graphics inventories, stable UUID/driver, and exact known-miner identity match. No setter or process-control call occurred.
- Actual disposable Scheduled Task, UAC, installation, upgrade, interruption, and operational rollback acceptance: not run; no suitable independently authorized guest.
- Intermediate validation findings were corrected: a non-`h4-rc-*` path was refused with exit 3 before tests; one fake subprocess result initially lacked captured output fields; and a task-profile dry run was initially blocked by a source-tree restriction intended only for mutations. The fixture and guard scope were corrected; final focused tests passed. No mutation occurred during these attempts.

Source import provenance is the task worktree; H4 source/package baseline remains `1.0.0`.

Commands and final exits (PowerShell, module worktree, unique module-local pytest roots):

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest tests\test_h4_wddm_probe.py tests\test_h4_windows_acceptance.py -q --basetemp <absolute-module>\.pytest_tmp_root\h4-ship-focus-20261115 --junitxml <absolute-module>\.pytest_tmp_root\h4-ship-focus-20261115\junit.xml
# final run exit 0; 19 passed

python tools\h4_qualification\windows_acceptance.py --test-root <absolute-module>\.pytest_tmp_root\h4-rc-offline-release-final-20261115 --apply --profile offline --json
# final run exit 0; JUnit: 110 total, 109 passed, 1 skipped, 0 failed

python -m ruff check tools\h4_qualification\wddm_probe.py tools\h4_qualification\windows_acceptance.py tests\test_h4_wddm_probe.py tests\test_h4_windows_acceptance.py tests\test_windows_task_transport_integration.py
# exit 0

python -m compileall -q tools\h4_qualification\wddm_probe.py tools\h4_qualification\windows_acceptance.py tests\test_h4_wddm_probe.py tests\test_h4_windows_acceptance.py tests\test_windows_task_transport_integration.py
# exit 0
```

### Current disposition

| Gate | Result | Evidence / next requirement |
|---|---|---|
| Disposable VM selection | UNAVAILABLE | No local VM; Sandbox disabled; separate idle authorized Windows VM/host needed. |
| Harness preflight and offline profile | PASS | Fail-closed runner, isolated artifacts, and 110-test offline profile. |
| Real task profile | NOT_TESTED | Requires a separately authorized guest; primary host correctly refused. |
| Actual install/upgrade/rollback | NOT_TESTED | Guest-only runtime injection and lifecycle profiles now exist; execution still requires an independently identified and authorized disposable Windows guest. |
| Historical WinError 206 upgrade cause | PARTIAL | Long command/path boundaries were reproduced earlier; actual upgrade path still untested. |
| RTX 5090 read-only compute/graphics PID correlation | PARTIAL | Known KRig PID matched compute + Windows identity in three snapshots; graphics API did not list it. |
| Complete WDDM attribution / Case C | BLOCKED | No authoritative proof of complete process coverage; keep configuration false. |
| H5 supervised maintenance | NOT READY | Runtime still reports 0.11.3 vs source 1.0.0; disposable acceptance, approved deployment, and bounded preflight remain. |
| Unattended recovery | BLOCKED | Keep disabled pending execution-boundary qualification and separate approval. |

## H4.5 lifecycle acceptance infrastructure checkpoint (2026-11-15)

The implementation adds an explicit `InstallationRuntime` seam for guest-only task identities, loopback listener/port, dummy credentials, process/listener/GPU observations, clocks, and fault injection. `InstallationPaths.isolated()` confines mutable artifacts to a guest test root. `ManagedInstallation` rechecks containment and mutation authorization; the production CLI continues to construct the unchanged production-default runtime. The Windows task helper receives task identities through its protected request payload and does not accept arbitrary identity overrides through the production CLI.

Source review caught and fixed one remaining production-only assumption in `_legacy_attribution()`: the guest upgrade preflight used to accept only production task names. It now receives the injected runtime task-name mapping, with production names retained as the default for unchanged callers. A focused helper regression was added. The first validation attempt could not import `_ssl`; that historical failure is superseded by the successful focused run documented in the continuation below.

`windows_acceptance.py` now offers read-only `preflight` by default and explicit `offline`, `task`, `install`, `upgrade`, `rollback`, `full`, and `cleanup` profiles. Guest profiles require `--apply`, explicit authorization, a matching guest-authorization environment value, independently observed virtual-guest identity, readable task/service/process inventories, isolated absolute paths, and an exact test-owned resource manifest. Source bundles are version-checked and hashed before use. Full runs keep a phase manifest and verify task, listener, and process cleanup after each phase; interrupted runs retain exact manifest evidence for the scoped cleanup profile.

### Fresh validation in the H4.5 worktree

| Check | Result |
|---|---|
| `compileall` for changed installer, runner, and tests | PASS, exit 0 |
| `tests/test_h4_windows_acceptance.py` | 12 passed, exit 0; pytest warned that `asyncio_mode` is unknown because plugin autoload was disabled |
| Fake-module installer runtime isolation probe | PASS, exit 0; this does not import or exercise the RC async stack |
| Combined H4 runner + WDDM tests | BLOCKED during WDDM collection: `_ctypes` DLL initialization failure |
| Installer runtime tests | BLOCKED during collection: `_ssl` DLL initialization failure through `anyio` |
| Ruff | NOT RUN: the Ruff launcher failed to initialize in this execution environment |
| Actual guest install/upgrade/rollback | NOT TESTED: no authorized disposable guest was available |

The isolated Python 3.12 executable runs, but importing `_ctypes` and `_ssl` fails with “DLL initialization routine failed”. Those failures occurred during test collection before product assertions. The runner-only test file does not import either extension and ran successfully. A separate fake-module probe exercised runtime construction, guest guard requirements, task identity injection, and listener selection. This is limited evidence, not a replacement for the blocked installer tests or real guest acceptance.

The worktree's Git client also failed to initialize (`0xC0000142`) during status inspection. Consequently this checkpoint has not been committed or pushed, and no current cleanliness or remote-tip claim is made. Once Git is available, inspect the exact worktree diff/status, rerun the focused checks, then commit and push the isolated H4.5 branch. Do not merge it to `main`.

### Guest execution procedure

Prepare separate, read-only source bundles for RC `0.14.0` and `1.0.0`; record their source tree SHA-256 values. Create a new guest-local directory whose name begins `h4-rc-`, ensure it is outside the source trees and protected installation directories, and run the preflight without `--apply`. Only a separately authorized guest operator may set `RC_H4_DISPOSABLE_GUEST_AUTHORIZED` to the documented phrase and run a mutating profile. Use the new-source root for `--source-root`; provide the separately staged 0.14.0 root for `--old-source-root` on upgrade/rollback/full. Keep the authorization environment scoped to the guest process. Preserve `environment.json`, `preflight.json`, `test-results.json`, `junit.xml`, per-phase `upgrade-receipts/`, `task-snapshots/`, `process-identity.json`, `cleanup-result.json`, and `cleanup-manifest.json`. If a profile fails or is interrupted, do not rerun over the same phase root; inspect the exact manifest and use the explicit cleanup profile only after the guest is re-preflighted. A cleanup uncertainty requires guest checkpoint restoration or operator inspection.

The current worktree cannot claim this procedure has been exercised on Windows Task Scheduler, UAC, real service processes, or rollback. The earlier WinError 206 probes remain candidate reproductions only; the historical production upgrade failure site is still unknown. WDDM remains incomplete despite the preserved 3/3 known-process correlation. H5 remains blocked by disposable acceptance and the installed-versus-running RC version mismatch; unattended recovery remains disabled.

### Exact fresh commands

Commands ran from `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-h4-full-windows-lifecycle-20261115\modules\resource_coordinator` using Python 3.12.10 at `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe`:

```cmd
"C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe" -m compileall -q resource_coordinator\installation.py tools\h4_qualification\windows_acceptance.py tests\test_h4_windows_acceptance.py tests\test_h4_installation_runtime.py
```

Exit 0.

```cmd
set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 && "C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe" -m pytest tests\test_h4_windows_acceptance.py -q --basetemp "C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-h4-full-windows-lifecycle-20261115\modules\resource_coordinator\.pytest_tmp_root\h45-runner-current-3"
```

Exit 0; **12 passed**. Pytest warned that `asyncio_mode` is unknown because plugin autoload was explicitly disabled.

```cmd
set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 && "C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe" -m pytest tests\test_h4_windows_acceptance.py tests\test_h4_wddm_probe.py -q --basetemp "C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-h4-full-windows-lifecycle-20261115\modules\resource_coordinator\.pytest_tmp_root\h45-offline-final"
```

Exit 2 at `test_h4_wddm_probe.py` collection: `_ctypes` DLL initialization failed. The runner-only test had already passed independently.

```cmd
set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 && "C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe" -m pytest tests\test_h4_installation_runtime.py -q --basetemp "C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-h4-full-windows-lifecycle-20261115\modules\resource_coordinator\.pytest_tmp_root\h45-runtime-final"
```

Exit 2 at collection through `resource_coordinator.__init__` → `anyio` → `ssl`: `_ssl` DLL initialization failed. Ruff's launcher and `git status` also exited `-1073741502` (`0xC0000142`) before producing output. No commit or push was attempted after that failure.

### H4.5 continuation validation (2026-11-15)

The first combined regression run exposed compatibility issues in the new injection boundary: existing installer tests replace `_legacy_attribution` with its historical four-argument signature and patch no-argument listener helpers. The initial injected-runtime calls changed those seams. A new helper test also used a pytest temporary root beneath the source checkout, correctly triggering the source-overlap guard. The implementation now retains legacy call signatures for production defaults and uses the system temporary directory for that isolated-path rejection test. Existing assertions were preserved.

The lifecycle runner now exposes the installer's existing failure checkpoints as explicit `--fault-stage` choices: `after_prepared_receipt`, `after_old_service_stopped`, `before_task_replacement`, `after_task_replacement`, and `after_new_service_ready`. Rollback still requires a recognized fault point and an independently verified automatic rollback result. The guest mutation guard also inventories the selected loopback port and fails closed if its listener is not absent or owned by the exact recorded test process (PID, creation time, executable). This adds selectable guest scenarios; no actual guest lifecycle execution is claimed.

Validation ran in the H4.5 worktree from `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-h4-full-windows-lifecycle-20261115\modules\resource_coordinator`, using Python 3.12.10 at `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe`:

```powershell
$py = 'C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe'
$base = Join-Path $PWD.Path '.pytest_tmp_root\h45-final'
& $py -m pytest tests\test_h4_windows_acceptance.py tests\test_h4_installation_runtime.py tests\test_installation.py tests\test_windows_task_transport_integration.py -q -p no:cacheprovider --basetemp $base --junitxml (Join-Path $base 'junit.xml')
```

Exit 0; JUnit reported **134 tests, 0 failures, 0 errors, 3 skipped**. The skips are opt-in Windows task-mutation tests. No guest mutation was attempted.

```powershell
$py = 'C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe'
& $py -m ruff check resource_coordinator\installation.py tools\h4_qualification\windows_acceptance.py tests\test_h4_installation_runtime.py tests\test_h4_windows_acceptance.py
& $py -m compileall -q resource_coordinator\installation.py tools\h4_qualification\windows_acceptance.py tests\test_h4_installation_runtime.py tests\test_h4_windows_acceptance.py
git diff --check
```

All three checks exited 0. JUnit is at `.pytest_tmp_root\h45-final\junit.xml`. An intermediate pytest invocation used a doubled module path for `--basetemp` and failed during fixture setup; it did not run product assertions and is excluded from the passing result.

The existing runner's offline profile was also executed directly with a unique module-local artifact root:

```powershell
$run = Join-Path $PWD.Path ('.pytest_tmp_root\h4-rc-offline-h45-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $run | Out-Null
& 'C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe' tools\h4_qualification\windows_acceptance.py --test-root $run --apply --profile offline --json
```

Exit 0; **110 tests, 0 failures, 0 errors, 1 skipped**. The skip is the pre-existing opt-in Windows task integration case. The offline profile ran no Task Scheduler or service mutation.

Git publication is still pending. `git fetch origin` cannot write the shared `.git/FETCH_HEAD` in this sandbox (`Permission denied`), and this worktree's upstream still points to the earlier H4 documentation branch. No commit or push has been attempted. When repository metadata access is available, confirm the intended H4.5 remote ref and publish explicitly; do not push to the stale upstream.

The current cached `origin/main` and local primary `main` are `be15c705c56c14762f2d534441340ba9c8f12f7c`; the H4.5 worktree remains at base `a618d6b0edcdb9e15f019a9e5109914643c20e99`, with merge base `04835a8c93c90881614d55651688800d5f646cad`. The intervening mainline diff is limited to four `modules/cli_tui/` paths for path completion UI and tests, with no RC overlap. The task branch remains isolated; it was not merged with that unrelated work. Remote refs could not be refreshed because `FETCH_HEAD` is unwritable here. Actual guest installation, upgrade, UAC/task, rollback, and historical WinError 206 path remain `NOT_TESTED`. H5 remains blocked and unattended recovery disabled.
