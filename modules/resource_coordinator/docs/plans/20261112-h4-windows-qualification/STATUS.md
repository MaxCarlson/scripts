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

First complete disposable Windows upgrade/task/rollback acceptance and qualify the installed-versus-running RC identity. Then independently qualify read-only NVML offset getters and WDDM process attribution on the RTX 5090. Only after those evidence gates and explicit authorization should a controlled H5 optimizer/inference test be prepared. Keep H4 acceptance, H5 live work, and unattended recovery as separate approvals.
