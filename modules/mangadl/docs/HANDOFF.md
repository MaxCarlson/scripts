# mangadl Immediate Project Handoff

Active branch: `agent/mangadl-gallery-auth`, based on `agent/unified`.

Current version: `mangadl 1.17.0` in the active feature-branch working tree.

Active planning records:

- [Partial safety and merge-readiness plan](plans/20260921-0943_partial-safety-and-merge-readiness/00_implementation-plan.md)
- [Partial safety status](plans/20260921-0943_partial-safety-and-merge-readiness/STATUS.md)
- [Partial safety checklist](plans/20260921-0943_partial-safety-and-merge-readiness/checklist.md)
- [Managed gallery-dl auth plan](plans/20260825-0540_gallery-dl-managed-auth/00_implementation-plan.md)
- [Managed gallery-dl auth stage 1](plans/20260825-0540_gallery-dl-managed-auth/01_profile-and-ua-foundation__planned.md)
- [Managed gallery-dl auth stage 2](plans/20260825-0540_gallery-dl-managed-auth/02_browser-refresh-and-probe__implemented.md)
- [Managed gallery-dl auth stage 3](plans/20260825-0540_gallery-dl-managed-auth/03_managed-runtime-retry__in-progress.md)
- [Managed gallery-dl auth stage 4](plans/20260825-0540_gallery-dl-managed-auth/04_target-catalog-and-progress__planned.md)
- [Managed gallery-dl auth stage 5](plans/20260825-0540_gallery-dl-managed-auth/05_gallery-dl-output-integrity__planned.md)
- [Managed gallery-dl auth stage 6](plans/20260825-0540_gallery-dl-managed-auth/06_destination-root-series-layout__planned.md)
- [Managed gallery-dl auth stage 7](plans/20260825-0540_gallery-dl-managed-auth/07_input-wide-auth-preflight__planned.md)
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
managed gallery-dl authentication S1-S4 is implemented and validated on this
feature branch. S5 corrected the global naming override, embedded gallery-dl
errors, HTTP retry classification, and concurrent partial-merge race exposed
by the first real multi-URL run. Version 1.14.1 passes 146 tests; one-worker and
four-worker live Mangakakalot downloads now complete with distinct images. S6
is active to remove gallery-dl's category wrapper during the final merge so
series folders live directly inside the selected destination. The latest
25-URL manual acceptance run additionally exposed blocking TUI auth refresh,
stale same-domain worker credentials after replacement, inconvenient required
control-path arguments, and raw-JSON-only dry-run output; these are now part of
the active S6 completion boundary. The code remediation now passes 158 offline
tests plus compile/Ruff and local no-write dry-run checks; user-controlled live
acceptance remains pending.

Version 1.16 adds a default refusal for broad gallery-dl collection URLs with
an explicit `-G/--allow-collection` opt-in. New partials contain versioned
ownership metadata and exact archive-key/path manifests. `mangadl partials
clean` previews archive-aware cleanup and applies it only with `--apply`, with
archive deletion ordered before filesystem deletion. Legacy partials are
refused unless the user explicitly selects files-only cleanup. The dashboard's
raw-log view now reads a bounded file suffix rather than rereading the entire
log every refresh, addressing the concrete full-UI freeze path found in the
September 21 run.

`mangadl partials clean` now owns its interactive TermDash tree rather than
delegating deletion to `file_utils`. With no explicit target it supports
expand/collapse, hierarchical sorting, URL/ownership details, and multi-select
of top-level partial owners. Explicit repeatable `-t` targets remain available.

For legacy owners without manifests, the command can recover URLs from local
state (or validated URL overrides), enumerate exact archive keys through a
no-download gallery-dl metadata pass, and delete matching rows from an explicit
archive before deleting files. It refuses active/recently changing trees and
rechecks the preview fingerprint immediately before archive mutation.

The live `fc7c3b753cc0` investigation found gallery-dl PIDs 30028/14992 still
running the broad collection after the manager had been interrupted. The real
tree grew from the user's 35,276-file preview to more than 36,700 files during
read-only inspection. Cleanup correctly refuses it as recently active; no
`B:` archive, state, or partial data was changed.

The 1.16 baseline merge-readiness evidence is green at 170 tests plus compile,
Ruff, CLI help, and the repository `mangadl` validation target. The 1.17 full
validation result is recorded in the active stage status. The remaining boundary is
manual: live-check one normal gallery-dl series for destination-root layout and
responsive log controls. Staging, commit, push, and continued integration work
were approved on 2026-09-21; final merge still requires review. S7 remains
blocked on the existing S6 live acceptance.
