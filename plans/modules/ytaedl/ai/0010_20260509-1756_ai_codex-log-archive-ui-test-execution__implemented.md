---
plan_index: 0010
origin: ai
status: implemented
source_file: user_runtime_artifacts_20260509_1756
template: ai/perma/log_archive_ui_testing_plan.md
---

# Log/Archive/UI Test Execution: 2026-05-09 17:56 Run

## Run Inputs

- Working directory: `D:\Pictures\Saved\tmpvids\ytaedl_confinement`.
- Command: `ytaedl run -t 8 -P B:\stars\ -s ..\files\downloads\stars\ -d ..\files\downloads\ae-stars\ -a .\archive -v 2k -D 2 -M -L ..\stars\`.
- User deleted `logs/` and `archive/` before the run.
- `_partial/` directories under `B:\stars\...` were preserved.
- Run was stopped/killed after a short observation window.
- Copied artifacts:
  - `modules/ytaedl/logs/new_logs/`
  - `modules/ytaedl/logs/new_archive/`

## Executed Checks

- Ran `python -m ytaedl.log_audit` against copied logs/archive.
- Inspected manager log startup and fallback progression.
- Inspected `ytaedler-worker-06.log` because the UI snapshot selected worker 6 during fallback churn.
- Inspected archive rows.

## Findings

- Domain index was rebuilt: 25 domains, 3811 total queued URLs, 0 finished.
- Manager promoted 196 `_partial/` URLs to the front of domain queues.
- `D:2` domain cap appeared respected in the snapshot and manager logs: active same-domain counts were `active=0/2` or `1/2` during scans.
- No tracebacks were found.
- No `_TPL_` hits were found in manager/worker logs for this copied run.
- Archive contains only `stalled` rows, which is consistent with a short killed run and no completed URLs.
- Worker 6 repeatedly stalled on Pornhub fallback candidates with `pre_transfer_no_output`; the UI correctly showed fallback phase text rather than stale `99.x%` progress.
- The UI snapshots did not show the old stuck-percent failure.

## Follow-up Notes

- `_TPL_` still appears in `urlscan-latest.json` as a discovered existing filename, not as a manager/worker destination in this run. Treat that as a separate URL-scan/data-quality investigation only if it affects selection or duplicate behavior.
- Future log-reset flag must be independent of `-M`; either flag alone or both together must not touch `_partial/` resume state.

