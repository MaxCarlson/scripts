# Runmux Web UI — Phase 3 Agent Handoff: Explorer, Tabs and Process Details

**Phase ID:** RUNMUX-WEB-P3  
**Status:** Planned; inspect actual metadata and UI state before implementation  
**Priority:** **P1** user productivity and correctness  
**Primary backlog:** N01–N08, D01–D05, W01–W04, W12, S06–S07, S12; baseline H01–H04 as supported.

## 1. Objective

Turn the existing functional-but-basic process explorer into a scalable, reliable **hybrid navigation workspace**. Retain the current dark style, searchable left process list, opened-run tabs and Details view; add flexible grouping, sorting, stronger tab handling, persistence and informative/authorized metadata.

This phase should improve the current implementation, **not** replace it with a new visual framework.

## 2. Current visual baseline

Current screenshots show a left-side Processes list grouped as Running, Disconnected, Completed, and Killed. Each entry has a name, secondary identifier, time and state badge. Several distinct runs share names (`file-util`, `mangadl`, `ytaedl`); tabs exist and can switch among runs. A Details tab displays Run ID, PID, exit code, runtime and timestamps while hiding command arguments and working directory for privacy. Status changes and persistence across reloads are **not** demonstrated by screenshots alone.

## 3. User-visible deliverables

### 3.1 Explorer grouping, filtering and sorting

- **Status grouping remains the default.** A grouping selector offers status, ungrouped, and other modes **only** when relevant metadata is available (e.g., category, workspace, tag).
- Search process name and available command/metadata fields according to authorization. Filtering must never change registry contents.
- Add status filters and sorting by relevant attributes such as last activity, start time, name and duration; availability should reflect actual API fields.
- Preserve expanded/collapsed groups and filtering preference in lightweight browser state; do not store credentials or full logs.
- Handle large run counts without rendering an unlimited process-list DOM. If backend pagination is required, plan it based on real API constraints.
- When no results match, show a useful *no matching processes* state distinct from an empty registry.

### 3.2 Process tabs and selection

- Each run view is keyed by immutable, unique **Run ID**; identical display names must never collide.
- Clicking a listed run activates its existing tab or opens exactly one view tab.
- Closing a tab closes only the view and never changes supervisor/process state.
- When tabs overflow, maintain readable labels and a usable switcher (scroll or menu); do not force a sophisticated docking system.
- Restore open/selected tabs on reload where practical. If runs disappeared, drop or label stale entries gracefully.
- Clarify whether the current UI already persists this state before adding replacement logic.

### 3.3 Process header and details

- Present a compact selected-run header containing status, stable identity and essential time/command/cwd information **where authorized**.
- Maintain a Details tab for full values and copy actions for useful IDs/paths/commands.
- The current UI explicitly hides commands and working directories for privacy. **Do not remove this protection without a verified authorization model.** An HTML-only reveal button is not authorization: current Runmux API **omits** these fields. Do not extend the API to expose full command/cwd by default. Document a proposed deliberate server-side disclosure policy and seek user approval before implementing new disclosure.
- Use consistent absolute/relative timestamps, handle long commands and paths without layout breakage, and distinguish unavailable fields from empty strings.
- Improve visual density: output should remain the dominant area.

### 3.4 Reconciliation and status language

- Distinguish **registry disconnected** from a run marked `LOST`/Disconnected and from an ordinary completed or terminated run.
- Apply backend state updates to explorer rows, tabs and current details consistently without falsely reopening or duplicating runs.
- Use actual backend lifecycle vocabulary rather than replacing `Killed` and `Lost` with invented categories to match conceptual artwork.
- If history pages or retained output are already available, make navigation coherent; full history search/event timelines belong to Phase 6.

## 4. Out of scope

Do not introduce browser process lifecycle operations, resource metrics charts, advanced log filters, arbitrary tag editing, generalized saved workspaces, or a completely new navigation hierarchy in this phase. Global menu/command palette and reorderable pinned tabs can wait for Phase 6.

## 5. Technical investigation

1. Trace all process list/detail fields, sorting/filtering endpoints, run IDs and status enums.
2. Check how tabs, active selection, explorer state, and session authorization are represented in current frontend code.
3. Verify privacy rationale for hidden command/cwd fields; document whether existing API already withholds them or only hides them in UI.
4. Review any browser storage currently used. Keep UI preferences separate from supervisor/registry data.
5. Check state/update cadence and any stale lifecycle status issues, including multiple tabs open on one run.
6. Determine minimum responsive widths from actual layout rather than imposing fixed pixel widths from a mockup.

## 6. Validation matrix

| Test | Expected result |
|---|---|
| Two runs with identical name | Two distinct run IDs, entries and tabs |
| Hundreds of synthetic historical runs | Usable filtering and tab navigation without major lag |
| Switch grouping modes | List reorganizes, actual run states unchanged |
| Filter with zero matches | Search-empty state, not registry-empty message |
| Reload after opening several runs | Restores only valid views and correct active selection |
| Close a tab on running process | Supervised process remains running |
| Run exits while displayed | Explorer, tab and details reconcile correctly |
| Registry connection drops | Connection error distinct from per-run `LOST` |
| Long Unicode process name/path/command | Truncation/wrap access remains usable |
| Unauthorized session | Hidden command/cwd/secret fields remain protected |

All tests must run on disposable registries and synthetic processes. Check keyboard focus and accessible names on controls.

## 7. Acceptance criteria

- [x] Grouping is switchable, with status as default and no invented groups.
- [x] Search/filter/sort works on supported fields and preserves UI usability at scale.
- [x] Tabs and process selection uniquely identify **runs**, not names.
- [x] Closing a tab never mutates process state.
- [x] Workspace preferences restore safely with no sensitive data persisted.
- [x] Metadata presentation is richer yet honors existing privacy policy; full argv/cwd disclosure remains deferred.
- [x] Lifecycle/registry state is accurately reflected across UI components.
- [x] Representative responsive, accessibility and regression checks are recorded in the Phase 3 status report.

## 8. Agent handoff instruction

> Implement **RUNMUX-WEB-P3** from `PHASE_03_EXPLORER_AND_WORKSPACE.md`. First inspect the current process-list schema, unique IDs, state persistence, and authorization for command/cwd metadata. Enhance the existing dark explorer and tabs rather than replacing the UI. Add status-default switchable grouping, useful search/sorting, overflow handling, safe view persistence and improved Details. Validate with synthetic same-named processes and a large registry; report tested behavior and deferred items.
