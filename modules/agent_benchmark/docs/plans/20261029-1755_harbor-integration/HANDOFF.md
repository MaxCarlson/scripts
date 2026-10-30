# Current Harbor worktree checkpoint (2026-10-30)

Active worktree: `C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755`, branch `harbor-integration-20261029-1755`, base `33040f00`. No commit, merge, or push was authorized.

Phase C completed: Qwen scored 7/10 (70%) on the frozen Aider Polyglot task set, with 10/10 scored trials and no canonical infrastructure errors. The exact task list, revision, model, quantization, context, endpoint, tool protocol, digests, run IDs, token totals, and limitations are recorded in `reports/harbor/qwen-baseline-10/`. Codex/Antigravity protocol is prepared there; no cloud inference ran.

Terminal-Bench provenance audit corrected the catalog. The preserved Oracle job used Terminal-Bench 2.0 (`terminal-bench/terminal-bench-2`, 89 tasks) from `laude-institute/terminal-bench-2` at `69671fbaac6d67a7ef0dfec016cc38a64ef7a77c`; Terminal-Bench 4.0.0 is separate (66 tasks, source release `v4.0.0`). Corrected derived import is `reports/harbor/tb-pilot-corrected/`. Original primary-checkout `.harbor-jobs/` and `reports/` remain untouched.

Resource review confirms 1 CPU, 2 GB RAM, and 10 GB storage for four of the five CPU subset tasks (`build-cython-ext`, `regex-log`, `sqlite-db-truncate`, `nginx-request-logging`). The `log-summary-date-ranges` page omits resource fields; the preserved pilot does not contain its task TOML. Check that exact pinned TOML and numeric timeout before any future Terminal-Bench run.

Validation for this addendum: Harbor-focused suite 37 passed. The Oracle `build-cython-ext` reward is invalid for agent-capability interpretation because the upstream pyknotid reference test failed; the native logs do not record the installed planarity package version. See the corrected report note and plan status for detail.

Next: obtain authorization before external Codex or Antigravity inference; use the prepared exact-task protocol without changing the task set.
