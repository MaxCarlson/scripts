

## Operational diagnostics checkpoint

Status: implemented and validated on the same feature branch; committed after final verification. Root-cause findings are recorded in `docs/operational-diagnostics/ROOT_CAUSE_FINDINGS.md`. The incident cause remains unconfirmed because the failing operation/traceback was unavailable. `llmd doctor` is read-only and `llmd recover` only associates a durably captured exact ID.

Validation: `python -m pytest -q --basetemp=.pytest_tmp_root/ops-final-full`; `python -m ruff check agent_continuity/dispatcher.py agent_continuity/dispatcher_cli.py tests/dispatcher_ops_test.py`; `git diff --check`.

Checkpoint: operational diagnostics changes are committed locally. No push or merge.

## Independent review corrections

Status: implemented in a separate local review-fix checkpoint. Picker preview no longer persists inactive-agent reactivation; direct continuation checks current lock contention before lifecycle or activation-history updates. Runtime ownership requires the persisted environment ID plus matching runtime kind, host, and WSL distribution when applicable; uncertain ownership reports `UNKNOWN` and blocks recovery. `llmd doctor` now renders human-readable text while retaining JSON schema version 1. Package version is 1.3.1.

Validation: focused diagnostics, picker, and CLI regression tests passed; full module suite passed; Ruff and `git diff --check` passed. No provider launches or live registry operations were used.
