# Downstream Interface Specifications: P05 & P06

This document defines the interface contracts, boundaries, and validation requirements for downstream implementation phases:
- **P05:** Versioned Feature-Profile Schema and Registry
- **P06:** Safe Configuration Compiler, Apply, and Rollback Engine

These specifications are built directly upon the immutable identity (`lio-experiment-v1`, `lio-variant-v1`, `lio-trial-v1`) and provenance (`lio-evidence-v1`) foundation established in P03/P04.

---

## 1. P05 — Feature Registry Interface Specification

### 1.1 Purpose and Boundaries
P05 owns the registry of supported inference features, parameter constraints, and conflict graphs.
- **Read-Only Invariants:** `modules/agent_benchmark/agent_benchmark/inference_profile.py` (`opencode-inference-profile-v1`) must remain completely untouched. No new feature keys may be added to the v1 profile.
- **Output:** P05 produces validated parameter subsets that populate the `features` and `sampling` sections of `lio-variant-v1`.

### 1.2 Feature Definition Schema (`lio-feature-def-v1`)
Each registered feature definition must specify:
1. `feature_id`: Unique identifier matching `^[a-z0-9][a-z0-9._-]{0,63}$`.
2. `version`: Semantic version string.
3. `scope`: Execution boundary — either `"load_time"` (model loading/allocation) or `"request_time"` (per-request parameter).
4. `parameters`: Dictionary of allowed parameter names to typing rules:
   - `type`: One of `"int"`, `"float"`, `"str"`, `"bool"`.
   - `bounds`: Minimum and maximum for numbers; enumeration for strings.
   - `default`: Safe default value (must match unmodified baseline).
5. `dependencies`: List of required prerequisite features or minimum backend versions.
6. `conflicts`: List of mutually exclusive feature IDs.
7. `backend_capabilities`: Required backend runtime capabilities (e.g. `mtp`, `flash_attention`).

### 1.3 State Handling
- Unrecognized features must fail closed with an explicit rejection error.
- Features requiring unavailable backend capabilities must be flagged `unsupported` or `unknown`.
- Parameter validation must strictly reject out-of-bounds, non-finite, or unexpected types prior to compilation.

---

## 2. P06 — Configuration Compiler & Apply Engine Interface Specification

### 2.1 Purpose and Boundaries
P06 compiles an authorized feature configuration into a deterministic, non-mutating execution plan (`lio-plan-v1`), and coordinates transaction-safe application and rollback against the host inference runtime.

### 2.2 Compilation Input and Output
- **Inputs:**
  1. `variant`: Validated `lio-variant-v1` instance.
  2. `backend_attestation`: Validated backend identity and capability records (`lio-evidence-v1` capabilities).
- **Output:** `lio-plan-v1` containing:
  - `variant_sha256`: Binding to the exact variant fingerprint.
  - `load_operations`: Deterministically ordered list of load-time mutations (e.g., context sizing, KV cache type, flash attention, draft model).
  - `request_operations`: Deterministically ordered list of request-time parameters (e.g., temperature, top_p, top_k, max_tokens, reasoning effort).
  - `reload_required`: Boolean indicating whether model reload or server restart is necessary.
  - `resource_delta`: Estimated VRAM / memory changes.
  - `status`: `"compiled"`, `"unsupported"`, or `"rejected"`.

### 2.3 Strict Separation of Stages
1. **Planned vs. Effective:**
   - Compiler output has stage `"planned"`.
   - The compiler must **never** assert or emit stage `"effective"`.
2. **Apply & Runtime Mutation:**
   - Applying a plan requires explicit operator authorization.
   - Every mutation must generate a journal/receipt artifact with SHA-256 digest.
   - If runtime verification fails or times out, the engine must execute automated rollback to baseline state.
3. **Evidence Emission:**
   - Runtime observations are recorded as stage `"observed"` with source `"backend_runtime"`.
   - Only when observed runtime evidence matches the planned setting in timestamp, type, value, and artifact receipt may an entry with stage `"effective"` and status `"verified"` be emitted into `lio-evidence-v1`.

---

## 3. Downstream Coordination & Gating Matrix

| Gate / Phase | Requirement for P05 / P06 | Enforcement Mechanism |
|---|---|---|
| **P03 Identity** | Must reference `lio-experiment-v1` and `lio-variant-v1` digests. | `contracts.py` fingerprint verification. |
| **P04 Evidence** | Must emit strictly typed `lio-evidence-v1` observations. | `contracts.py` `validate_evidence()`. |

### P04 request ownership evidence

Request ownership is established outside `lio-evidence-v1` by `benchmark-inference-correlation-v1`: Monitor-issued execution credentials bind a run/task/attempt context to gateway-assigned request IDs, then reconcile the native Harbor trial ID after execution. The authenticated correlation API and schema-v4 history carry only identifiers and verification provenance. A `monitor_request_observations` adapter may consume requests only after this upstream relation is verified. Correlation does not change the evidence stages and cannot promote configuration or request parameters to `effective`.
| **P02 Baseline** | Must never mutate or override the sealed P02 baseline reference. | Fixed baseline comparison checks. |
| **P07 Gate** | No-op parity verification must pass before any optimized feature run. | Matched control trial comparison. |
| **Safety / Isolation**| No runtime modification without explicit receipt journal and rollback. | Fail-closed capability and receipt validation. |
