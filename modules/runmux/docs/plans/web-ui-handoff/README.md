# Runmux Web UI — Coordinated Implementation Hand-offs

**Revised:** 2026-10-24 | **Repository:** `MaxCarlson/scripts`

## What to use

- `RUNMUX_WEB_UI_MASTER_ROADMAP.md`: canonical project roadmap, existing capabilities, dependencies, and phase status.
- `PHASE_01_BROWSER_PROCESS_LAUNCH.md`: **supplemental requirements** for an agent **already executing** the earlier Milestone 1 handoff; not a second assignment.
- `CURRENT_AGENT_PHASE_01_ADDENDUM.md`: **send this one short file to the currently working launch agent**. It only fills gaps between the two handoffs.
- `PHASE_02_TERMINAL_AND_LOG_CORRECTNESS.md` and `PHASE_03_EXPLORER_AND_WORKSPACE.md`: subsequent independent implementation handoffs.
- `PHASE_04A_LIFECYCLE_CONTROLS.md` and `PHASE_04B_ENHANCED_LOGS.md`: separately assignable slices of Phase 4.
- `PHASE_05A_OVERVIEW_MODES.md`, `PHASE_05B_LIVE_TELEMETRY.md`, `PHASE_05C_METRIC_HISTORY.md`: independently assignable slices of Phase 5.
- `PHASE_06_ADVANCED_WORKSPACE_AND_HISTORY.md`: optional future feature pool, not one implementation assignment.

The original handoff sent to the running agent remains authoritative for Milestone 1. **Do not restart or reassign that job.** The addendum clarifies only important acceptance/security/edge cases; it does not authorize other phases or more ambitious launch features.

## Assignment rule

The master is a reference, not blanket implementation authorization. An explicit instruction to implement a named phase or slice **does** authorize its scoped code, tests, docs, and pushed feature branch without a second approval. Material product/security decisions outside that scope require user input. No agent may merge into `main` without a separate assignment.

## Required references

Attach/link the supplied screenshot-based `Runmux Web UI — Gap Analysis & Feature Backlog`, the approved minimal/full UX specifications, and relevant current/goal screenshots **only when visual comparison is needed**. The package does not contain those images. A screenshot is symptom evidence, not a source-code contract. Agents must inspect current `origin/main`.

## Maintenance

After each integration, update the master phase status and merged SHA. This bundle deliberately omits `RUNMUX_WEB_UI_ALL_PHASES.md`: it duplicated the source documents, became stale easily, and was not a second source of truth.
