# H4 Read-Only Qualification Checklist

Date: 2026-11-12 (Pacific)

## Source merge

- [x] Parts 2–3 candidate fast-forwarded to `main` at `0f983428c2a5e0ae02517f94dec6a38b1a4cec4b`.
- [x] Remote `origin/main` verified at the same commit.
- [x] RC package source reports `1.0.0`; entry-point metadata and import provenance checked.
- [x] V3 SHA-256 and Git blob match the finalized values.
- [x] Focused post-merge test selection: 14 passed; compile and scoped diff checks passed.
- [x] Existing H3/Part 3 evidence preserved; broad suite not unnecessarily rerun.

## Read-only host inventory

- [x] Queried GPU identity, PCI address, driver/NVML version and power limit with `nvidia-smi`.
- [x] Queried current clocks; recorded that this does not verify offset restoration.
- [x] Checked compute-app query; zero rows, attribution completeness remains unknown.
- [x] Checked development RC distribution; distinguished `0.6.0` shared test environment from merged source `1.0.0` and production installation.
- [x] Checked LM Studio installed-app and `lms.exe` file-version metadata; did not run `lms ps` or WSL.
- [x] Attempted non-mutating RC status GET; sandbox denied loopback access before HTTP response.
- [x] Attempted read-only service/task/process discovery; documented access and CIM limitations.
- [x] No production service, task, miner, GPU setting, credential, LM Studio backend or WSL state was changed.

## Remaining operational gates

- [x] Obtain permitted read-only installed/running identity observations; mismatch found: source 1.0.0, shared dev distribution 0.6.0, live runtime 0.11.3. Do not upgrade under this assignment.
- [x] Inspect the relevant Scheduled Task and service in current-user context; broad descendant/alternate launcher and full ACL qualification remain incomplete.
- [ ] Reproduce and validate `WinError 206`, upgrade, rollback and interruption recovery on a disposable Windows host.
- [x] Read-only NVML graphics/memory offset getters returned values on this RTX 5090/driver; controlled restoration, repeated observer checks, timeout/access-denied and actual RC-interpreter qualification remain open.
- [ ] Establish complete WDDM GPU-process attribution and host-wide known-miner inventory.
- [ ] Qualify actual KRig launch/ownership and cooldown behavior in the separately authorized controlled test.
- [ ] Establish LM Studio runtime identity, no-wake observation behavior and direct-client routing coverage.
- [ ] Conduct bounded H5 live maintenance acceptance only under explicit authorization.
- [ ] Keep unattended recovery disabled until Windows execution-boundary evidence is qualified and rollout is separately authorized.

## H4 disposable-host/WDDM follow-up (2026-11-14)

- [x] Verified V3 is present in the task worktree with the expected SHA-256 and Git blob; no edit was made.
- [x] Refreshed read-only Windows virtualization inventory: Sandbox disabled, Hyper-V enabled, no VM identified, approximately 3.4 GB free RAM during active KRig/WSL/Docker workload; no guest was provisioned or started.
- [x] Compared Sandbox and dedicated Hyper-V options and selected a separate idle authorized Windows VM/host for full upgrade/rollback acceptance.
- [x] Added a default-read-only `windows_acceptance.py` runner with guest identity, task/service/process inventory, explicit authorization, isolated-root, artifact, timeout, result-code, and exact cleanup guards.
- [x] Added an independently enforced guest guard to the disposable task integration test.
- [x] Added a bounded NVML v3 compute/graphics process probe with PID/create-time/executable correlation and WDDM unavailable-memory classification.
- [x] Fake-backed H4 probe/harness tests: final run 19 passed, exit 0.
- [x] Harness mock-backed offline installation profile: 110 total, 109 passed, 1 skipped, no failures, exit 0.
- [x] Final harness primary-host preflight (exit 3) refused task mutation for non-guest identity and detected RC task/miner/coordinator processes.
- [x] Three final bounded read-only GPU samples showed stable UUID/driver, listed the known Coordinator-owned KRig PID in compute rows, and matched its Windows create-time/executable; it was absent from graphics rows.
- [x] Recorded WDDM memory as unavailable-under-WDDM, not process absence; attribution completeness remains unproven and configuration stays false.
- [ ] Run disposable task/UAC/install/upgrade/interruption/rollback acceptance on a named, separately authorized isolated Windows guest.
- [ ] Reproduce WinError 206 through the actual upgrade orchestration in that guest.
- [ ] Demonstrate complete WDDM process coverage before enabling Case C or unattended recovery.
- [x] Kept production installation, host task state, GPU settings, KRig, LM Studio, and WSL unchanged.

## Follow-up disposition

- [x] Read-only RC status endpoint returned HTTP 200; current runtime is v0.11.3 and reports ready. `maintenance/status` returns 404 in that older runtime.
- [x] Current-user Task Scheduler and Scheduler-service queries succeeded; sandbox-specific failures in the initial snapshot are preserved as historical limitations.
- [x] Token-file ACL metadata was checked without reading its contents: current user owns it, inheritance is disabled, and no broad user-group allow entry was found.
- [x] Safe offline Windows selection: 14 passed, exit 0; task/UAC integration flags were not enabled.
- [x] Harmless local process-creation probes reproduced WinError 206 for a long argument and executable path; the historical upgrade root cause remains unresolved.
- [x] Native read-only NVML power/offset getters succeeded; values are not treated as a restoration baseline.
- [x] No independently identified and separately authorized disposable VM/host was available; install/task/upgrade/rollback mutation was not attempted.
- [x] H5 is not ready and unattended recovery remains disabled due runtime mismatch and incomplete WDDM process attribution.
