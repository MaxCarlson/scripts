# Local Agent Setup Status Audit — Design and Plan

## Intent

Make `local-agent setup status` an immediately readable, non-destructive audit of whether required Codex, Antigravity, and OpenCode resources match the package that is actually running. Report stale and missing resources, copy/link method, optional feature selection, and package provenance without changing setup behavior.

## Scope and constraints

- Keep `setup status` read-only and preserve `operations`, existing operation fields, and established exit codes.
- Do not change apply, receipt, backup, conflict, or recovery behavior.
- Do not infer the active package source from the current working directory. Report its version and resolved module/resource paths; identify a source checkout only when the active package files are tracked by that checkout.
- Use synthetic homes/state directories for tests. Never inspect or mutate the live installation during implementation.

## Approaches

1. Rewrite planner fingerprints and installer ownership: rejected because the observed four-resource drift is already detected and the request is an audit/presentation improvement.
2. Add a status-only report derived from the existing plan, retaining the operation structure and codes: chosen because it makes status clearer while leaving plan/apply semantics stable.
3. Add a separate audit command: rejected because users need the existing `setup status` command to make the sync state obvious.

## Implementation stages

1. Add synthetic tests for stale copied skills and generated roles, byte drift, semantic JSON/TOML equivalence, link target drift, missing resources, optional features, JSON compatibility, exit codes, provenance, and color behavior.
2. Add a status summary and package/resource provenance; improve default status formatting with safe auto-color and explicit copy/link markers.
3. Validate content-audit boundaries, then run the complete module test suite, Ruff, packaging checks, and diff review.
4. Commit and push the reviewed feature branch only; do not merge.

## Verification contract

Files and copied trees are verified by SHA-256 over exact file bytes and relative tree entries. Link verification includes the resolved target and linked content. JSON/TOML managed fields are checked semantically while preserving unrelated formatting; the report must label this as semantic and must not claim global byte-exact verification. Optional features disabled by the effective plan are informational and do not count as failures.
