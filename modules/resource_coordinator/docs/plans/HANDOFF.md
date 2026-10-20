# Resource Coordinator Plans Handoff

## Plan Index

- **20261019-0915_resource-coordinator-core**: Generic core framework, offline LM Studio gateway, policy engine, process backends, and offline test suite.
  - Status: Architecture review checkpoint complete; unattended deployment blocked. See [review](../PHASE_B_REVIEW.md).
  - Stages:
    - Stage 1: Generic Core Framework (`01_core-framework.md`)
    - Stage 2: Adapters, Gateway, Config & CLI (`02_lmstudio-gateway.md`)
    - Stage 3: Verification & Review (`STATUS.md`)

## Phase C preparation and safety review

- Branch: `resource-coordinator-phase-c-prep`; reviewed 9101ca7c against e903cf2e.
- Status: review checkpoint complete, 151 offline tests passing, **NO-GO** for live testing until missing lifecycle/admission path and deployment prerequisites are closed.
- [Historical Phase C report](../PHASE_C_SAFETY_REVIEW.md) and [handoff](../PHASE_C_PREPARATION_HANDOFF.md).
- Telemetry T1 remains separate at dd8dd7ff; no merge or live operation performed.


## Current: Phase D final safety review

- Plan: [20261019-1250_phase-d-controlled-integration](20261019-1250_phase-d-controlled-integration/STATUS.md).
- Branch `resource-coordinator-phase-d`, reviewed e9b8c9f5 against 3744c4c2.
- Bounded safety corrections and 34 added regressions; 220 offline tests passing, Ruff/format/Mypy clean.
- [Current report](../PHASE_D_SAFETY_REVIEW.md): CONDITIONAL GO only after independent acceptance gates and separate user authorization. Operational NO-GO until then; unattended NO-GO.
- No live operation, merge, push or T1 integration. Next: review checkpoint and environment evidence.

## Phase D supervised-test environment preflight

- Branch/worktree: `resource-coordinator-phase-d`, reviewed coordinator commit `e548941f7cea477decf571825769abc42e36e433`.
- [Preflight report](../SUPERVISED_TEST_PREFLIGHT_20261019.md) records a **NO-GO** host snapshot and an ignored, inactive private config draft. Krig is stopped; Qwen is resident/CLI-IDLE; no live process-control validation occurred. OpenCode listens on port 4096. Watchdog exclusion, one-client isolation, upstream idle, VRAM/compute headroom and crash-time intervention remain open.
- Next: Sol Medium reviews the preflight. Operator supplies the exact watchdog inventory and out-of-band intervention method and closes remaining acceptance gates before any separate execution authorization. No test or live operation was performed.

## Minimal LM Studio activity automation

- Plan/status: [20261019-1600 minimal activity automation](20261019-1600_minimal-lmstudio-activity/STATUS.md).
- Branch: `resource-coordinator-phase-d`, based on `44ce5d6e`.
- Offline implementation enables known model-load paths under exclusive `gpu.inference` leases with matching configured stop/restart policies; generic process lifecycle is opt-in. Unload and unknown mutation paths remain closed.
- Sol Medium review required for model-load admission, shared-resource exclusive arbitration, and atomic idle-restart/request boundary. Host preflight remains NO-GO. No live operation, merge, or push.
