# Local Agent Bridge Reliability Plan

## Goal

Persist and verify explicit OpenCode model limits, improve safe job/session recovery guidance, and make worker instructions favor focused source discovery without adding a new retrieval system.

## Architecture

Extend the existing `local-agent model` and `local-agent run` CLI and preserving OpenCode JSON helpers. Verification will report configured metadata, effective OpenCode API values when reachable, and LM Studio's actually reported loaded context independently. Since job polling is supplied by pinned `opencode-mcp`, improve the packaged coordinator skill and synthetic resource-contract tests rather than patching the installed dependency.

## Scope and constraints

- Preserve the 32K default; make output limits opt-in/configurable and require explicit correction for conflicting user metadata.
- Do not modify user profiles, LM Studio/OpenCode installations, loaded models outside an explicitly invoked `run`, `modules/llm_monitor`, Runmux, or third-party packages.
- Keep the measured 64K/8K Qwen profile opt-in and qualify its hardware/model limits.
- Do not implement retrieval/indexing/compaction architectures or claim empirical prompt efficiency.
- Preserve current CLI aliases, setup receipts, model rename/remove behavior, and unrelated OpenCode JSON fields.

## Approaches

1. Add a competing profile/model registry. Rejected because it duplicates OpenCode and LM Studio state.
2. Extend current run/config helpers and add read-only `model verify`. Chosen because it keeps metadata beside the existing alias and can compare static, effective, and loaded values.
3. Patch `opencode-mcp` polling. Rejected because it is a pinned external package and its current polling implementation is not owned by this module; use instruction-level recovery guidance and synthetic contract fixtures.

## Work units

1. Add tests for limit validation, conflict handling, run configuration, verification state, and alias preservation; implement configurable output/context metadata and explicit correction.
2. Add read-only JSON/text model verification using OpenCode's provider config endpoint and LM Studio loaded-instance report, with offline confidence and clear status codes.
3. Update coordinator/worker resources and deterministic recovery/resource fixtures for IDs, explicit agents, stale-job reconciliation, task correlation, timeout semantics, and independent diff verification.
4. Update module documentation and package/resource checks, including the unresolved enabled Codex CLI discovery blocker.
5. Run focused module tests, CLI/package checks, inspect diff/status, commit, and push this branch only.

## Validation

Use mocked HTTP responses and temporary config paths. Cover absent, valid 32K, valid 64K, invalid/mismatched limits, project directory overrides, provider offline, unknown loaded context, and preserved fields. Run the full `modules/local_agent_bridge/tests` suite and build/inspect the wheel without invoking live inference or modifying actual profiles.
