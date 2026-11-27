# Phase 3D — Live Integration and Runmux Adapter

## Goal

Independently verify read-only local provider behavior, harden only LLM Monitor's own interfaces, and provide a bounded, privacy-safe adapter contract for a separately owned Runmux implementation.

## Scope

All source, test, plan, and documentation changes are limited to `modules/llm_monitor/`. Other modules are read-only. No inference, provider mutation, process control, Runmux routes, browser code, or live session changes are allowed.

## Stages

1. **Baseline and live checks:** verify Phase 3C tests and packaging; inspect the observability/storage contracts; run sanitized GET-only OpenCode and LM Studio checks and read-only hardware discovery.
2. **LLM Monitor adapter:** expose versioned snapshot, session detail, paginated persisted timeline, and stored alerts from existing APIs. Keep the adapter framework-neutral and read-only; redact paths, credentials, and local database locations.
3. **Contract and handoff:** add isolated tests, document the live validation results and limitations, and provide a concrete Runmux-side implementation handoff without editing Runmux.
4. **Delivery:** run focused and regression validation, inspect scoped diff, commit and push the isolated branch.

## Acceptance

- Existing module behavior remains compatible.
- The integration adapter does not collect independently or write provider/database state.
- Returned data is bounded, versioned, provider/session scoped, and sanitized.
- Tests cover pagination, ambiguity, offline/empty data, and privacy.
- Live validation distinguishes observed behavior from unavailable capabilities.
- Every changed repository path is under `modules/llm_monitor/`.
