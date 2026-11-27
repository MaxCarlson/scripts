# Resource Coordinator Part 2 Implementation Plan

> This is the execution ledger for V3 Part 2, not a replacement or revision of the master roadmap.

**Goal:** Deliver the backward-compatible `rc` CLI, accurate unified status and telemetry, dedicated maintenance reconciliation, and conservative read-only inference/recovery assessment.

**Architecture:** Preserve existing service, gateway, durable-state, and operator-auth boundaries. Consolidate parsing/dispatch and structured result rendering; add read-only inference aggregation, optional no-wake runtime observation, and recovery assessment. Automatic inference recovery mutation, journal revisions, startup-holder canonicalization, and the two-stage recovery transaction remain Part 3 work.

**Source specification:** `docs/plans/20261111-consolidated-roadmap/MASTER_IMPLEMENTATION_PLAN_V3.md`, Part 2.

## Global constraints

- Keep root `recover -r <resource> -n <reason>` and `service recover --resource <resource> -r <reason>` distinct; no value heuristics.
- Bump package metadata and `__version__` together to `1.0.0`; do not reinstall or modify the production installation.
- Maintain the canonical 12 visible commands and functional hidden compatibility paths.
- Read-only status/recovery defaults; never infer safe recovery from idle snapshots, elapsed time, or low GPU utilization.
- Do not implement Part 3 durable-state revision, `RECONCILED` phase, startup canonicalization, or automatic-recovery mutation.
- Keep LM Studio observation bounded, instance-aware, and safely unavailable unless no-wake behavior is established; tests use mocks only.
- Preserve credential and nested status redaction, maintenance fencing, operator audit, and existing JSON keys.
- No production service, process, model, GPU, WSL, or Scheduled Task operations.

## Execution steps

1. **Baseline and CLI/package:** record interpreter/import provenance and current tests; add failing parser/dispatch/entry-point tests; implement shared parser helpers, canonical catalog, legacy aliases, global options, version/help-registry updates, and installation exit codes.
2. **Gateway status and telemetry:** add failing sanitization/gaming/status/ownership tests; repair safe detail allowlists and nested inhibition sanitization; expose maintenance/gaming status; correct online/offline telemetry ownership and close temporary resources.
3. **Maintenance reconciliation:** add fake-client contract tests; implement read-only status/reconcile and explicit authenticated maintenance release with identity checks; preserve maintenance-specific admission and release semantics.
4. **Inference and recovery assessment:** add the read-only LM Studio observer interface, inference aggregator, recovery assessor and endpoints; test classifications, coverage, offline limits, failure behavior, and no mutation.
5. **Human/JSON presentation:** add intentional renderers and stable JSON schemas for status, telemetry, maintenance, doctor, installation, and recovery; preserve stdout purity and `NO_COLOR` behavior.
6. **Integration regression and review:** run focused and full relevant RC suites, scripts-help tests, isolated console-entry-point validation, Ruff, compilation, and scoped diff checks. Reproduce/classify the known lifecycle baseline failure without suppressing it. Update status/checklist and module indexes; review all changed paths and safety boundaries.

## Review focus

- Legacy recover flag collisions and defaults: parser/architecture tests pin both forms.
- Hidden compatibility command drift: parser catalog tests execute aliases and canonical dispatch.
- Sensitive nested inhibition fields or additional holders: adversarial gateway sanitization tests.
- Offline process ownership misclassification or leaked temporary systems: telemetry tests assert provenance and cleanup.
- Idle snapshots or offline state incorrectly authorizing recovery: assessor tests assert conservative classifications and zero mutations.
- Maintenance release ambiguity or wrong identity clearing a hold: fake authenticated client tests assert exact endpoint, session, and disposition handling.
- LM Studio probe waking a stopped backend: observer tests assert the stopped-runtime guard prevents subprocess/HTTP invocation.
