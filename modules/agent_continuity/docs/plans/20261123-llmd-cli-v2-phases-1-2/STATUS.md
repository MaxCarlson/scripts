

## Operational diagnostics checkpoint

Status: implemented and validated on the same feature branch; committed after final verification. Root-cause findings are recorded in `docs/operational-diagnostics/ROOT_CAUSE_FINDINGS.md`. The incident cause remains unconfirmed because the failing operation/traceback was unavailable. `llmd doctor` is read-only and `llmd recover` only associates a durably captured exact ID.

Validation: `python -m pytest -q --basetemp=.pytest_tmp_root/ops-final-full`; `python -m ruff check agent_continuity/dispatcher.py agent_continuity/dispatcher_cli.py tests/dispatcher_ops_test.py`; `git diff --check`.

Checkpoint: operational diagnostics changes are committed locally. No push or merge.
