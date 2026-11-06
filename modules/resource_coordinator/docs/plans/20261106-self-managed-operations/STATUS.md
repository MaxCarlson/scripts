# Status — Self-Managed Operations

## Current checkpoint

- [x] Confirmed current source repository is `C:/Users/mcarls/src/scripts`, branch `main`; validated checkpoints are `3cd1da96` (log retention), `b1505a4d` (runtime identity doctor), `4b590ac2` (GPU-idle/game gate), and `d58ddcfc` (initial manual-hold preservation). Current changes build on `d58ddcfc`. No RC source worktree was created.
- [x] Existing setup, doctor, repair, teardown, startup task management, auth provisioning, optional viewer, and `miner`/`krig` log aliases are present in merged mainline history.
- [x] Added bounded append-only miner output retention: rotate at 64 MiB, preserve three prior files, and keep an empty active file ready for capture.
- [x] Doctor now resolves default capture paths, checks capture-directory access, and compares the running service's reported package path/version against the installed source.
- [x] Doctor labels the power limit and memory clock verified/mismatched/unavailable, and does not claim independent verification of dynamic core clock or the unexposed core offset.
- [x] GPU-idle sampling now pauses while gaming is stopping, active, restoring, or failed, so an old conditional pause cannot restart mining during gaming/reconciliation; 4 synchronous gate regressions pass.
- [x] All manual miner mutations are blocked during gaming/reconciliation; operators must use gaming stop to restore mining. A newer timed pause/stop clears any stale GPU-idle auto-resume condition. Synchronous gate coverage passes.
- [x] Focused installation/config/log/CLI tests: latest run 56 passed; credential regression selection: 15 passed, 1 async test deselected.
- [x] Protected inference route regression tests: 5 passed.
- [x] Ruff, `py_compile`, and submodule-safe `git diff --check` passed for current source changes.
- [ ] Validate service lifecycle controls (manual miner, gaming, GPU-idle) on a functioning async test runner. A focused `pytest -vv -s` invocation reached the first manual-control test and then stalled without assertion output; interrupted only that test process.
- [ ] Complete fresh-install/elevation acceptance and safe degraded teardown boundaries; driver telemetry still cannot independently verify core clock lock or offset, and live task/process controls are not available from this sandbox.
- [x] Confirmed the service-test stall is runner-level: `asyncio.run(asyncio.sleep(0))` prints before entering the loop and then hangs. The existing async lifecycle tests therefore remain unverified here; async credential restart test was excluded while its synchronous credential regressions passed.
- [ ] TUI remains deferred until setup/teardown and operational controls are validated.

## Ownership/dependency inventory (source review; runtime portions historical)

| Resource | Ownership | Current handling / evidence |
|---|---|---|
| RC config, durable state, operator token, logs, managed launcher | RC-managed; user configuration/data preserved | Per-user `.resource_coordinator`; setup provisions/validates without overwriting existing config; teardown preserves config, token, journal, and logs. |
| Startup coordinator task | RC-managed | Fixed boot/logon task names and ownership checks; interactive task uses Highest, boot task uses SYSTEM; current Scheduler inventory is unavailable to this sandbox. |
| Optional output viewer/task | RC-managed optional integration | Separate read-only logon task; reads configured capture path and does not own miner. |
| KRig executable/pool/worker settings | User-configured, process lifecycle coordinated by RC | Setup requires a configured non-placeholder worker identity before launcher enables mining; coordinator records process ownership and appends stdout/stderr. |
| NVIDIA driver power/clock state | Shared external system resource; not yet fully RC-enforced | Doctor reads configured flags and available `nvidia-smi` effective limit/draw/clocks; core offset is not exposed by the selected query. No live driver changes performed. |
| LM Studio process/server/model files | Externally owned integration | RC routes protected inference upstream and gaming controls use supported LM Studio API; do not uninstall LM Studio. |
| OpenCode inference provider | User-owned configuration with protected RC routing | Bridge tests validate `:1235` default and explicit Monitor route and prevent fallback to direct LM Studio `:1234`. Effective runtime checks for Codex/AGY remain unverified. |
| Windows Task Scheduler / UAC | OS-owned, RC manages only fixed RC task identities | Setup/task helpers use a static operation allow-list and request UAC for privileged task changes; live UAC/SYSTEM acceptance is unverified. |

Current live health and task inventory are not refreshed by this checkpoint; prior GPU, task, PID, and listener observations remain historical only.

## Last verified live state

Read-only host check in this execution: `resource-coordinator doctor --json` loaded the 0.9.0 source, validated the persisted token and ACL, found the configured capture log file and writable parent, and reported the configured GPU flags (550/2400/225/7001). NVIDIA reported 550 W limit, 539.8 W draw, 2385 MHz dynamic graphics clock, and 7001 MHz memory. It cannot expose the effective core offset; the doctor now labels that and the requested core lock unverified. The service endpoint returned no data and Task Scheduler CIM access failed (`Access to a CIM resource was not available to the client`); a direct CLI status connection was blocked with WinError 10013. Therefore service PID/miner ownership, active inference, runtime version, and startup task state are unknown from this sandbox. No live state was changed.

## Next action

Resolve the service-test runner hang or use a supported test context; finish setup/elevation/degraded teardown and hardware policy diagnosis; then verify controls/integrations/GPU-idle before implementing the TUI last. Preserve the dirty handoff document and unrelated untracked paths in the root checkout.

## Work completed in current execution

- Added top-level `setup`, `doctor`, `repair`, `teardown`, and `startup` command dispatch.
- Added configuration environment overlays for managed state and append-only log paths without overwriting explicit user configuration.
- Added a Windows task backend with a fixed operation allow-list, ownership checks, duplicate-trigger suppression, and explicit noninteractive elevation failure.
- Setup copies the production template only when configuration is missing, creates the shared credential through existing credential code, verifies its ACL/validity before task registration, preserves existing config/state/logs, and avoids restarting an already-ready service.
- Doctor compares configured and live GPU power limit, checks upstream reachability, service/miner state, credential ACL, tasks, and configured logs; inaccessible Task Scheduler inventory is reported as unavailable rather than an empty healthy result.
- Teardown refuses to act when coordinator state is unreachable or inference is active/pending; offline destructive recovery remains unfinished.
- `logs miner` and `logs krig` resolve to the single configured miner; unknown process and missing log configuration return distinct errors.
- Focused validation: 35 self-management/config/log tests passed; 10 focused operator-credential tests passed in two subsets; Ruff, Python compilation, `git diff --check`, and PowerShell parsing for the generated task/launcher/viewer scripts passed. The elevated helper carries an allow-listed encoded task operation and the original interactive user's managed root/identity, without relying on a second administrator profile. Setup reports placeholder miner configuration as degraded and reports completed resources on partial failure without exposing credential values; startup task installation is tested not to start the service; optional viewer creation follows the configured miner capture path without mining side effects; teardown requests graceful draining of active/pending work, validates durable state before shutdown, holds the instance lock while decommissioning, and its offline path acquires the lock before reading the journal; tests cover idle recovery, unresolved inference refusal, and refusal to disturb a verified running miner. Doctor reports requested GPU flags separately from observed driver values and validates task identity; log aliases and authorization passed a direct handler test. Actual UAC acceptance, Task Scheduler mutation, full service lifecycle, and integrated ASGI raw-log test attempts remain unverified in this Windows sandbox.
- Log retention follow-up: `test_log_rotation.py` verifies preservation of prior bytes and bounded three-file rotation. Retention + installation + alias validation passed; protected provider/model-switch routing passed 5 regressions. Ruff, `py_compile`, and submodule-safe `git diff --check` passed. Focused `test_service_lifecycle.py` invocation stalled in the first test and was interrupted; no assertion result was produced.
- Doctor/runtime follow-up: implicit process capture paths resolve to the managed log directory, explicit paths remain authoritative, and an unwritable capture parent degrades health. Status reports serving PID, package version, and source path; doctor marks mismatches degraded. It also represents driver observability honestly. Latest installation/config/log/CLI suite passed 47; credential regressions passed 15 with one async service-restart test deselected; protected routing regressions passed 5. Ruff, compilation, and diff checks passed. Package version advanced from 0.8.0 to 0.9.0.
- Gaming/GPU-idle guard: four synchronous cases verify that GPU-idle sampling is suppressed while gaming is stopping, active, restoring, or failed, and that sampling requires the persisted manual hold. The async integration lifecycle remains unexecuted because `asyncio.run(asyncio.sleep(0))` hangs in this runner.
- Manual-control precedence: five states verify that all manual mutations are blocked during gaming/recovery, and four cases verify that timed/manual stop supersedes an older GPU-idle resume condition. The latest combined suite passed 56 RC tests, 15 credential tests (one async excluded), and 5 routing tests; Ruff, compilation, and diff checks passed.
- CLI dry-run acceptance: `setup --json` and `teardown --json` both returned `planned` without mutation. `startup status --json` failed with the exact Task Scheduler CIM access error; actual apply/elevation remains unverified. Read-only doctor confirms configured/effective 550 W and 7001 MHz, valid token ACL, and writable captured log, but coordinator/upstream/task state cannot be read from this sandbox.
- Read-only Task Scheduler verification was blocked by Windows CIM access (`Access to a CIM resource was not available to the client`); no live tasks, coordinator, or miner were changed.
