# Runtime resource policy checklist

- [x] Remove implicit 90% host RAM rejection/cancellation.
- [x] Remove fixed 4 GiB available-RAM floor from default dispatch checks.
- [x] Review and replace arbitrary GPU/combined reserves and model-size multiplier.
- [x] Keep explicit user-configured percentage limits effective end to end.
- [x] Add tests for default behavior, explicit thresholds, estimate capacity, missing telemetry,
      allocation failure, and no blind retry.
- [x] Update docs and version.
- [x] Run focused tests and lint.
- [x] Commit/push the RAM-policy milestone (`d1e6342a`, isolated investigation branch).
- [x] Analyze B1 visibility-resume and single-flight implementation failures.
- [x] Compare matched B1 `none`, invariant-checklist, and one-repair workflows; retain the first
      attempt verdicts and report first-attempt/recovery outcomes separately.
- [x] Validate a live Monitor observation against persisted inference history; retain the
      effective-options/outbound-parameter provenance gap.
- [x] Diagnose Monitor `found=false`: two earlier sessions had no recorder; two later sessions
      were queried from the wrong database. Correct per-run database queries return complete
      history with zero gaps.
- [ ] Validate and publish the allowlisted overlay/task/report checkpoint; exclude raw runs,
      session data, prompts, and telemetry databases.
