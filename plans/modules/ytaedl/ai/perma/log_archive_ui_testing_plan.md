---
origin: ai
status: permanent_template
template_name: log_archive_ui_testing_plan
applies_to: modules/ytaedl
---

# ytaedl Log/Archive/UI Manual Testing Template

Use this template when a run produces the same evidence bundle format:

- UI screenshots or copied terminal snapshots.
- Copied logs under `modules/ytaedl/logs/new_logs/`.
- Copied archive files under `modules/ytaedl/logs/new_archive/`.
- The exact command and working directory used for the run.
- Notes about whether the run was stopped cleanly, killed, or allowed to finish.

## Inputs To Capture

Record these facts in the execution plan:

- Command:
  `ytaedl run ...`
- Working directory.
- Whether `logs/` and/or `archive/` were deleted before the run.
- Whether `-M/--rebuild-domain-index` was used.
- Whether any future log-reset flag was used.
- Whether `_partial/` directories were preserved.
- Whether Python/aebndl/yt-dlp processes were quit cleanly or killed.
- UI snapshot timing, especially early-run and post-fallback snapshots.

## UI Snapshot Checks

For each screenshot/snapshot, extract:

- Header: `threads`, `active`, `pool`, elapsed time, started/done/duplicate URL counts.
- Domain state: `D:N`, active domains, unique domain count, and whether per-domain cap looks respected.
- Storage state: staging free/total, destination free/total, buffer, ETA.
- Worker rows: slot, source file, URL count, elapsed, percent, speed, ETA, domain, bytes.
- Phase text rows: simulate/fallback discovery/candidate messages.
- Verbose pane: selected worker, event names, `attempt_id`, raw destination paths, progress fields.

Flag suspicious UI behavior:

- fallback/simulate row displays stale near-complete progress instead of phase text.
- live `100%` appears before terminal completion.
- a worker changes URL but keeps old percent/speed/ETA.
- `D:N` domain cap appears exceeded for the same base domain.
- destination path contains `_TPL_`.
- aggregate speed/ETA is obviously impossible and not explainable by resumed local bytes.

## Log Audit Commands

Run:

```powershell
.\.venv\Scripts\python.exe -m ytaedl.log_audit -g modules\ytaedl\logs\new_logs -a modules\ytaedl\logs\new_archive
```

Then inspect focused logs:

```powershell
rg -n "Traceback|ERROR|_TPL_|FALLBACK_EXHAUSTED|FALLBACK_STALLED|REQUEUE|DOWNLOAD_FAIL|SIMULATE|attempt_id" modules\ytaedl\logs\new_logs modules\ytaedl\logs\new_archive
Get-Content modules\ytaedl\logs\new_logs\dlmanager-*.log
Get-Content modules\ytaedl\logs\new_logs\ytaedler-worker-06.log
Get-Content modules\ytaedl\logs\new_archive\*.txt
```

Use worker 6 only as an example; pick any worker that the UI snapshot shows as suspicious.

## Artifact Consistency Checks

Expected healthy signals for a short killed run:

- `domain_index.json` exists if `-D` was enabled.
- `domain_index.json` may have `finished=0` immediately after a fresh `-M` run.
- archive may contain only `stalled` rows if the run was stopped before completions.
- no tracebacks.
- no `_TPL_` destinations in manager/worker logs.
- `_partial/` URLs are promoted if partial dirs were preserved.

Potential issues:

- archive contains `downloaded`/`already` rows for URLs that logs show as failed.
- manager log repeatedly requeues the same URL without backoff or terminal status.
- fallback candidate URLs are malformed in a way that points to parser escaping bugs.
- raw logs show media candidates that should have been accepted but were treated as failed.
- domain index marks partial URLs as finished or permanently failed after a killed run.

## Output Format

Each manual test execution plan should end with:

- Summary of command/run state.
- UI observations.
- Audit counts.
- Archive/domain-index consistency.
- Suspected bugs.
- Non-bugs / expected behavior.
- Follow-up implementation plan entries, if needed.

