# Checklist: Local Agent Bridge Reliability

## Model limits and verification
- [x] Validate positive integer context/output and output less than context.
- [x] Add absent limits; preserve valid metadata and require explicit correction for conflicts.
- [x] Keep the 32K default and add the documented opt-in 64K/8K Qwen command.
- [x] Report requested/configured/effective OpenCode/loaded LM Studio values separately.
- [x] Cover online, offline, project directory, mismatch, and unknown-loaded-context cases.
- [x] Preserve 64K metadata through rename/remove/recovery/setup behavior.

## Coordination and worker resources
- [x] Record job/session/message IDs, directory, model/provider, and explicit agent at dispatch.
- [x] Document stale job reconciliation against original session/directory and turn correlation.
- [x] Document active/completed/failed/uncertain, pending input, timeout vs cancellation, and no duplicate dispatch.
- [x] Require actual diff/hash and focused test checks; ignore false-zero summaries and ambiguous ownership.
- [x] Add deterministic synthetic recovery scenarios.
- [x] Add search-first/focused-read/concise-progress preferences to the canonical worker prompt.

## Delivery
- [x] Update README, SETTINGS, INTEGRATION, VALIDATION, HANDOFF.
- [x] Keep enabled Codex CLI tool discovery marked unresolved pending live acceptance.
- [x] Run module tests and wheel/package/resource checks; record counts and skips.
- [x] Review changed paths, diff, and final Git status; commit and push branch only.
