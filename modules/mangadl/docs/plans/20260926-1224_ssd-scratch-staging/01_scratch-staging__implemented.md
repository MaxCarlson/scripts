# Stage 1 — Scratch staging and guarded promotion

Implementation boundary: CLI, manager, worker, partial-cleanup path routing, recoverable promotion, tests, and docs. No production drive writes or live downloads.

Verification: run module pytest suite, Ruff, compileall, and a no-write CLI preview. Manual acceptance is required before calling the feature production-proven.
