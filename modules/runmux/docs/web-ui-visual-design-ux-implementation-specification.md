# Runmux Web UI — Visual Design & UX Implementation Specification

**Version:** 0.1 — Working Design Specification
**Status:** Partially approved; several design decisions remain open
**Target:** Runmux browser-based process management interface
**Primary audience:** Coding agent responsible for the Runmux Web UI and reusable `web_ui_tools` framework

---

## 1. Purpose and Design Philosophy

Runmux is a Python utility for managing persistent, long-running CLI processes. It has a backend with process registration, supervision, lifecycle operations, logs, and terminal attachment.

The browser UI should combine two complementary interaction models:

1. **Developer workspace:** A dark, IDE-like environment for opening processes, switching between them, inspecting their details, and reading logs.
2. **Process-monitoring dashboard:** A high-information-density interface for understanding process states, monitoring resource consumption where available, identifying failures, and navigating large collections of processes.

The interface should feel like a polished developer tool, not an administrative CRUD dashboard.

### 1.1 Primary design objectives

- Support efficient monitoring of multiple long-running processes.
- Make process state, identity, and recent output immediately accessible.
- Optimize screen space for readable CLI output.
- Support keyboard-oriented workflows without sacrificing mouse usability.
- Adapt well to desktop, widescreen, and ultrawide monitors.
- Allow users to customize information density and panel arrangement.
- Preserve workspace preferences across page reloads.
- Accommodate hundreds of registered or historical processes without clutter.
- Avoid implying capabilities that the backend does not provide.
- Keep process execution independent of browser navigation and UI lifetime.

### 1.2 Progressive implementation principle

**Implement simple components first, then extend them with optional capabilities.** For example, begin with a simple log viewer, then add search, facets, counts, advanced navigation, multiple streams, and split panes. Start with a Details tab before considering an inspector. Avoid complex abstractions for unscheduled features while keeping component boundaries extensible.

## 2. Approval and Decision Status

### 2.1 Approved design decisions

| Component | Approved direction |
|---|---|
| Overall visual direction | Dark, technical, IDE/dashboard hybrid |
| Process navigation | Hybrid D: searchable process explorer plus opened-process tabs |
| Process grouping | Switchable, status grouping by default |
| Process overview | Four configurable views: A, B, C, D |
| Overview switching | Cycle button and direct mode selection |
| Overview persistence | Last-used view mode is global and restored |
| Detailed metrics | Independent, optional metrics drawer in the longer-term design |
| Initial log viewer | A — Simple terminal |
| Enhanced log viewer | B — Enhanced terminal becomes the eventual default |
| Advanced logs | Multiple stream tabs, split panes, and keyboard navigation |
| General development approach | Simple first, advanced optional functionality later |

### 2.2 Provisional decisions

- Implement a standard Details tab first.
- A right-side inspector/drawer is the preferred future extension; it may eventually be pinnable and resizable.
- Bottom docking is optional and undecided.
- Compact inline metrics may suit the initial overview, but no first metrics presentation is required.

### 2.3 Decisions still open

- Exact process discovery page layout.
- Default widths and resize limits for panels.
- Whether explorer and primary navigation form one sidebar or two.
- Exact tab-overflow policy.
- Inspector docking options and persistence.
- Advanced keyboard shortcut assignments.
- Dashboard card styles and chart behavior.
- Theme switching and light-theme design.
- Process launch UX.
- Historical-process browsing and archival UX.

Do not treat open questions as final approval.

## 3. Overall Application Layout

### 3.1 Preferred desktop structure

Use a persistent application shell containing global navigation, a process explorer, process workspace tabs, a selected-process header, a main content workspace, and optional auxiliary panels. These are structural regions, not fixed dimensions. Favor expanded log content on widescreen displays. On constrained desktop windows, collapse global navigation to icons, allow the explorer to be hidden, and prioritize selected-process content.

Potential destinations include Processes, Logs, Sessions, Templates or Presets, Schedules, Environments, and Settings. Enable only destinations backed by implemented functionality; do not add empty pages.

Suggested sizing guidelines, subject to testing: collapsed global navigation approximately 56–72 px; explorer approximately 240–340 px initially; future inspector approximately 300–420 px; log viewer fills remaining height; header and tabs have compact stable heights. Long names, commands, and paths must not force whole-app horizontal overflow.

## 4. Process Navigation — Approved Hybrid D

### 4.1 Core concept

Combine a persistent, searchable process explorer with tabs representing opened process views, analogous to a file explorer plus editor tabs. The explorer supports discovery; tabs represent the current working set.

### 4.2 Process explorer

Where available, entries present process name, lifecycle status, short command or description, uptime, optional resource summary, and selection. Keep rows compact. Status colors must be accompanied by text or another cue.

### 4.3 Switchable grouping

**Approved default: Group by status.** Additional choices may include workspace or user-defined grouping where supported, category, and an ungrouped list. Only use lifecycle categories represented by actual backend state. Persist grouping preference where practical.

### 4.4 Searching and filtering

Eventually support name, command, status, tags/category when supported, working directory where useful, and sorting by name, status, start time, or recency. Filtering must not modify the registry. Initial implementation may use text search and status filtering.

### 4.5 Process tabs

Show truncated name, status, selected styling, and a close-view action. Selecting an already-open process activates its existing tab. Optional future features include pinning, overflow, context menus, reordering, resource indicators, and keyboard switching.

**Critical invariant: Closing a process tab closes only the UI view. It must never stop, unregister, or otherwise modify the underlying process.**

### 4.6 Tab overflow and workspace persistence

Keep many tabs usable with a bounded strip and overflow list or searchable switcher; do not shrink tabs into unreadable fragments. Eventually remember open tabs, active tab, explorer visibility and width, expanded groups, grouping preference, and global overview mode. Store browser preferences separately from process state. Restore gracefully when a process no longer exists.

## 5. Process Overview and Metrics — Approved Configurable Layouts

These are information-density settings for one process, not separate process models.

- **Mode A — Minimal:** Maximize log space; show name, status, useful ID, compact command preview, and essential navigation; avoid prominent charts.
- **Mode B — Inline Metrics:** Balance visibility and logs with compact facts such as CPU, memory, I/O, uptime, and start time where available.
- **Mode C — Dashboard Cards:** Compact cards and optional sparklines for CPU, memory, disk I/O, network, and supported metrics.
- **Mode D — Expanded Header:** More metadata and larger charts for investigations; includes trends only when supported.

Provide a cycle action and a direct selector. Suggested order A → B → C → D → A. Persist the last-used global mode across process switches and reloads. A future detailed metrics drawer is independent of these modes and may offer charts, time ranges, metadata, and availability indicators.

**Do not fabricate telemetry.** Hide an unavailable chart or mark it unavailable; never silently substitute zero. Historical charts require real time-series data. Define percentage denominators clearly.

For the initial read-only milestone, expose actual backend metadata; add dashboard presentations incrementally when telemetry support is verified.

## 6. Log and Output Viewer — Approved Progressive Design

### 6.1 General direction

Give logs substantially more workspace than decorative headers, oversized metrics, or secondary panels. **Phase 1: A — Simple terminal. Later: B — Enhanced terminal becomes the default.** Subsequent features may add output-stream tabs and split panes.

### 6.2 Phase 1 — Simple terminal

Provide monospaced readable output, efficient live updates, follow-tail, manual scrolling without forced jumps, bounded display, and clear loading, empty, disconnected, and error states. Search, line limits, and pause-display are desirable but not blockers. Preserve original output ordering and content as provided by the backend.

### 6.3 Bounded output

Do not indefinitely append DOM nodes. Use bounded rendering, virtualization, or another controlled method compatible with the transport. Keep retrieval limits, retained buffers, and rendered rows conceptually distinct. Opening a process that ran for days must remain responsive.

### 6.4 Follow and pause behavior

Follow-tail scrolls while the user is at the end. Scrolling upward suspends auto-follow until the user resumes. **Pause display must never pause execution.** Any Clear action must distinguish viewer buffer from persisted logs; initial read-only scope must not delete logs.

### 6.5 Phase 2 — Enhanced log viewer B

Enhancements include text and regex search, case controls, next/previous navigation, recognized log-level filtering, level counts, error/warning visibility, advanced buffer navigation, and keyboard shortcuts. Counts must state their scope.

### 6.6 Unstructured output handling

Support plain text, mixed stdout/stderr, ANSI decoration, structured logging, progress updates, and lines without timestamps or severity. Preserve unrecognized lines. Do not attribute merged logs to separate streams retroactively.

### 6.7 Future mode switching and multiple sources

Future modes: one full-width log, resizable split panes, and tabs for multiple actual streams. Only expose stdout/stderr separately if Runmux retains them separately. If output is merged, represent it as combined output. Split panes should eventually have independent scroll, follow, search/filter, and optional horizontal/vertical splitting.

### 6.8 Keyboard navigation

Desired future commands include `/` for search, `n`/`N` for next/previous result, `f` follow, `p` display pause, `?` help, and configurable pane/layout navigation. Do not depend on Ctrl+W, which browsers reserve. Avoid interfering with text entry, accessibility, or clipboard behavior. Shortcuts are not a Phase 1 requirement.

### 6.9 State preservation

Switching processes or layouts should ideally retain search, filters, scroll position, follow state, selected stream, and pane layout. Avoid unlimited browser persistence of raw log content; persist lightweight view preferences and retrieve output as needed.

### 6.10 Interactive terminal attachment

Browser PTY attachment is outside the initial read-only milestone. A log viewer is not automatically an interactive terminal. Future attachment requires analysis of input, authorization, terminal escapes, resizing, reconnect behavior, and session ownership. Do not add command input to the basic log viewer.

## 7. Process Details and Inspector — Provisional Direction

Initially show a Details tab with actual metadata: name, status, command/arguments, working directory, process or registry ID, start time, elapsed duration, and other available fields. Support long values and offer copy affordances where helpful. Do not expose sensitive environment values indiscriminately.

A future on-demand right inspector may contain Details, Resources, Events, Files, and Environment only when supported. The preferred extension combines an on-demand drawer with a pinnable persistent right panel and resizing. Bottom docking remains undecided; do not build a generalized docking engine for speculation.

Overview modes control workspace information density; an inspector is supplementary and optional.

## 8. Process Discovery and Overview Page — Open Design Area

A dedicated Overview/All Processes page may eventually add a sortable table, status filtering, search, grouping, future bulk selection, high-level counts, and access to completed/failed runs. Distinguish active processes from history. Show resource totals only when reliable. Large history may need pagination or virtualization, date filtering, archives, recent failures/completions, or saved searches. These are future options.

## 9. Process Creation and Lifecycle Controls — Deferred

Mockup actions such as New Process, Duplicate, Restart, Pause, Resume, Stop, and Archive are future functionality, not current browser capabilities. Process launch UX remains open. Stopping, terminating, or deleting registrations must be explicit and identify the target unambiguously. Do not visually equate closing a tab with terminating a process. Do not expose write controls before backend integration and authorization support them.

## 10. Visual Style

### 10.1 Direction

Dark, technical, compact but readable, high-density, subtle separators, limited decoration, clear status emphasis, and strong hierarchy. Combine an IDE feel with monitoring clarity.

### 10.2 Suggested semantic color tokens

| Token | Suggested value |
|---|---|
| Main background | `#0B111B` |
| Sidebar background | `#101925` |
| Surface | `#141F2D` |
| Elevated surface | `#1A293A` |
| Border | `#26384A` |
| Primary text | `#E8EFF7` |
| Secondary text | `#A6B6C8` |
| Muted text | `#8194A8` |
| Primary accent | `#3B82F6` |
| Running | `#22C55E` |
| Warning / waiting | `#F59E0B` |
| Failure | `#EF4444` |
| Informational | `#38BDF8` |
| Purple accent | `#A78BFA` |

These are starting suggestions; use semantic tokens. Status must remain distinguishable without color alone. Use a modern sans-serif for UI and monospace for commands, paths, logs, and identifiers. Avoid heavyweight fonts. Prefer 4 px spacing increments, compact controls, and panels that do not displace logs. Use an existing coherent icon family; do not mix unrelated sets.

## 11. Reusable Component Structure

Inspect `web_ui_tools` before adding reusable components. Potential primitives include status indicators, process rows, tabs, searchable lists, resizable panels, terminal-style viewers, metric cards, toolbars, and empty/loading states. Keep Runmux process logic separate from generic visual primitives.

Separate backend retrieval, state presentation, navigation, display preferences, log transport/buffering, parsing/filtering, layout, and future mutation actions where useful. Do not build a generic dashboard or docking framework before a concrete need.

## 12. Keyboard and Interaction Philosophy

Eventually support keyboard-first navigation alongside mouse use: search, open, switch/close tabs, toggle explorer, cycle overview, navigate log search, follow, switch panes, and command palette. Avoid browser-critical bindings. Make shortcuts discoverable and context-aware. Configurable shortcuts are future capability.

## 13. Empty, Error, and Disconnected States

- No processes: explain the empty registry; do not fabricate samples.
- No selection: show neutral guidance.
- No logs: show an explicit empty-output state.
- Process terminates while viewed: update status and preserve available history; do not close the tab.
- Backend disconnected: distinguish connection failure from empty registry and do not imply processes stopped.
- Metrics unavailable: state unavailability honestly.
- Long names/commands/paths: truncate, wrap, scroll, or expand while keeping full values accessible.

## 14. Security and Safety Constraints

Preserve Runmux security boundaries and verify real backend contracts. Do not expose unauthenticated administrative controls; preserve localhost restrictions; avoid leaking access codes through logs, URLs, or persistent storage; treat logs and commands as sensitive and untrusted; render logs as text safely; do not send metadata/logs to external visualization services; do not persist secrets in preferences; respect registry, supervisor, lifecycle, and input-ownership semantics. Initial read-only actions must not mutate state. Security mechanisms must be grounded in the implementation, not invented from the mockup.

## 15. Proposed Implementation Stages

These are recommendations, not instructions to implement every stage at once.

1. **Functional read-only foundation:** dark shell, hybrid navigation, status grouping where supported, tabs, header, Details, simple logs, and empty/error/disconnected states. No lifecycle, launch, interactive PTY, or speculative telemetry.
2. **Navigation refinement:** search/filter, tab overflow, preference persistence, resizable explorer, keyboard navigation, follow/scroll, basic search.
3. **Enhanced logs:** search navigation, severity filtering/counts, shortcuts, then streams/splits subject to backend support.
4. **Configurable monitoring:** four overview modes, global persistence, detailed metrics drawer when telemetry is reliable.
5. **Optional workspace customization:** inspector, docking, advanced tabs/layouts/shortcuts.
6. **Process management:** launch, presets, lifecycle operations, interactive terminal attachment, history/scheduling only under separate requirements and security review.

Adjust sequence to repository state, dependencies, and evidence.

## 16. Acceptance Criteria

### 16.1 Initial read-only milestone

- Coherent dark desktop UI.
- Searchable explorer with backend-accurate status and default status grouping.
- Selection opens or activates a process tab; switching and closing never affect execution.
- Readable details, including long values.
- Actual logs with bounded rendering and predictable follow/manual scroll.
- Distinct empty, loading, disconnected states.
- Unsupported data and metrics are not presented as real.
- No mutation through the read-only interface.
- Usable keyboard focus and essential contrast.

### 16.2 Future feature acceptance criteria

- Four overview modes retain process identity/workspace; global choice persists.
- Filtering preserves original output; counts describe their scope.
- Split panes maintain independent state; tabs represent actual streams.
- Inspector visibility does not destroy unrelated state.
- Charts use real telemetry.
- Layout restoration handles missing/terminated runs safely.

## 17. Reference Mockups

Visual exploration includes dark IDE, light monitoring, dark tabbed workspace, Hybrid D navigation, four overview modes, log-viewer comparisons, stream/split examples, and detail/inspector placement. Treat them as visual references, not pixel-perfect contracts or evidence of backend functionality. Retain compact process tabs, searchable status-grouped navigation, distinct lifecycle indicators, dense selected-process information, large readable logs, subtle dark surfaces, optional metrics/panels, and clear keyboard/mouse affordances.

## 18. Instructions for the Implementation Agent

Before significant implementation or planning:

1. Inspect current Runmux frontend, backend contracts, and `web_ui_tools`.
2. Compare actual functionality with this specification.
3. Identify reusable components and avoid duplication.
4. Preserve registry, supervision, logging, and security semantics.
5. Separate approved requirements from provisional/open choices.
6. Prefer the smallest coherent implementation advancing the read-only milestone.
7. Identify unsupported data requirements before depending on them.
8. Validate with representative long-running process and log data.
9. Do not assume mockup features exist in the backend.
10. Do not interpret this document as authorization to modify code or expand scope beyond a separate assignment.

Perform independent technical analysis. UX objectives and interaction invariants guide decisions; suggested components, colors, and dimensions are starting points.

## 19. Outstanding Design Work

| Area | Unresolved decision |
|---|---|
| Process inspector | Right drawer, pinnable panel, or bottom docking |
| Process overview | Dedicated page versus explorer/workspace integration |
| Process tables | Columns, density, sorting, history |
| Global navigation | Compact rail versus expanded navigation |
| Layout persistence | Storage and restoration rules |
| Metrics | Sources, windows, chart presentation |
| Log viewer | Shortcut configuration and multi-pane behavior |
| Process creation | Dialog, drawer, page, or command palette |
| Light theme | Whether and how to support it |
| Settings | Layout, appearance, and keyboard preferences |

## 20. Final Design Summary

Runmux's preferred interface is a **dark, developer-oriented, hybrid process workspace** with searchable status-grouped navigation, process tabs, a compact header, four information-density modes, a large terminal-style output area, optional enhanced logs, initial Details, future inspector/metrics drawer, and UI preferences independent of process execution. Progress deliberately from simple read-only functionality to richer monitoring and management.

**Primary implementation priority: Deliver a stable, responsive, read-only process workspace before implementing optional UI complexity.**

This is a working design specification, not approval of every feature or authorization to exceed a separately assigned scope.
