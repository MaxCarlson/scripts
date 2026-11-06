# P03/P04 Offline Integration Checkpoint

This document records the offline integration of P03 preregistration and paired
analysis with P04 execution-scoped inference correlation. The fixture uses
synthetic identities and outcomes only. It does not seal or characterize the
real P02 baseline, and it creates no promotion decision for a real model.

The additive paired-analysis diagnostics are released as `benchmark_core`
0.5.0. `agent_benchmark` is 1.28.0 and now declares a compatible
`benchmark-core>=0.5.0,<0.6` range; this corrects the previous upper bound that
excluded P03's 0.4.0 checkpoint.

## Source contracts and path

The path exercised by `tests/test_p03_p04_integration.py` is:

1. `lio-preregistration-v1` is validated and frozen with the existing P03
   fingerprint API. A separate case with an unknown baseline or instrumentation
   identity remains `template_ready_blocked`.
2. P04's `ExecutionCredentialRegistry` allocates an attempt ID before any
   simulated task execution. Gateway-assigned request IDs are recorded against
   its short-lived credential. `TelemetryStore` persists each context in
   SQLite v4, then reconciles the native Harbor trial ID after completion.
3. `reconcile_correlated_execution()` checks the P04 context against the
   existing `lio-trial-v1` descriptor and persisted rows. The attempt ID and
   Harbor trial ID remain distinct. It selects requests only by verified
   execution ID; rows from unrelated clients are ignored regardless of time.
4. The adapter emits unchanged `lio-evidence-v1` records and calls
   `validate_evidence()`. Request parameters supplied as captured fixture data
   become `observed` evidence from `external_request_capture`. Missing captures
   are represented as unavailable observations. Requested and planned settings
   retain their own stages.
5. No effective observations are emitted. Correlation proves request ownership,
   not backend activation. A separate, independently verified runtime artifact
   is still required by the current LIO evidence contract before a setting can
   be called effective.
6. P03 frozen-design matching and `benchmark_core` condition compatibility and
   paired-analysis APIs validate/compare synthetic result descriptors. The
   generated report is portable single-file HTML and contains IDs, reason
   codes, and evidence references, never credential or prompt content.

## Adapter boundary

`reconcile_correlated_execution(correlation, request_rows, trial, ...)` accepts
the P04 `ExecutionCredentialRegistry.requests()` result and
`TelemetryStore.get_inference_request(..., include_content=False)` rows. It
fails closed when verification is absent, the run/task/attempt/variant/repetition
or native trial IDs disagree, a correlated row is missing or duplicated, or a
row's persisted context differs from the registry context. It does not use
timestamps as proof and does not accept legacy rows in this strict adapter.

P04 history stores correlation metadata, not the incoming parameter map. The
adapter's optional `request_settings` input therefore represents a separately
available sanitized request-capture observation; it must not be inferred from
the correlation record. In the synthetic test it is fixture data. Production
parameter capture and live Harbor/OpenCode propagation remain separate
acceptance questions.

Artifact hashes in adapter output fingerprint the normalized correlation
metadata for the request. They are identifiers for the evidence record, not a
claim that a transcript or backend-runtime artifact was collected.

An optional `backend_runtime_evidence` input is accepted only as a separate
backend identity/version, artifact ID/SHA-256, and field/value/timestamp set.
The adapter emits a separate LIO evidence record with paired `observed` and
`effective` backend-runtime observations; it does not merge those with external
request observations, because the contract allows only one observation per
field/stage. Missing or partial runtime fields stay visible in `evidence_gaps`.
The returned `request_capture_status` distinguishes complete, partial, and
unavailable request-parameter capture from verified request ownership.

## Analysis and limitations

The synthetic between-model example has four task blocks: three scored pairs,
one block excluded from paired effects because the baseline attempt is
infrastructure-invalid, one scored failure, one timeout, and wins/losses/ties.
Infrastructure-invalid attempts remain visible in status counts and
`trial.status_not_scored_in_pair`; they do not enter the scored denominator or
become functional failures. The small fixture is exploratory and ineligible for
promotion.

A synthetic within-model setting comparison is compatible only when the model
identity is held fixed and both the model identity and changed setting have
separate evidence references at their required stages. Without the independent
effective-setting attestation, the comparison is refused as a causal estimate.

The analysis methods and their assumptions remain those documented by P03:
exact paired testing only when identifiable, task-cluster resampling for
repeated pairs, and no inferential claim from this small synthetic fixture.

## Validation boundary and remaining gates

Offline SQLite, API, schema, statistics, and report interfaces are exercised
with synthetic fixtures. No local inference, Harbor dispatch, model transition,
GPU workload, container execution, service interaction, or Resource Coordinator
operation is part of this checkpoint.

Real process propagation through Harbor/OpenCode is still unverified. Before a
real P02/P07 study, separately establish the sealed P02 baseline, verify the
per-invocation OpenCode configuration reaches the actual agent process, and
collect independent backend-runtime evidence for any setting used as an
effective intervention. This checkpoint itself does not authorize those
runtime actions.
