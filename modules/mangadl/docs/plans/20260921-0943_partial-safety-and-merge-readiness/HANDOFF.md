# Partial Safety and Merge Readiness Handoff

Branch: `agent/mangadl-gallery-auth`

Current stage: implementation and validation complete; integration review.

The S6 and S4 implementations are committed on the feature branch. Final work
must remain distinguishable until reviewed and must not disturb live paths
under `B:`.

Baseline verification before this plan: `158 passed` with one pytest cache
permission warning. The concrete freeze finding was `ui.read_log_lines()`,
which read the entire selected activity/raw log every dashboard refresh; it now
reads a bounded suffix.

Implemented changes gate broad collection extractors, track exact archive
ownership for new partials, add dry-run-first archive-aware cleanup, and bound
raw-log reads. The generic file-utils lister was not given a generic delete key:
deletion must stay behind mangadl's ownership/archive validation. Focused tests
pass. Verification is green: 182 module tests; compile and Ruff pass; the root
`mangadl` dispatcher target passes; scripts-help registry tests pass 42/42 with
a module-local basetemp. The user approved staging, commit, push, and continued
integration work on 2026-09-21. Live isolated runs now verify direct
destination-root layout and responsive activity/raw-log switching. Remaining
blockers are integration-branch review and final merge approval. A current
four-URL/four-worker run completed 4/4 chapters without a retry; S7 remains
intentionally blocked only on its potentially large complete-series gate.

The accidental legacy partial predates manifests, but version 1.17 can recover
its URL and reconstruct exact archive keys through a no-download metadata pass
when an explicit archive is supplied. A latest files-only read-only preview
found 41,957 files totaling 17,073,852,121 bytes and made no changes.
