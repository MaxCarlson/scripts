# Partial Safety and Merge Readiness Handoff

Branch: `agent/mangadl-gallery-auth`

Current stage: offline-complete; stopped for user manual acceptance.

The pre-existing S6 implementation is staged. New plan work must remain
distinguishable until reviewed and must not disturb live paths under `B:`.

Baseline verification before this plan: `158 passed` with one pytest cache
permission warning. The concrete freeze finding is `ui.read_log_lines()`, which
currently reads the entire selected activity/raw log every dashboard refresh.

Implemented changes gate broad collection extractors, track exact archive
ownership for new partials, add dry-run-first archive-aware cleanup, and bound
raw-log reads. The generic file-utils lister was not given a generic delete key:
deletion must stay behind mangadl's ownership/archive validation. Focused tests
pass. Verification is green: 170 module tests; compile and Ruff pass; the root
`mangadl` dispatcher target passes; scripts-help registry tests pass 42/42 with
a module-local basetemp. The user approved staging, commit, push, and continued
integration work on 2026-09-21. Remaining blockers are the existing S6 live
layout/TUI acceptance, integration-branch review, and final merge approval. S7
remains intentionally blocked until S6 acceptance.
The accidental legacy partial predates manifests and can only use explicit
files-only cleanup; exact historical archive rollback is unavailable. A
read-only preview found 34,220 files totaling 13,694,065,861 bytes and made no
changes.
