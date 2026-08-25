# mangadl Immediate Project Handoff

Active branch: `agent/mangadl-gallery-auth`, based on `agent/unified`.

Current version: `mangadl 1.13.0` on the active feature branch.

Active planning records:

- [Managed gallery-dl auth plan](plans/20260825-0540_gallery-dl-managed-auth/00_implementation-plan.md)
- [Managed gallery-dl auth stage 1](plans/20260825-0540_gallery-dl-managed-auth/01_profile-and-ua-foundation__planned.md)
- [Managed gallery-dl auth stage 2](plans/20260825-0540_gallery-dl-managed-auth/02_browser-refresh-and-probe__implemented.md)
- [Managed gallery-dl auth stage 3](plans/20260825-0540_gallery-dl-managed-auth/03_managed-runtime-retry__in-progress.md)
- [Managed gallery-dl auth status](plans/20260825-0540_gallery-dl-managed-auth/STATUS.md)
- [Managed gallery-dl auth checklist](plans/20260825-0540_gallery-dl-managed-auth/checklist.md)

Historical planning records:

- [Manga18FX plan](plans/20260729-1307_manga18fx-backend/00_implementation-plan.md)
- [Manga18FX status](plans/20260729-1307_manga18fx-backend/STATUS.md)
- [Manga18FX checklist](plans/20260729-1307_manga18fx-backend/checklist.md)
- [Manga18FX handoff](plans/20260729-1307_manga18fx-backend/HANDOFF.md)
- [CLI/optimizer/archive plan](plans/20260729-1630_cli-optimizer-archive/PLAN.md)
- [CLI/optimizer/archive status](plans/20260729-1630_cli-optimizer-archive/STATUS.md)

Implemented scope includes the native Manga18FX backend; destination-aware resume; bounded inner image concurrency; safe/staggered outer workers; runtime concurrency controls; cumulative native progress; aligned two-row dashboard output; concise `run`, `optimize`, `benchmark`, and nested `config` command surfaces; online adaptive optimization and systematic benchmarking; and an interactive archive browser.

The user confirmed live Manga18FX downloads and approximately 15-17 MiB/s aggregate throughput with four outer workers. A fifth outer worker saturates the current destination disk and remains outside the safe default ceiling.

The pre-existing Manga18FX local validation notes remain historical. Generic
managed gallery-dl authentication is implemented and validated on this feature
branch. Offline verification passes with 133 tests and installed version 1.13.0.
Live exact-target Chrome capture plus gallery-dl simulation passed, and a normal
URL-file dry-run automatically routed the acceptance URL to gallery-dl. The
feature is ready to commit/push; merging remains a separate approval boundary.
