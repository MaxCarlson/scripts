# Status

Integration branch: `integrate/qwen-runtime-investigation-20261029`

Base: `origin/main` at `eeb40e8468d5fb33816caa5a8ec45f20b639c4f8`.

Source: `experiment/qwen-runtime-investigation-20261029` at `6a0899213329dae023157ae71d137199fc4cdd4c`.

Current stage: completed the committed-evidence inventory and sensitive-field scan; ported the Agent Benchmark patch, runtime operations guide, optional proxy and reusable condition files. Added integration regressions for short CLI aliases and malformed profile/proxy identifiers, fixing each issue with a red-green check. No local inference has been run.

Audit result: 138 committed evidence paths included one SQLite database. Structured reports had no prompt-sized string values, credential payloads or tool-argument values. The database passed a read-only integrity check and contained normalized telemetry fields, including session IDs, but no prompt/response body columns, credentials or user paths. Generated run records and Markdown include session identifiers and user-specific Windows paths; all are excluded from this integration and remain in the published source branch history. The published branch was not rewritten.

Validation passed against the exact curated source tree (`6ece603760417f35c3129a83bb8f8e9a7f4d581b`) in a short-path checkout: Agent Benchmark `411 passed, 3 skipped`; Benchmark Core tests passed; request-capture proxy `6 passed`; Ruff passed. Focused regressions also passed for new CLI aliases, malformed profile/proxy values, Qwen verifier fixtures and the synthetic-Git fixture. Mypy passed for the new profile/overlay/identity modules; broader documented checks still report unrelated existing `benchmark_core`, `termdash` and dynamic `resource_metrics` diagnostics. `git diff --cached --check` passed. No local inference has been run.

Integration commit: `e03bfc529ed8eaf306c983aeb1d6265770b56bb0`.

Merge commit pushed to `origin/main`: `a791c65f28b40e6f89157525c5e42622fb1498e3`. The pushed tree matches the validated integration tree. Post-merge diff and artifact checks passed. The original dirty `main` checkout and source investigation worktree, including raw local evidence, remain preserved and untouched by integration operations.
