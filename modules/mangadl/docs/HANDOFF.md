# mangadl Immediate Project Handoff

The active work is the native Manga18FX backend on `agent/add-manga18fx-backend`, based on `agent/add-development-ledger-module`.

Active files: [plan](plans/20260729-1307_manga18fx-backend/00_implementation-plan.md), [status](plans/20260729-1307_manga18fx-backend/STATUS.md), [checklist](plans/20260729-1307_manga18fx-backend/checklist.md), and [handoff](plans/20260729-1307_manga18fx-backend/HANDOFF.md).

The backend recognizes `manga18fx.com/manga/<slug>` series URLs, parses all chapter/image links, downloads into per-job partial directories, and merges successful manga/chapter folders into the destination root. The existing `-C/--cookies` Netscape/Mozilla cookies-file option is supported.

The user confirmed that a Manga18FX URL file downloads correctly on Windows 11. Windows pytest base-temp setup and the environment-dependent gallery-dl routing test have been corrected on the branch. The complete mangadl pytest suite must be rerun after pulling the latest commits; merge into `main` remains unauthorized until that suite passes.
