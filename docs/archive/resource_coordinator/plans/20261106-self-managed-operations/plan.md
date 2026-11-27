# Resource Coordinator Self-Managed Operations

## Goal

Make the integrated Resource Coordinator installation inspectable and manageable through its CLI while preserving existing configuration, durable state, credentials, logs, and unrelated Windows tasks.

## Current evidence

- Repository: `scripts`, branch `main`, HEAD `9c01c700eb9a1bb557399fce47c143837a75e2cf`.
- The merged Resource Coordinator implementation is in `main`; the historical feature worktree is not the source of truth.
- Live coordinator uses the root `main` package, is ready on `127.0.0.1:1235`, and currently owns KRig PID 73392. Inference active/pending counts are 0/0.
- The logon task is enabled and `Highest`; NVIDIA reports a 550 W limit and 7001 MHz memory clock. Captured log reads work by the configured process name `krig_miner`; the documented `logs krig` alias still needs correction.
- LM Studio is externally owned at `127.0.0.1:1234`. The viewer is a separate user task. No boot task was found in the last task inventory.
- Existing config, journal, token, launcher, and logs live outside the repository under `%USERPROFILE%\\.resource_coordinator`; the current launcher imports the shared `main` checkout.

## Implementation sequence

1. Add focused inventory and CLI behavior tests before implementation.
2. Implement a dry-run-first installation manager with safe paths, non-overwriting config/credential behavior, startup task inspection/repair, allow-listed elevation operations, setup, startup subcommands, doctor, and degraded-mode teardown.
3. Fix canonical miner log-name resolution and distinguish unknown process from absent/unreadable capture; add alias coverage and update CLI documentation.
4. Add operational diagnosis for source/task identity, effective NVIDIA configuration, port/upstream health, credential ACL, leases, and routing where a read-only local probe is available.
5. Audit and harden existing controls, gaming, bridge routing, viewer behavior, and GPU-idle behavior without creating a second supervisor.
6. Implement the TUI only after stages 1–5 have focused validation.

## Safety boundaries

- Setup is preview-only unless `--apply` is supplied; existing user configuration is never overwritten.
- Teardown defaults to preserving user config, credentials, journal, logs, model files, and external applications.
- Task management targets only named RC-owned tasks. Disabling startup does not stop a running service.
- Privileged helpers accept an operation enum and validated paths, never arbitrary shell text.
- No live process, task, routing, model, or GPU mutation is part of offline tests.

## Acceptance gates

- Fresh, repeated, partial, and interrupted setup tests are idempotent and preserve existing files.
- Startup task commands operate only on RC task names and expose dry-run/apply behavior.
- Doctor reports healthy, degraded, and blocked states independently; HTTP 200 alone is insufficient.
- Teardown drains/stops only owned processes and has an offline recovery path.
- Focused Python tests, Ruff, diff checks, and bounded Windows task-helper tests pass before each checkpoint.
- The existing live miner remains untouched while implementation and offline validation proceed.
