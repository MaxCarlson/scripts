# H4 Qualification Acceptance Matrix

Date: 2026-11-12 (Pacific)

Source baseline: `main` / RC `1.0.0` at `0f983428c2a5e0ae02517f94dec6a38b1a4cec4b`
Observation context: current-user Windows PowerShell, medium integrity; no elevation.

`PASS` means the listed check was directly established. `PARTIAL` means only part of the acceptance claim is established. `UNAVAILABLE` means a required environment was not available. `NOT_TESTED` means the operation was intentionally outside this run. `BLOCKED` means a safety prerequisite is not satisfied.

| Gate | Result | Observed / executed | Still required |
|---|---|---|---|
| Source identity | PASS | Merged source import/version is 1.0.0; V3 checksum/blob match the finalized values. Existing Part 3, H3 and post-merge test evidence is preserved. | No source change was made in this H4 follow-up. |
| Live RC identity | PARTIAL | Read-only `GET http://127.0.0.1:1235/_coordinator/status` returned 200, online/ready. Runtime reports 0.11.3, repository source path, and revision `52d59d4803fd04b9bd1fd8b0ea72cc7f7a2f128895348ba37dbe68e44fea0c0d`. Maintenance-status route returned 404. | Do not infer that deployed service is 1.0.0. An authorized installation/upgrade and subsequent read-only identity check are required. |
| Task Scheduler inventory | PARTIAL | `Get-ScheduledTask` succeeded (221 total; RC task Running; KRig output-viewer task Ready); Schedule service Running; task is current-user interactive, highest run level. Sanitized launcher command length 161; task XML 1,779 chars. | No task mutation, launch, ACL change, or disposable-host validation. Complete duplicate-launcher audit remains outstanding. |
| Runtime/miner process identity | PARTIAL | Listener PID matched the runtime process; service task ancestry was observed. RC reported `krig_miner` Coordinator-owned and its process PID/create-time matched independent Windows observation. No command-line dump retained. | Host-wide descendant and alternate launcher inventory is incomplete; no process was controlled. |
| Operator token ACL | PARTIAL | Metadata-only check: file exists; owner current account; inheritance disabled; two ACL entries; zero broad allow entries for Everyone, Authenticated Users, or Users. Secret bytes were not read. | This is not a complete credential-store or task-account security audit. |
| WinError 206 boundary | PARTIAL | Harmless Python child creation with 33,000-character argument and with 33,007-character executable path each returned native `winerror=206` before child execution. | These demonstrate possible causes, not the historical upgrade's root cause. Actual upgrade path is not tested. |
| File-backed installer transport | PASS (offline selection) | Existing mocked regression preserves 100,000-character task XML in the request file and keeps argv below 2,000 chars. Quoting, timeout and malformed receipt paths passed. | Does not establish elevated helper, Task Scheduler replacement, or operational rollback. |
| Disposable install/task/rollback | UNAVAILABLE | `Get-VM` did not identify a usable disposable VM; no separately authorized disposable host was available. | Run the full fresh-install/upgrade/task/interruption/rollback matrix in an isolated authorized Windows environment. Primary-host mutation remains out of scope. |
| RTX 5090 power/offset getters | PARTIAL | Native read-only NVML calls all returned success: 550,000 mW, graphics offset +225 MHz at P0, memory offset 0 MHz at P0. Device UUID/PCI/driver recorded in `STATUS.md`. | No setting was changed, so no restoration test occurred. Verify the RC observer under a qualified deployment interpreter and test a separately authorized controlled restore cycle before automatic release. |
| WDDM process attribution | BLOCKED | Compute-app inventory differed between snapshots; later WDDM rows had `[N/A]` memory and did not include the independently identified KRig PID. | Establish complete graphics/compute process coverage and identity correlation. Keep `gpu_process_attribution_confirmed=false`; Case C and unattended recovery remain unavailable. |
| LM Studio / WSL | NOT_TESTED | Installed metadata is LM Studio 0.4.28+2 and `lms.exe` 1.3.3. No `lms ps`, WSL command, model operation or inference was run. | Qualify runtime identity, no-wake semantics and direct-client routing under separate authorization. |
| H5 controlled live maintenance | NOT READY | Current runtime/source mismatch and unresolved process-attribution gates. | Requires separate authorization after deployment qualification and a bounded preflight. |
| Unattended recovery | BLOCKED | Source-level fail-closed behavior and simulated tests do not establish Windows execution-boundary termination. | Keep disabled pending Windows/WDDM qualification, complete recovery evidence, deployment validation and separate approval. |

## Executed offline test selection

Environment: Windows PowerShell, Python from the H4 worktree's existing environment; `PYTHONPATH` set to the H4 module. The module-local unique pytest temp root was `modules/resource_coordinator/.pytest_tmp_root/h4-safe-3609e150433a4b79a746961698a9d0e0` in the H4 worktree. `RC_WINDOWS_INTEGRATION=1`; `RC_WINDOWS_TASK_INTEGRATION` and `RC_WINDOWS_UAC_INTEGRATION` were unset.

```powershell
Set-Location C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-h4-windows-acceptance-20261112\modules\resource_coordinator
$env:PYTHONPATH = $PWD
$env:RC_WINDOWS_INTEGRATION = '1'
Remove-Item Env:RC_WINDOWS_TASK_INTEGRATION -ErrorAction SilentlyContinue
Remove-Item Env:RC_WINDOWS_UAC_INTEGRATION -ErrorAction SilentlyContinue
python -m pytest tests\test_restoration.py tests\test_installation.py::test_windows_task_transport_keeps_large_payload_out_of_process_command_line tests\test_installation.py::test_elevated_upgrade_cli_runs_once_and_preserves_quoted_arguments tests\test_installation.py::test_task_transport_timeout_retains_operation_artifacts tests\test_installation.py::test_task_transport_retains_artifacts_when_completion_record_is_invalid tests\test_windows_task_transport_integration.py::test_windows_helper_processes_large_request_from_protected_file -q --basetemp .pytest_tmp_root\h4-safe-3609e150433a4b79a746961698a9d0e0 --junitxml .pytest_tmp_root\h4-safe-3609e150433a4b79a746961698a9d0e0\junit.xml
```

Result: **14 passed, exit 0**. JUnit output was generated in the ignored module-local temporary directory. An initial setup attempt failed before tests because the pytest temp parent did not exist; after creating that ignored parent, the same selection passed. No product test failed in the successful run.

## Probe provenance and limits

- Status GET, Task Scheduler/service queries, process identity observations, token-file ACL metadata, and NVML reads were performed read-only as the current user. No credentials or task command lines containing sensitive values are retained.
- NVML getter probe used only initialization, device lookup, power/clock getter calls, and shutdown. It did not invoke setters. The reported offsets are point-in-time configured readings and must not be called the pre-maintenance baseline.
- NVIDIA's [NVML clock-offset query](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html) defines a versioned read API; it can still return unsupported for a device/driver. WDDM's process/memory visibility is a distinct capability and remains unqualified here.
- Microsoft defines [system error 206](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-) as `ERROR_FILENAME_EXCED_RANGE`. The local synthetic repros establish the process-creation boundary but not the historical installer call site.
- No production service, task, miner, GPU setting, LM Studio backend, WSL instance, or credential was modified.

## 2026-11-14 disposable-host and WDDM follow-up

| Gate | Result | New evidence | Remaining |
|---|---|---|---|
| Local disposable VM/Sandbox | UNAVAILABLE | Windows 11 Pro 26300; Hyper-V present but no VM; Sandbox disabled; approximately 3.4 GB free RAM during existing KRig/WSL/Docker activity. | Use a separately authorized idle Windows VM/host; do not provision here. |
| H4 runner/preflight | PASS | `tools/h4_qualification/windows_acceptance.py`; default is read-only; primary host refused task profile; guest and inventory guard is repeated inside the mutating task test. | Actual task profile is unrun; full install/upgrade/rollback remains guest procedure. |
| Offline installer regression via runner | PASS | 110 tests, 109 passed, 1 skipped, 0 failed, exit 0; mock-backed module tests. | Does not prove Task Scheduler, UAC, or real upgrade operations. |
| WDDM process identity sample | PARTIAL | In 3/3 samples, compute=41 rows, graphics=39 rows; all 41 union rows had readable Windows identities; known KRig PID/create-time/executable matched compute API in all samples, absent from graphics API. | No complete-inventory guarantee; `gpu_process_attribution_confirmed=false`. |
| WDDM process memory | PARTIAL | Known PID had `NVML_VALUE_NOT_AVAILABLE` under WDDM. | Not an absence signal and not proof of memory attribution. |
| WinError 206 actual upgrade cause | PARTIAL | Earlier harmless argument/path probes reproduced code 206; file-backed payload regression passed. | Root cause remains unverified until actual isolated upgrade path is run. |
| Supervised H5 | NOT READY | Current status endpoint reports 0.11.3; merged source is 1.0.0. | Disposable acceptance, separately authorized deployment, runtime identity, safe preflight, abort/restoration plan, explicit one-run authorization. |
| Unattended recovery | BLOCKED | Repeated known-process correlation is not complete attribution. | Keep disabled until authoritative execution-boundary evidence and separate approval. |

## 2026-11-15 H4.5 implementation checkpoint

| Gate | Result | New evidence | Remaining |
|---|---|---|---|
| Guest-only installer seam | PARTIAL | `InstallationRuntime`, isolated paths, test task identities, credential provider, observers, and mutation/fault hooks retain production defaults; installer/runtime regression tests passed. | Real guest ACL, Task Scheduler, service and UAC behavior remains untested. |
| Lifecycle runner | PARTIAL | `install`, `upgrade`, `rollback`, `full`, and exact-manifest `cleanup`; source trees are version checked and hashed; five upgrade fault points are selectable; cleanup is verified per phase. | No actual Task Scheduler/service lifecycle execution. |
| H4 runner/installer regression | PASS (focused) | Combined H4 runner, runtime injection, installation, and Windows helper transport selection: 134 passed, 3 skipped, 0 failed, exit 0. | Three opt-in task-mutation tests were skipped; pytest cache provider was disabled. |
| Static checks | PASS (focused) | Ruff on changed implementation/tests, compileall, and `git diff --check` exited 0. | None for this focused selection. |
| Isolated loopback listener ownership | PASS (fake-backed) | Runner probe is bounded and scoped to `127.0.0.1` plus the exact non-production phase port; tests reject unavailable inventory and unknown PID/create-time/executable owners. | Actual guest listener inventory remains unexecuted. |
| WDDM regression | UNAVAILABLE | Historical 3/3 known-process PID/create-time/executable correlation retained unchanged. | Current test collection failed because `_ctypes` DLL initialization failed; no resampling was done. |
| Actual guest lifecycle | NOT_TESTED | No separately identified and authorized disposable Windows guest was available. | Execute only on a separately authorized guest with checkpoint and exact cleanup manifest. |
| H5 supervised maintenance | NOT READY | No production state was touched. | Requires guest acceptance, separately authorized deployment, exact running v1.0.0 identity, safe preflight, and one-run authorization. |
| Unattended recovery | BLOCKED | Complete WDDM/execution-boundary attribution remains unproven. | Keep disabled; do not use idle or elapsed-time evidence as a substitute. |
