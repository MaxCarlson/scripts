# Resource Coordinator Part 3 — Verified Recovery

## Objective

Implement V3 Part 3 from the verified Part 2 candidate. Keep automatic recovery limited to request-specific, authoritative termination evidence. Preserve operator override as a separate authenticated path and leave unattended recovery disabled.

## Source baseline and boundaries

- Part 2 candidate: `19255b2e90b7a8904ddf324856687bc40c5e30d4`.
- `origin/main` at start: `4f4373d2533e4e0c6bd115eda6623ed65fbadc49`.
- Part 2 source integration into `main` was not authorized by the handoff. This branch therefore starts from Part 2; `main` remains untouched.
- V3 is authoritative and must remain unchanged. Its SHA-256 is `BA842936C9DE945EE8463FD41C3E60491A5714DCA1CF481064DC915DBF516F46` and Git blob is `3a1c2f7662a54469bb6dc15ad6462a4295ec93e6`.
- No production service, miner, GPU, LM Studio, WSL, credential, or Scheduled Task operations.

## Execution sequence

1. Establish Part 2 source/H3 protocol equivalence and capture current Part 3 test baselines.
2. Add serialized journal transactions, monotonic revision, compatible deserialization, and tested rollback export semantics.
3. Canonicalize startup inhibition holders durably and fail closed on incomplete restoration; correct AccessDenied/PID identity reconciliation.
4. Add explicit reconciliation dispositions and a single durable request-plus-holder reconciliation transaction.
5. Add a bounded GPU recovery fence and authenticated `POST /_coordinator/recovery/auto` with unlocked bounded observations, exact revision/generation revalidation, and cancellation-safe cleanup.
6. Permit automatic clearance only for durably proven not-forwarded requests or later authoritative protocol completion. Keep forwarded/unknown execution operator-required; do not qualify Case C on this host.
7. Repair the persisted GPU-idle/manual-override startup defect without erasing intentional operator holds; investigate the historical gateway timing failure.
8. Connect `rc recover --apply` to the verified endpoint, test no-op/offline/auth/error paths, document readiness and rollback limits, run regression/static checks, commit checkpoints, and push the feature branch.

## Acceptance

Follow V3 Part 3 §§3.1–3.6 and the current handoff's safety matrix. Every failure test must inspect durable requests and holders, in-memory lease holds/fence, service state, process identity, and restart eligibility as applicable. No idle snapshot, elapsed time, frontend PID exit, or client flag is termination evidence.
