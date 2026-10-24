# Runmux Web UI — Master Roadmap and Agent Handoff Index

**Document ID:** RUNMUX-WEB-MASTER  
**Version:** 0.1 (planning baseline)  
**Date:** 2026-10-24  
**Status:** Proposed implementation roadmap; not authorization to modify the repository  
**Repository:** `MaxCarlson/scripts`  
**Areas:** `modules/runmux/`, `modules/web_ui_tools/`  
**Primary target:** A browser UI for discovering, inspecting, launching, and eventually controlling persistent Runmux processes.

> **Use this as the durable project reference.** Assign only one phase-specific handoff at a time; the phase files below define individual work packages. Update this master when requirements, scope, approval, or validation outcomes change. Do not treat conceptual mockups as evidence of implemented backend features.

## 1. Current implementation and evidence

Phase 3 was integrated from the `origin/main` baseline at `9f01984d3dedf05781a19f8d131956662ee5b29d`, which
already contained Phase 1 launch, Phase 2 terminal/log correctness, and the
Phase 5B telemetry backend. The Phase 3 merge commit is
`54502666b5724596ee3d21c1e694b8522d5a5151`.

The browser keeps Output and the ANSI Terminal as distinct views. The existing
supervisor owns process lifecycle, PTY behavior, and terminal input locks. The
API preserves a privacy allowlist; full command arguments, working directory,
environment values, credentials, and log paths are not disclosed to the UI.
Phase 3 adds explorer grouping/filtering/sorting/paging, Run-ID tab restoration,
reconciliation, and responsive controls without expanding that allowlist.

Synthetic Windows headless Chromium checks cover the empty registry, 450-run
registry, responsive layouts, keyboard controls, safe text rendering, reload
tab restoration, and close-view behavior. Focused Windows Python tests remain
unverified because the test process hangs during startup; see the Phase 3
status report for validation limits. Concept images and browser screenshots are not evidence of
unimplemented backend capabilities.
## 2. Governing product decisions

1. **Desktop-first dark workspace.** Preserve the existing visual foundation; improve information density and layout rather than replacing it wholesale.
2. **Hybrid navigation.** Searchable process explorer plus tabs representing opened run *views*. Closing a tab never stops a process.
3. **Explorer grouping.** Switchable grouping; status is the default. Group/category modes depend on actual metadata.
4. **Process overview.** Four future display modes: A Minimal, B Inline, C Dashboard, D Expanded. Cycle/select modes; persist the **last-used mode globally** across runs and reloads.
5. **Logs.** Start with simple, reliable output. Evolve toward enhanced search/facets/counts and keyboard use. Preserve a distinction between append-only output and a PTY-rendered terminal. Future modes: single, stdout/stderr split, and multi-stream tabs **only when sources exist**.
6. **Inspector.** Existing Details view is sufficient as a starting point. An optional resizable/pinnable right inspector is a **provisional** longer-term design; bottom docking is unresolved.
7. **Progressive implementation.** Deliver and validate simple capabilities before optional extensions. Do not introduce an elaborate framework in anticipation of hypothetical features.
8. **Immediate new requirement.** The Web UI must launch a new run using the same underlying semantics as `runmux run <program stuff here>`, through a new tab containing command entry. This changes the previously read-only browser milestone, so access control and mutation boundaries are prerequisites.

## 3. Phase map and dependencies

| Phase | File | Deliverable | Primary priority | Must precede |
|---|---|---|---|---|
| 1 — Launch | `PHASE_01_BROWSER_PROCESS_LAUNCH.md` | Authorized new-process tab and CLI-parity launch flow | **P0** | Browser mutations and run-management UX |
| 2 — Output fidelity | `PHASE_02_TERMINAL_AND_LOG_CORRECTNESS.md` | Reliable log/terminal rendering and bounded output | **P0** correctness | Enhanced log features, split/stream layouts |
| 3 — Navigation | `PHASE_03_EXPLORER_AND_WORKSPACE.md` | Search/group/sort, tabs, persistence, useful metadata | **P1** | Full workspace customization |
| 4 — Control and logs | `PHASE_04_LIFECYCLE_AND_ENHANCED_LOGS.md` | Authorized lifecycle actions and enhanced searchable logs | **P1** | Advanced controls/automation |
| 5 — Monitoring | `PHASE_05_METRICS_AND_OVERVIEW_MODES.md` | Four overview modes, verified telemetry, detailed metrics | **P2** | Advanced resource dashboards/alerts |
| 6 — Workspace extension | `PHASE_06_ADVANCED_WORKSPACE_AND_HISTORY.md` | Inspector, multi-pane output, events/history, optional productivity tools | **P2–P3** | No required successor |

**Scheduling:** Phases 1 and 2 can be investigated independently, but overlapping edits to the backend, frontend component tree, and `web_ui_tools` must be coordinated. Phases 3–6 are staged delivery areas, not promises that all features will fit into one pull request. Decompose them further following code inspection.

## 4. Global invariants and acceptance gates

### Safety and process identity

- Operate in a clean isolated worktree/checkout from current `origin/main`. Do not alter another agent's worktree (including concurrent native TUI integration).
- Tests use synthetic registries, disposable supervised processes, temporary directories, and distinct ports. **Never touch the user's real Runmux registry, process supervisors, configuration, or state.**
- Treat the **Run ID** as the unique identity for tabs, selection, URLs/API actions, and persistence. Identical process names are expected.
- Closing a browser tab, refreshing a page, changing a log display mode, clearing visual output, or pausing a *viewer* must **never** terminate or pause the supervised process.
- Differentiate backend/registry disconnection from a specific run's `LOST`/disconnected lifecycle state.
- No resource charts or severity counts may be invented. Unknown telemetry is **unavailable**, not zero; unrecognized log lines remain visible.

### Security gate for any mutating web action

- Verify localhost binding, access-code/session/authentication behavior, origins/CSRF mitigation, API authorization, security of browser storage and logs, and privilege context **in the actual implementation**.
- Launching an arbitrary local executable is a high-impact capability. Implement an explicit authorized action, never as an unauthenticated convenience endpoint.
- Reuse Runmux's existing CLI/service launch semantics. Do not convert a user-supplied command into arbitrary `shell=True` execution or claim cross-platform quoting parity without tests.
- Ensure untrusted log content cannot inject scripts or active HTML; avoid exposing sensitive command/environment values without the existing permission model allowing them.
- Browser write actions require explicit user invocation, clear feedback, and idempotency/double-submit handling where practical. Avoid unapproved state changes on load or retry.

### Engineering gate

Each phase handoff must result in a report of: inspected commit/branch, verified existing contracts, changed files, behavior delivered, tests executed (commands and outcomes), limitations, security impacts, regressions, and remaining backlog IDs. No phase is accepted on visual resemblance alone.

## 5. Backlog mapping

The IDs below match the preceding visual gap analysis and are used consistently by phase documents. IDs designate **requirements to evaluate**, not proof that code is absent.

- **Phase 1:** L01–L09; security S01–S05, S08–S09 as applicable. L10–L11 optional scope after core launch passes; L12 deferred.
- **Phase 2:** T01–T07, S10; output fidelity and history truncation. T08–T12 deferred to Phases 4/6 or their own follow-up work.
- **Phase 3:** N01–N08, D01–D05, W01–W04/W12, S06–S07/S12; baseline H01–H04 discovery as useful.
- **Phase 4:** C02–C07; T08–T09; W05/W06; remaining lifecycle-related S01–S12 validation.
- **Phase 5:** M01–M13; resource collection/retention is conditional on confirmed backend capability.
- **Phase 6:** I01–I08; T10–T12; N09–N14; H01–H11 enhancements; L12; C08–C12; W07–W11; future templates/schedules/sessions/notes subject to separate approval.

**Priorities may be re-evaluated after code reconnaissance.** For example, an already working backend feature with no UI could be inexpensive to expose, while a novel telemetry/history subsystem is not.

## 6. Cross-phase UX requirements

### Primary workspace

A compact application header and left explorer frame a central tabbed workspace. A process tab has an identity/status cue and a close-*view* action. The selected run shows essential identity and status; its primary content is output/terminal or Details. Large output should have first claim on vertical and horizontal space.

### Initial launch tab

A visible `+` in the process-tab strip opens an unsaved **New Process** tab. Empty-state UX also includes an obvious launch entry. The form accepts a command and arguments, uses the actual `runmux run` semantics, permits an explicit working directory/default, and has a deliberate Launch action. On success, show/open the actual new run; on failure retain user input and show a non-destructive error.

### Logging and terminal

**Output** is for inspecting a log stream and retained history; **Terminal** is for terminal-screen behavior including cursor movement/ANSI/TUI rendering. Pausing follow or display is not process pause. An arbitrary log tail may be insufficient to reconstruct a TUI frame; diagnose replay/snapshot design before modifying the renderer.

### Process details

Show available metadata in a Details view. Full command, working directory, and environment information may be sensitive; preserve explicit authorization/reveal decisions, with no secret leakage through page source, client cache, analytics, or console logs.

### Future monitoring

The four process overview modes and the metrics drawer operate on **real available values**. Use data provenance for host versus per-process measures and label chart time windows/retention. Do not block Phase 1 or 2 on telemetry architecture.

## 7. Project-level unresolved questions

1. What exactly are the current `runmux run` flags/argument, shell, cwd, environment, naming, and PTY contracts?
2. Which browser APIs are already implemented versus absent, and what is the session's write-authorization model?
3. Does the current Terminal pane receive raw PTY bytes, state snapshots, or replay from persisted log data?
4. Are stdout and stderr retained separately? Is old output readable in bounded chunks?
5. Which resource telemetry (per-process, host, GPU, I/O) actually exists, and with what history?
6. Are workspaces, categories, tags, event records, or persisted UI layouts already modeled?
7. Should the future inspector support right-pinned only or also bottom docking? Not yet approved.
8. Which browser-safe keyboard shortcuts should be final? `Ctrl+W` must not be relied upon for pane switching.
9. Is the launch interface intended to expose Runmux-specific flags, arbitrary shells, or only argument-vector execution in the first iteration?
10. Which UI features warrant top-level navigation versus tabs/drawers? The full mockup is not a binding sitemap.

Record answers in this master as decisions, linking the relevant code/tests and date. Do not assume an answer merely from a screenshot.

## 8. Handoff operating procedure

1. **Choose one phase file** and specify the desired implementation slice/acceptance criteria.
2. Agent inspects the repository and returns a concise evidence-based implementation plan; note assumptions and backend gaps.
3. Agent works in a dedicated feature branch/worktree, minimizing conflict with other Runmux development.
4. Agent updates code, tests, and documentation consistently. Validate unit/integration tests with isolated registries; never mutate production state.
5. Agent reviews changes and provides commit/PR plus an auditable validation report. Run any required platform-specific local validation before merging.
6. Update this master: phase status, implementation evidence, unresolved issues, and any changes to scope or sequencing.

### Phase status tracker

| Phase | Status | Implementation reference | Validation reference | Blockers/notes |
|---|---|---|---|---|
| 1 | Complete | `plans/20261024-runmux-web-process-launching/` | 33 focused web/readiness tests and prior browser smoke passed | Authenticated `create_managed_run` launch; full suite retains four failures reproduced on `origin/main`; wheel build unavailable because hatchling is not installed; POSIX runtime not exercised |
| 2 | Complete and merged before Phase 3 in baseline `9f01984d3dedf05781a19f8d131956662ee5b29d` | `plans/web-ui-handoff/PHASE_02_TERMINAL_AND_LOG_CORRECTNESS.md`; `plans/20261024-runmux-web-terminal-log-correctness/` | Prior platform validation is in the Phase 2 status report | Windows Proactor hang limited native post-fix validation; bounded replay cannot reconstruct omitted screen history |
| 3 | Complete and merged (`54502666b5724596ee3d21c1e694b8522d5a5151`) | `plans/web-ui-handoff/PHASE_03_EXPLORER_AND_WORKSPACE.md`; `plans/20261024-runmux-web-explorer-workspace/` | Windows Node suite and native headless Chromium validation pass; see status report | Full argv/cwd remain withheld; focused Python web tests are unverified due documented Windows startup hang |
| 4 | Not assigned | — | — | Depend on mutation security and log model |
| 5 | 5B backend merged in baseline `9f01984d`; 5A/5C not assigned | `src/runmux/web.py` telemetry routes | 5B backend integrated | Metrics UI and history remain unassigned |
| 6 | Not assigned | — | — | Many items are optional or undecided |

## 9. Reference material

- Current-state screenshots supplied in this conversation: `RunmuxEmpty.png` and six process/Output/Terminal/Details captures taken 2026-10-24.
- Conceptual destination: `Runmux Process Dashboard Full.png`, plus earlier approved design explorations.
- Prior conversation: minimal and full Runmux Web UI design specifications and the screenshot-based gap inventory.

These files must be attached or made available to any external coding agent; referring to them here does not imply they exist in the Git repository.

## 10. Definition of ready for a phase

A phase is ready to start when its acceptance criteria, supported/unsupported backend contracts, security gates, isolated validation plan, and branch ownership are understood. **This document is a planning reference, not blanket authorization to implement all six phases.**
