# ytaedl Plan Index

Canonical plan registry for `modules/ytaedl`. User-authored inputs live in
`user/`; AI interpretations, implementation plans, and status notes live in
`ai/`. Reusable permanent templates live under `ai/perma/`.

## Naming

`<index>_<yyyymmdd-HHMM|yyyymmdd-unknown>_<origin>_<slug>__<status>.md`

Statuses: `planned`, `in_progress`, `implemented`, `partial`, `superseded`,
`deferred`.

## Registry

| Index | Origin | Status | File | Source | Notes |
| --- | --- | --- | --- | --- | --- |
| 0001 | user | superseded | `user/0001_20260509-unknown_user_99xx-percent-stuck-report__superseded.md` | `99_xx_percent_stuck_plan.md` | Original 99.xx percent stuck report; superseded by Plan +1. |
| 0002 | user | partial | `user/0002_20260509-unknown_user_versioning-and-scripts-cohesion-request__partial.md` | `versioning_and_scripts_cohesion_plan.md` | Versioning and CLI instruction request; mostly implemented, remaining bootstrap repair tracked by Plan +2. |
| 0003 | ai | implemented | `ai/0003_20260509-unknown_ai_claude-latest-plan__implemented.md` | `latest_plan_claude.md` | Claude latest plan; current implementation and tests treated it as implemented. |
| 0004 | ai | implemented | `ai/0004_20260509-unknown_ai_codex-followup-current-plan__implemented.md` | `current_plan.md` | Codex follow-up plan/status before Plan +1/+2; implemented or superseded by this registry. |
| 0005 | ai | implemented | `ai/0005_20260509-1700_ai_codex-plan-plus-1-ytaedl-runtime-hardening__implemented.md` | user request 2026-05-09 | Runtime hardening: attempt IDs, stale progress rejection, help version text, and log audit helper. |
| 0006 | ai | implemented | `ai/0006_20260509-1700_ai_codex-plan-plus-2-bootstrap-aebndl-install__implemented.md` | user request 2026-05-09 | Bootstrap/aebndl install repair: canonical package skip, locked exe diagnostics, invalid leftover detection. |
| 0007 | ai | implemented | `ai/0007_20260509-unknown_ai_codex-status-note__implemented.md` | `status.md` | Prior short status note retained for history. |
| 0008 | ai | partial | `ai/0008_20260509-1653_ai_codex-plan-session-note__partial.md` | `5_9_2025_16_53_plan.md` | Later user note about possible ffmpeg metadata/duration use; retained as future investigation. |
| 0009 | ai | planned | `ai/0009_20260509-1745_ai_codex-run-clean-start-flags__planned.md` | user request 2026-05-09 | Future explicit log-dir reset flag near `-M`; must not touch archive or `_partial/` resume state. |
| 0010 | ai | implemented | `ai/0010_20260509-1756_ai_codex-log-archive-ui-test-execution__implemented.md` | copied runtime artifacts 2026-05-09 | Executed the permanent log/archive/UI manual testing template against this run. |
| 0011 | ai | implemented | `ai/0011_20260622-1156_ai_codex-explicit-urlfile-workers-and-locking__implemented.md` | user request 2026-06-22 | Exact `-p/--priority-files` workload mode, one worker per file, and worker-owned cross-process URL-file locks. |

## Permanent Templates

| Template | File | Purpose |
| --- | --- | --- |
| log/archive/UI testing | `ai/perma/log_archive_ui_testing_plan.md` | Reusable template for future copied logs/archive plus UI snapshot review sessions. |
