# Runmux Web UI — Gap Analysis & Feature Backlog

Comparison: Current Runmux Web UI (October 24, 2026) versus the full-featured Runmux design.

## Executive summary

The current implementation has the basic foundation we wanted: a dark interface, status-grouped process explorer, process tabs, live output, a terminal view, and a details view.

However, it is still primarily a read-only process inspector, rather than the full process-management workspace we envisioned.

The largest gaps are:

1. Process launching: The browser cannot launch new processes. This should be the first major functional addition.
2. Terminal/output fidelity: The screenshots reveal substantial formatting problems with interactive CLI applications such as MangaDL and `file-util`. This deserves high priority.
3. Process information: The selected-process header is sparse, and important details such as command arguments and working directories are hidden.
4. Process management: There are no visible browser controls for stopping, restarting, pausing, duplicating, or otherwise managing processes.
5. Monitoring: The configurable A/B/C/D process overview modes, resource metrics, charts, and detailed monitoring panels are absent.
6. Advanced log management: Search, severity filtering, error counts, stream tabs, split panes, and output navigation are missing.
7. Workspace customization: Explorer grouping, resizable panels, saved layouts, richer navigation, and keyboard-oriented workflows are largely missing.

There are also secondary gaps involving process history, events, alerts, appearance, discoverability, and accessibility.

Important distinction: This is a visual and requirements-based audit, not a source-code audit. Features marked missing below are not visible in the supplied screenshots; some may already exist internally. Backend support and security behavior must be verified before implementation.

## 1. What the current UI already provides

| Feature                    | Assessment | Observations                                                    |
| -------------------------- | ---------- | --------------------------------------------------------------- |
| Dark desktop interface     | Present    | Visually consistent developer-oriented styling                  |
| Process explorer           | Present    | Left-side list with process entries                             |
| Process status grouping    | Present    | Running, Disconnected, Completed, Killed                        |
| Process search field       | Present    | Search input visible; filtering behavior not tested             |
| Multiple process tabs      | Present    | `file-util`, MangaDL, and other runs can be opened              |
| Process selection          | Present    | Selected rows and tabs are highlighted                          |
| Read-only live output      | Present    | Output and Follow controls visible                              |
| Separate terminal view     | Present    | ANSI Terminal view and read-only status visible                 |
| Process details            | Partial    | Run ID, PID, exit code, timestamps, runtime                     |
| Registry connectivity      | Present    | Connection and local-session indicators                         |
| Refresh and lock controls  | Present    | Visible in the global header                                    |
| Missing-history indication | Present    | Lost process explicitly reports that earlier output was omitted |
| Empty-state handling       | Present    | No-process state shown, but without a browser launch action     |

The existing layout is a reasonable starting point. I would not recommend replacing the UI or rebuilding the application shell. Most of the work should extend and improve the existing interface.

## 2. Highest-priority addition: Launch processes from the browser

P0 — Next functional milestone

This is a change to our original read-only milestone. It is now an explicit requirement.

### 2.1 Required user experience

The tab strip should have a + button, even when no processes are currently open.

Clicking it should open a new, temporary tab containing a process-launch form.

New Process

Proposed layout

Command

python -m mangadl compress -d B:\Hent --inventory-depth files

Equivalent to supplying these program arguments to `runmux run`.

Working directory

Current / configured default

Process name (optional)

Auto-generated

Cancel Launch Process

Static layout illustration, not a working launch form.

### 2.2 Functional requirements

| ID  | Requirement                                                                                               | Priority |
| --- | --------------------------------------------------------------------------------------------------------- | -------- |
| L01 | Add a `+` tab that opens the launch form                                                                  | P0       |
| L02 | Add a visible New Process action when no processes exist                                                  | P0       |
| L03 | Accept a command and its arguments                                                                        | P0       |
| L04 | Invoke the existing Runmux launch mechanism, matching `runmux run` semantics                              | P0       |
| L05 | Allow specifying a working directory, with an explicit default                                            | P0       |
| L06 | Validate input and display actionable launch errors                                                       | P0       |
| L07 | Show a pending state while launching; prevent duplicate submissions                                       | P0       |
| L08 | On success, replace the launch tab with the new process's real run tab                                    | P0       |
| L09 | Immediately expose the new process in the explorer and its output viewer                                  | P0       |
| L10 | Preserve the form when switching tabs; discard it only when deliberately closed or successfully submitted | P1       |
| L11 | Optional process name, environment overrides, and Runmux-specific flags                                   | P1       |
| L12 | Recent commands, reusable presets, and Duplicate Process                                                  | P2       |

### 2.3 Important backend considerations

The implementation agent must inspect the actual `runmux run` CLI contract.

The web UI should use the same underlying process-creation and supervision logic as the CLI, rather than inventing a separate process-launching implementation.

Particular attention is needed for command argument parsing, quoted paths, Windows versus POSIX behavior, working-directory resolution, environment handling, supervisor initialization, process registration, and launching commands that require a PTY.

Do not simply pass the submitted text to `shell=True`. Commands should be interpreted according to Runmux's established invocation contract, with explicit support for shell execution only if that is an intentional, separately defined mode.

The launch operation must also respect the web session's authorization. Currently the browser identifies itself as read-only and provides a Lock control; making it capable of arbitrary process execution introduces a significant security boundary.

### 2.4 Launch acceptance test

A successful end-to-end test should be able to:

1. Open Runmux with an empty registry.
2. Click New Process.
3. Enter a harmless long-running test command.
4. Launch it successfully.
5. See the newly registered run appear in the explorer.
6. See its output update in the browser.
7. Close its browser tab and verify that the supervised process continues running.
8. Reopen the run and continue viewing its output.

The test must use an isolated registry and synthetic process—not the user's real Runmux environment.

## 3. Terminal and log rendering: A major correctness gap

Priority: P0–P1

The current screenshots expose an important issue not represented adequately by the finished mockup.

The CLI programs you are monitoring are not all line-oriented applications. Some are sophisticated TUIs that redraw the screen, use cursor positioning, update progress bars, and output ANSI control sequences.

### What the screenshots reveal

[opencode 求助，退出使用后终端不停输出内容 - 开发调优 - LINUX DO](https://images.openai.com/static-rsc-4/zReUhe_MTLO-iwo0NhBB4VnPc8NpB-Hj4hMUuTHP8AIh9hNXaAdADoypEqy7Ne9hToSHqKv--R2NpveoNdku1Fb7OO3y7o69MUjcikZB5M9mO7WCShSJy0S8_BG4Eq4aGgmY_Lfyl2Pl8eg5s1iNK1IZQUlBrg5tvhkmQvt6N24?purpose=inline)

MangaDL — Output tab

The displayed text contains flattened menus, overwritten status lines, concatenated metrics, and broken alignment. A large amount of screen space is also unused.

[Web Weekly #132](https://images.openai.com/static-rsc-4/FGxbXX8RlrxfdBYSVuJUkYCNVfL4gPncJQhKmClg-nRXbfmDhtyFUmY2-7fVqXebeSzYgDuFsyNLaMh75SEhHFbD5Zlde37WObx4GrMc-tKW12je0BKHEaSpAJs1WiqM5CJ2RRx31ormbAmmlbt0WF3l8gHmZd6jSUZC0SQxOYc?purpose=inline)

file-util — Output tab

TUI columns and instructions are interleaved. This is not a faithful rendering of the program's terminal screen.

These are illustrative visuals; the findings refer to your uploaded Runmux screenshots.

The separate Terminal tab is promising because it already has a read-only terminal mode and a Request control action, but the MangaDL terminal screenshot also shows alignment and layout problems. It's not yet clear whether those originate in terminal sizing, PTY data capture, output interpretation, or another layer.

### Required improvements

| ID  | Feature                                                                                               | Priority |
| --- | ----------------------------------------------------------------------------------------------------- | -------- |
| T01 | Investigate where ANSI/TUI rendering breaks: capture, storage, transport, or browser rendering        | P0       |
| T02 | Correctly distinguish append-only log output from terminal-screen state                               | P0       |
| T03 | Verify terminal column/row dimensions and resizing                                                    | P0       |
| T04 | Ensure terminal output is rendered using an appropriate terminal emulator, not ordinary HTML wrapping | P0       |
| T05 | Preserve support for simple, non-ANSI, line-oriented logs                                             | P0       |
| T06 | Implement reliable follow-tail, scrollback, and manual scroll behavior                                | P1       |
| T07 | Make buffering and historical truncation understandable                                               | P1       |
| T08 | Support output search, next/previous match, and case-sensitive/regex modes                            | P1       |
| T09 | Implement recognizable log-severity filters and correctly scoped counts                               | P2       |
| T10 | Support separate stdout/stderr streams where the backend retains them                                 | P2       |
| T11 | Add switchable single, split, and tabbed stream layouts                                               | P2       |
| T12 | Complete an explicitly authorized interactive PTY attachment workflow, if not already implemented     | P2       |

Two different display models should remain available:

Output: An append-only stream suitable for searching, reviewing history, and understanding log activity.

Terminal: An emulated terminal screen suited to programs that use cursor movement, redraw their entire display, or expect a PTY.

A terminal screen cannot always be reconstructed correctly from an arbitrary truncated tail of a byte stream. The implementation should verify whether complete replay, snapshots, or a live attachment are necessary.

I would prioritize this issue before introducing advanced monitoring charts. Runmux's main job is supervising CLI applications, and displaying their output accurately is central to that purpose.

## 4. Remaining feature inventory

The following backlog maps the rest of the finished design against what is visible in the current browser interface.

Priorities mean:

- P0: Core functional or correctness work.
- P1: Important functionality for a useful day-to-day process manager.
- P2: Full-feature enhancements.
- P3: Optional polish and advanced customization.

### 4.1 Navigation and process discovery

The current explorer is functional but considerably simpler than the finished design.

| ID  | Missing or incomplete feature                                                         | Priority |
| --- | ------------------------------------------------------------------------------------- | -------- |
| N01 | Switchable grouping: status, category, workspace, or ungrouped                        | P1       |
| N02 | Status filters independent of grouping                                                | P1       |
| N03 | Sorting by name, recency, duration, start time, and status                            | P1       |
| N04 | Search commands, names, tags, and other supported metadata                            | P1       |
| N05 | Resizable and collapsible process explorer                                            | P1       |
| N06 | Better tab overflow when many process views are open                                  | P1       |
| N07 | Preserve opened tabs and active selection across browser reloads                      | P1       |
| N08 | Distinguish and navigate multiple runs sharing the same process name                  | P1       |
| N09 | Dedicated All Processes overview/table                                                | P2       |
| N10 | Workspace/category navigation                                                         | P2       |
| N11 | Pinned and reorderable process tabs                                                   | P2       |
| N12 | Global search or command palette                                                      | P2       |
| N13 | Collapsible global navigation rail for Logs, Processes, Settings, and future sections | P2       |
| N14 | Keyboard shortcuts for switching tabs and selecting processes                         | P2       |

One especially important design requirement is N08. Your current screenshot shows several historical runs with identical names, including multiple `file-util` and MangaDL entries.

The browser must use the unique Run ID for selection, tabs, API operations, and persistence. A process name is a display label, not a unique identifier.

### 4.2 Process information and details

Your current Details tab is sparse compared with both our minimal specification and the finished mockup.

It exposes Run ID, PID, exit code, runtime, start time, and end time. It also explicitly states that command arguments and working directories are hidden for privacy.

That privacy behavior might be intentional and appropriate. The design should provide authorized access to useful information without weakening its security model.

| ID  | Missing or incomplete feature                                         | Priority |
| --- | --------------------------------------------------------------------- | -------- |
| D01 | Display the complete command and arguments when explicitly authorized | P1       |
| D02 | Display the working directory when explicitly authorized              | P1       |
| D03 | Copy command, path, PID, and Run ID                                   | P1       |
| D04 | More informative compact process header                               | P1       |
| D05 | Absolute and relative timestamps with consistent formatting           | P1       |
| D06 | Display available executable, environment, host, and session metadata | P2       |
| D07 | Optional tags and categories                                          | P2       |
| D08 | Process restart count and lifecycle history                           | P2       |
| D09 | Display resource limits and supervision policy when available         | P2       |
| D10 | Advanced metadata and notes                                           | P3       |

For D01/D02, a reasonable approach would be to keep sensitive values hidden by default and provide a deliberate reveal action after confirming that the session is authorized.

The current broad Run Inspector header could also be condensed to make more room for logs.

### 4.3 Process lifecycle controls

The finished design contains actions that are not available in the current browser screenshots.

| ID  | Feature                                                          | Priority |
| --- | ---------------------------------------------------------------- | -------- |
| C01 | Launch a process                                                 | P0       |
| C02 | Stop or terminate a running process                              | P1       |
| C03 | Restart an eligible process                                      | P1       |
| C04 | Pause/resume when supported by the OS and Runmux                 | P1       |
| C05 | Clear display pause versus actual process pause distinction      | P1       |
| C06 | Confirm destructive process actions                              | P1       |
| C07 | Display pending, succeeded, and failed lifecycle actions         | P1       |
| C08 | Duplicate an existing process configuration into the launch form | P2       |
| C09 | Modify process metadata or labels                                | P2       |
| C10 | Archive/remove records when supported                            | P2       |
| C11 | Bulk lifecycle operations                                        | P3       |
| C12 | Configure restart policies and scheduling                        | P3       |

Some of these may already have backend implementations. The agent should discover and reuse them.

Do not expose controls for unsupported state transitions. For example, Killed, Finished, and Lost do not necessarily permit the same restart or resume operations.

### 4.4 Configurable process overview and metrics

This was one of our explicitly approved design decisions.

The finished version supports four modes for how much process information is visible. None of those controls is visible in the current UI.

| ID  | Feature                                                | Priority |
| --- | ------------------------------------------------------ | -------- |
| M01 | A — Minimal overview                                   | P1       |
| M02 | B — Compact inline metrics/information                 | P2       |
| M03 | C — Dashboard metric cards                             | P2       |
| M04 | D — Expanded monitoring header                         | P2       |
| M05 | Cycle-view button and direct mode selector             | P2       |
| M06 | Persist last-used overview mode globally               | P2       |
| M07 | Current process CPU and memory, where telemetry exists | P2       |
| M08 | Disk I/O and network throughput, where available       | P2       |
| M09 | GPU usage and memory, where supported                  | P2       |
| M10 | Historical charts and selectable time ranges           | P2       |
| M11 | Independent resizable detailed-metrics drawer          | P2       |
| M12 | Distinguish host-wide and per-process measurements     | P2       |
| M13 | Graceful states for unavailable telemetry              | P1       |

Recommended initial behavior: Treat the existing compact process header as the starting implementation of mode A. Expand into B/C/D once real metrics are available.

Don't build elaborate empty charts before telemetry collection and retention are implemented.

### 4.5 Inspector and supporting panels

The current UI has a Details tab but no apparent persistent right-side inspector.

| ID  | Feature                                                    | Priority |
| --- | ---------------------------------------------------------- | -------- |
| I01 | Optional right-side process inspector                      | P2       |
| I02 | Toggle inspector without replacing log content             | P2       |
| I03 | Pin/unpin inspector                                        | P2       |
| I04 | Resize inspector width                                     | P2       |
| I05 | Inspector sections for details, metrics, events, and files | P2       |
| I06 | Remember inspector visibility and width                    | P2       |
| I07 | Optional bottom docking                                    | P3       |
| I08 | Advanced multi-panel layout management                     | P3       |

The right inspector is particularly useful for simultaneous viewing of output and metadata. However, it should remain optional so the terminal can consume the full workspace when needed.

### 4.6 Events, alerts, and process history

The screenshots show lifecycle states and historical runs, but not the richer event/history experience illustrated by the finished design.

| ID  | Feature                                                      | Priority |
| --- | ------------------------------------------------------------ | -------- |
| H01 | Show recent completions and failures                         | P1       |
| H02 | More detailed historical run information                     | P1       |
| H03 | Explain disconnected/lost supervision states clearly         | P1       |
| H04 | Browse retained output beyond the initial tail, if available | P1       |
| H05 | Structured process lifecycle event timeline                  | P2       |
| H06 | Search/filter events by type or date                         | P2       |
| H07 | Warning and error summaries                                  | P2       |
| H08 | Alerts for process failures and abnormal behavior            | P2       |
| H09 | Threshold-based CPU/memory/disk notifications                | P3       |
| H10 | Historical resource-usage comparisons                        | P3       |
| H11 | Configurable retention and archival management               | P3       |

For H04, your lost-process screenshot already reveals a useful starting point: the UI clearly indicates that only the latest 64 KiB of output is shown.

The agent should determine whether older output exists in persisted files and, if so, whether the browser can retrieve it safely in bounded chunks. This is preferable to assuming either that the earlier data is permanently missing or that every browser must load an entire multi-gigabyte log.

### 4.7 Workspace appearance and interaction

| ID  | Feature                                                   | Priority |
| --- | --------------------------------------------------------- | -------- |
| W01 | More compact information-rich selected-process header     | P1       |
| W02 | Use more available space for logs and terminal content    | P1       |
| W03 | Consistent text truncation and full-value inspection      | P1       |
| W04 | Better status labels, focus indicators, and contrast      | P1       |
| W05 | Keyboard-first navigation where practical                 | P2       |
| W06 | Contextual process actions and tooltips                   | P2       |
| W07 | Persistent explorer width, selected tabs, and preferences | P2       |
| W08 | Theme switching, including light mode                     | P3       |
| W09 | Adjustable information density and font sizes             | P3       |
| W10 | User-configurable shortcuts                               | P3       |
| W11 | Saved workspace/layout presets                            | P3       |
| W12 | Responsive behavior across desktop and ultrawide displays | P1       |

I would retain the existing visual language. The current UI is already close to our chosen dark theme.

Most of the visual gains should come from better information placement, reduced unused space, and flexible panels, not replacing colors, icons, or typography wholesale.

### 4.8 Security, reliability, and backend integration

These are less visible in screenshots, but are mandatory considerations for moving from read-only inspection into a browser that can launch and control programs.

| ID  | Requirement                                                                      | Priority |
| --- | -------------------------------------------------------------------------------- | -------- |
| S01 | Verify existing localhost binding and authentication/session protections         | P0       |
| S02 | Authorize process launching and other mutation requests                          | P0       |
| S03 | Validate command execution semantics and prevent unintended shell interpretation | P0       |
| S04 | Verify origin/CSRF protections for state-changing browser requests               | P0       |
| S05 | Isolate development/test registries and supervised processes                     | P0       |
| S06 | Reconcile process registry updates without duplicate or stale records            | P1       |
| S07 | Handle reconnection and browser reload without corrupting process state          | P1       |
| S08 | Safely render untrusted terminal/log output                                      | P0       |
| S09 | Do not expose sensitive environment values or access credentials inadvertently   | P0       |
| S10 | Bound output rendering, backend queries, and client memory                       | P1       |
| S11 | Test concurrent browser sessions and conflicting lifecycle requests              | P1       |
| S12 | Ensure run identity and state transitions are consistent with CLI behavior       | P1       |

One important detail: the top-right Registry connected indicator means the registry connection is healthy, but a particular process can independently have a Lost state. Those should remain distinct concepts.

## 5. Additional capabilities shown in the finished mockup

A few entire interface sections appear in the finished concept but not in the current screenshots.

| Feature           | Finished design                            | Suggested scope      |
| ----------------- | ------------------------------------------ | -------------------- |
| Launch page/form  | New Process controls and presets           | First implementation |
| Metrics tab       | Per-process resource information           | Later                |
| Environment tab   | View relevant environment information      | Later                |
| Files tab         | Inspect associated files or outputs        | Later                |
| Sessions tab      | Inspect and manage terminal sessions       | Later                |
| Events panel      | Timeline of process activity               | Later                |
| Notes             | Attach user annotations to runs            | Optional             |
| Templates/Presets | Save and reuse launch configurations       | Later                |
| Schedules         | Configure scheduled or recurring processes | Optional             |
| Storage view      | View retained output and storage usage     | Optional             |
| Settings          | Appearance, layout, retention, shortcuts   | Incremental          |
| System summary    | Host CPU, memory, disk, process counts     | Later                |

These should not automatically become separate top-level pages. The agent should determine which warrant dedicated navigation and which belong inside the process inspector or workspace.

## 6. Recommended implementation roadmap

I would break the work into six independently testable milestones rather than ask a single agent to implement the entire finished mockup in one pass.

## 1

Browser process launching

Highest immediate priority

Add the new-process tab, command input, launch integration, error handling, registry refresh, and automatic opening of the newly created run.

Dependencies: CLI launch contract, backend mutation endpoint, authorization

## 2

Terminal correctness and log reliability

High priority — largely independent of milestone 1

Investigate MangaDL and file-util output corruption, terminal sizing and PTY behavior, bounded historical output, follow mode, and reconnect behavior.

Dependencies: Existing output transport and terminal-emulation architecture

## 3

Process explorer and workspace improvements

Add switchable grouping, sorting, advanced search, resizable explorer, tab persistence, and richer process metadata. Improve layout density without replacing the existing styling.

Dependencies: Process metadata contracts and browser preference persistence

## 4

Process lifecycle management and enhanced logs

Add stop/restart/pause/resume where supported, plus improved log search, level filtering, severity counts, keyboard shortcuts, and stream navigation.

Dependencies: Authorized lifecycle APIs, structured or parseable log metadata

## 5

Monitoring and configurable process views

Introduce the A/B/C/D overview modes, global mode persistence, real CPU/memory/I/O telemetry, historical charts, and optional detailed metrics drawer.

Dependencies: Verified telemetry availability and, for charts, historical sampling

## 6

Full-workspace features

Add the optional pinned inspector, resizable log panes, tabbed streams, events, historical browsing, templates, advanced keyboard workflows, and further personalization.

Dependencies: Earlier milestones and remaining UI approvals

Milestones 1 and 2 could be developed on independent branches, provided they don't modify overlapping backend interfaces or frontend components concurrently.

## 7. What I would ask the implementation agent to investigate before planning

There are several architecture questions that could substantially change implementation complexity.

| Investigation                                                          | Why it matters                                                              |
| ---------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| How does `runmux run` register and supervise a process?                | Determines whether the web API can call an existing Python service directly |
| What launch-related backend endpoints already exist?                   | Avoids duplicating functionality                                            |
| How are arbitrary commands and arguments represented?                  | Ensures parity with CLI execution                                           |
| Does Runmux persist stdout/stderr separately?                          | Determines feasibility of stream tabs                                       |
| Are terminal sessions backed by a real PTY?                            | Critical to rendering interactive TUIs                                      |
| How is terminal output buffered and replayed?                          | Explains broken formatting and historical output limits                     |
| What is the read-only versus interactive terminal authorization model? | Required for launching and requesting control                               |
| Which process metrics are already collected?                           | Determines what the overview modes can display                              |
| How much of the `web_ui_tools` framework is reusable?                  | Influences component boundaries and scope                                   |
| How are runs uniquely identified and reconciled?                       | Important for tabs, history, and concurrent updates                         |

The actual repository implementation may also reveal already completed capabilities that aren't exposed in the screenshots. Those should be marked as UI integration work, not treated as entirely new features.

## 8. Recommended initial plan for the coding agent

The next task should be narrowly scoped to adding browser-based process launching, not undertaking the entire backlog simultaneously.

I would give the agent this acceptance contract:

> Implement a browser-based New Process tab that invokes the same underlying process-launch functionality as `runmux run`. Support entering a command and arguments, choosing a working directory, and handling launch failures. On successful registration, open the new run's process tab and make its output available through the existing viewer. Preserve the existing read-only inspection behavior and security restrictions for unauthorized sessions. Use synthetic processes and an isolated registry for validation. Do not implement the remaining full-dashboard features as part of this change.

After that, the output/TUI fidelity issue should receive a separate investigation and repair task.

### Next steps to explore

The full inventory above is intended as a feature backlog, not yet a repository-specific implementation plan. Before assigning individual changes, have the agent cross-reference each feature ID against the current `modules/runmux/` and `modules/web_ui_tools/` code, classify it as implemented, partially implemented, unsupported, or missing, and identify the affected backend/frontend interfaces.

That will give us a much stronger foundation for the actual staged implementation plan—and should prevent rebuilding features that are already present but simply not visible in the browser yet.