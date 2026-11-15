# ProcWatch — Implementation Planning Bundle

This bundle contains a **master plan**, one **standalone Markdown file per implementation phase**, and the two **unaltered Gemini source attachments** used to prepare it. No ProcWatch implementation was performed in creating these planning artifacts.

## Start here

1. [MASTER_PLAN.md](MASTER_PLAN.md) — agreed scope, architecture, source-conflict resolutions, event/security contracts, complete ten-command CLI, cross-phase gates and operational rules.
2. [PHASE_01_LIVE_GUARD_AND_CATCHER.md](phases/PHASE_01_LIVE_GUARD_AND_CATCHER.md) — prioritize a real, testable popup guard and live process/window watcher.
3. [PHASE_02_FLIGHT_RECORDER_AND_ATTRIBUTION.md](phases/PHASE_02_FLIGHT_RECORDER_AND_ATTRIBUTION.md) — reliable SQLite/Sysmon/event-log history and evidence-backed causal reconstruction.
4. [PHASE_03_SCANNING_AUDITING_AND_ANALYSIS.md](phases/PHASE_03_SCANNING_AUDITING_AND_ANALYSIS.md) — Python/PowerShell scanning, Scheduled Task audit, recurrence analysis and reviewable fixes.
5. [PHASE_04_HEADLESS_SUPERVISOR_AND_INTEGRATION.md](phases/PHASE_04_HEADLESS_SUPERVISOR_AND_INTEGRATION.md) — supervised headless execution, agent context and independent Windows integration testing.

## Source material

- [Gemini reconciliation reply — original](sources/01_gemini_reconciliation_original.txt)
- [Gemini detailed engineering plan + reference guard listing — original](sources/02_gemini_detailed_plan_original.txt)

The sources disagree about whether persistence or the guard comes first, and about the guard default. This bundle chooses **Phase 1 = live guard + catcher** (per the later detailed plan), while keeping the suppression engine's reported-working Win32 strategy testable and starting **observe-only** before enabling targeted `smart` suppression. Broad `all-consoles` and any wider mode remain explicit opt-ins.

The original Python guard implementation is preserved *inside the unaltered second source attachment*, not copied into production source files; its implementation defects/uncertainties are called out in the master plan and Phase 01 test gate.

## Scope and future handoff

The ZIP is a planning source of truth for a coding agent. The next action, if requested, is to draft a concrete agent handoff referencing these plans. The ZIP does **not** contain a handoff, modify the user's repository, configure Windows, run tests on Windows, or invoke local LLM inference.

## Contents

```text
procwatch_plan/
├── README.md
├── MASTER_PLAN.md
├── phases/
│   ├── PHASE_01_LIVE_GUARD_AND_CATCHER.md
│   ├── PHASE_02_FLIGHT_RECORDER_AND_ATTRIBUTION.md
│   ├── PHASE_03_SCANNING_AUDITING_AND_ANALYSIS.md
│   └── PHASE_04_HEADLESS_SUPERVISOR_AND_INTEGRATION.md
├── sources/
│   ├── 01_gemini_reconciliation_original.txt
│   └── 02_gemini_detailed_plan_original.txt
└── MANIFEST_SHA256.txt
```

`MANIFEST_SHA256.txt` verifies the included files (excluding itself); the ZIP is also independently integrity-checked as part of creation.
