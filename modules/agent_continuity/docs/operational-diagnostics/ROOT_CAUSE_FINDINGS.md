# LLMD lock timeout investigation

## Confirmed from current code

- `begin_launch` holds `dispatcher.lock` only while synchronizing and appending launch/environment events. The lock is released before dispatch calls `_run_pane`.
- `_run_pane` provider bootstrap and resume use `subprocess.run` outside the registry mutation lock. A separate session-keyed lock surrounds the known-session provider process; it is released before process-observation metadata writes.
- `record_process_observation`, attach, and launch state changes each acquire the registry lock for short event writes. Their callers do not hold the registry lock across provider execution.
- Parent `llmd start` submits/records a pending launch, then invokes `pane-run`; `pane-run` reads the slot and pending row, writes a bootstrap-start observation, launches the provider, records captured ID, associates it, then resumes it.

## Root cause status

The reported registry-lock timeout cannot be attributed to the visible Codex process from the available incident evidence. The lock is not held by the normal provider wait path. A timeout can occur at any short metadata mutation (including observations after a subprocess returns); the snapshot did not include the failing operation or traceback. A visible `pane-run` and Codex process therefore indicate that launch progressed, but do not identify which later metadata write failed. Do not infer a stale lock from the timeout.

The highest-risk persistence boundary is successful bootstrap followed by failure to persist the captured ID or activation. The provider may have created a billable session while LLMD still sees a pending launch. Automatic retry is unsafe; inspect the provider session and attach its exact ID. `llmd doctor` and `llmd recover` provide bounded inspection and only recover when one exact ID was durably captured.
