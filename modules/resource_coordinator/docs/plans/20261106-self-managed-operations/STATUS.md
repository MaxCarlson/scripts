# Status — Self-Managed Operations

## Current checkpoint

- [x] Verified current source of truth and merged mainline state.
- [x] Rechecked live coordinator/miner state, startup task privilege, GPU settings, and log endpoint.
- [x] Implement dry-run-first setup/startup CLI scaffolding and mock-backed manager paths.
- [ ] Complete Windows task privilege/elevation validation and fresh-install repair coverage.
- [x] Implement health doctor and bounded repair CLI dispatch (offline code path).
- [ ] Complete safe teardown when a running owned miner must be stopped offline; current fallback removes startup artifacts only after the instance lock and journal prove idle, and refuses if an owned miner is still alive.
- [x] Fix miner log alias and distinguish unknown process from missing log.
- [x] Add optional read-only post-login output viewer managed by the startup task backend.
- [ ] Revalidate existing controls, integrations, gaming, and GPU-idle behavior.
- [ ] Implement TUI last, after all previous gates pass.

## Last verified live state

At 2026-11-06 03:48 local: coordinator ready from `main`, KRig PID 73392 coordinator-owned, active/pending inference 0/0, logon task enabled at Highest, NVIDIA RTX 5090 power limit 550 W and memory clock 7001 MHz. `logs krig_miner` returned captured output without NVML permission warnings. `logs krig` was not tested in this session and is expected to fail until alias support is implemented.

## Next action

Continue setup/teardown recovery tests and operational diagnostics, then audit existing manual controls, gaming, and GPU-idle behavior before the final TUI phase. Preserve the dirty handoff document and unrelated untracked paths in the root checkout.

## Work completed in current execution

- Added top-level `setup`, `doctor`, `repair`, `teardown`, and `startup` command dispatch.
- Added configuration environment overlays for managed state and append-only log paths without overwriting explicit user configuration.
- Added a Windows task backend with a fixed operation allow-list, ownership checks, duplicate-trigger suppression, and explicit noninteractive elevation failure.
- Setup copies the production template only when configuration is missing, creates the shared credential through existing credential code, verifies its ACL/validity before task registration, preserves existing config/state/logs, and avoids restarting an already-ready service.
- Doctor compares configured and live GPU power limit, checks upstream reachability, service/miner state, credential ACL, tasks, and configured logs; inaccessible Task Scheduler inventory is reported as unavailable rather than an empty healthy result.
- Teardown refuses to act when coordinator state is unreachable or inference is active/pending; offline destructive recovery remains unfinished.
- `logs miner` and `logs krig` resolve to the single configured miner; unknown process and missing log configuration return distinct errors.
- Focused validation: 34 self-management/config/log tests passed; 10 focused operator-credential tests passed in two subsets; Ruff, Python compilation, `git diff --check`, and PowerShell parsing for the generated task/launcher/viewer scripts passed. Setup reports placeholder miner configuration as degraded and reports completed resources on partial failure without exposing credential values; startup task installation is tested not to start the service; optional viewer creation is covered without mining side effects; teardown requests graceful draining of active/pending work, validates durable state before shutdown, holds the instance lock while decommissioning, and its offline path acquires the lock before reading the journal; tests cover idle recovery, unresolved inference refusal, and refusal to disturb a verified running miner. Doctor reports requested GPU flags separately from observed driver values and validates task identity; log aliases and authorization passed a direct handler test. Full service lifecycle and integrated ASGI raw-log test attempts stalled in the Windows sandbox before producing assertions, so those runtime paths remain unverified here.
- Read-only Task Scheduler verification was blocked by Windows CIM access (`Access to a CIM resource was not available to the client`); no live tasks, coordinator, or miner were changed.
