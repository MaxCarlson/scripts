# Runmux Web UI — Phase 6 Agent Handoff: Advanced Workspace, Streams and History

**Phase ID:** RUNMUX-WEB-P6  
**Status:** Candidate feature pool, **not** a single approved implementation assignment  
**Priority:** **P2–P3**; split into independently approved subprojects  
**Primary backlog:** I01–I08, T10–T11, N09–N14, H01–H11 advanced items, L12, C08–C12, W07–W11. T12 (interactive PTY attachment) is **already implemented** and is not a future feature.

## 1. Objective

Build on the stable launcher, viewer, explorer, lifecycle and metrics foundation to make Runmux an efficient multi-process monitoring and management workspace. This phase intentionally contains multiple optional product areas. **Do not implement all of them as one PR.** First obtain user sign-off on concrete UX alternatives and verify source/backend support.

## 2. Candidate workstream A — Contextual process inspector

**Provisional direction:** Keep the existing Details tab, then introduce a shared inspector that can function as an on-demand right drawer and a pinnable/resizable right panel. Candidate sections: Details, Events, Metrics, Files, Environment, Notes.

- Inspector must not obscure essential process output by default.
- Users may open/close it without navigating away from logs.
- Pinning keeps it visible across run tabs, following the selected run.
- Resize limits must protect minimum log workspace width.
- Remember visibility and width as UI preferences, without storing sensitive process data.
- A bottom-docked inspector is an **unresolved** design option. Do not construct a generalized docking platform without another decision.
- Only show Events/Files/Environment views that have verified data access and authorization.

## 3. Candidate workstream B — Multiple output streams and split panes

The approved long-term log interaction model includes:

1. **Single:** One full-width log view.
2. **Tabbed streams:** Choose among stdout, stderr, application log files or other **actual retained** sources; useful for 3+ streams.
3. **Split panes:** Resizable simultaneous source views, typically stdout alongside stderr.

Potential future keyboard interactions: `/` search, `n`/`N` matches, `f` follow, `p` pause *display*, and browser-safe shortcuts for pane switching and layout cycling. Do not rely on `Ctrl+W`, which commonly closes a browser tab.

Before implementation, verify whether Runmux captures stdout and stderr separately and how per-stream retention works. A merged stream **cannot reliably be unmerged retroactively**. Each pane needs independent follow/scroll/search/filter state; output retrieval and rendering must remain bounded. Shared and per-pane state ownership should be defined before writing the UI.

**Interactive PTY attachment already exists** through authenticated WebSockets and supervisor-managed input locking. This stream-layout work must preserve that contract. A *new* control-transfer or multi-user permission model would require its own threat model and approval; do not rebuild current PTY interaction.

## 4. Candidate workstream C — Events, history, and run discovery

Enhance the existing historical-run explorer with a dedicated process overview or table **if volume justifies it**:

- Sortable, filterable run list; active and historical records searchable without overloading the explorer.
- Recent completions, failures, `LOST` explanations and restart history (where available).
- Bounded output-history retrieval if persisted data exists; show retention/truncation explicitly.
- Structured lifecycle events and an event timeline **only if event records exist or are deliberately introduced**.
- Distinguish an inferred warning from a verified event. Avoid converting arbitrary log messages into authoritative run lifecycle events.
- Date ranges, archived runs, and large-history pagination/virtualization where appropriate.
- Optional warning/failure alerts, sampling-based thresholds and archival/retention policy controls require separate backend policy work and explicit approval.

## 5. Candidate workstream D — Workflow/productivity features

Future optional features from the full concept:

- Recent commands, saved process-launch presets and duplicate-into-launch form.
- Pinned/reorderable tabs, searchable tab overflow and command palette.
- Saved workspace layout/appearance settings; potentially adjustable dark/light theme and information density.
- Task-oriented views for sessions, environment, files, storage, schedules, and notes—only where product usage and APIs justify dedicated navigation.
- Advanced batch stop/restart/cleanup and unattended schedules, only after explicit authorization/confirmation models exist.

Features shown in mockups such as New Process, Stop, Restart, resource charts and directories may belong to earlier phases. Do not duplicate them in this one.

## 6. Decision gates to settle before implementation

| Decision | Current status | Required evidence/approval |
|---|---|---|
| Inspector on-demand + right pin | Preferred but provisional | UX sign-off; resizable design acceptance |
| Bottom inspector docking | Open | Visual comparison and user approval |
| Split vs tabbed stream switching | Direction approved | Actual independent output sources and API contract |
| Browser PTY input | **Implemented** | Preserve existing WebSocket session/auth + supervisor attachment/input-lock contract; fix fidelity under Phase 2 |
| Dedicated historical overview | Open | Run volume, search schema, desired columns |
| Event/alert source | Unverified | Actual event model or approved event capture design |
| Launch presets/templates | Future | Storage schema, secrecy, permission requirements |
| Schedules/automation | Optional | Backend scheduling policy, scope and user approval |
| Light theme | Open | Visual design approval and maintenance budget |

## 7. Suggested subprojects, not fixed implementation order

- **6A — Inspector:** Right drawer + pin/resize, no arbitrary docking.
- **6B — Multi-stream logs:** Stream tabs and resizable split panes, based on real sources.
- **6C — History:** Dedicated run overview, bounded history browsing and real events.
- **6D — Productivity:** Launch presets, keyboard command palette, workspace settings.
- **No 6E PTY-control implementation:** Already delivered. Phase 2 may harden or correct terminal sizing/replay; any entirely new multi-user control-transfer policy requires a separate assignment.

These may be assigned individually. Each must produce its own plan, tests and acceptance criteria once actual dependencies are known.

## 8. Common acceptance requirements

Regardless of chosen subproject:

- UI changes cannot mutate processes unintentionally, lose open runs or expose restricted command/environment content.
- Long output and large historical registries must remain responsive through bounded retrieval/rendering.
- Open tabs must be keyed by unique Run ID; log pane closing is view-only.
- Resizing/docking should not corrupt terminal viewport geometry or ongoing process state.
- Missing per-stream/history/telemetry data must be honestly described, not fabricated.
- New write capabilities must use the verified authorized backend action model and be isolated in testing.
- Visual and keyboard interaction must remain accessible and coherent at common desktop/ultrawide widths.

## 9. Agent handoff instruction

> Treat **RUNMUX-WEB-P6** as a candidate roadmap, not blanket implementation authorization. First select **one** independently scoped subproject (6A–6D), inspect current source/API coverage and present unresolved UX/security decisions. Build only the approved slice, preserving Runmux registry and terminal semantics. Run validation with disposable registries and synthetic output. Return a concise PR/test report and recommend the next independent slice; do not create speculative navigation pages or backend services solely to mimic mockups.
