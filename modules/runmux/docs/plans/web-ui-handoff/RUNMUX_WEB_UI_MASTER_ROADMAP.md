# Runmux Web UI — Master Roadmap and Integration Contract

**Document ID:** RUNMUX-WEB-MASTER | **Revision:** 1.0 | **Date:** 2026-10-24  
**Repository:** `MaxCarlson/scripts` | **Scope:** `modules/runmux/`, `modules/web_ui_tools/`

## 1. Status and authority

This is the canonical **roadmap**, not authorization to implement all phases. Implement only a phase/slice explicitly assigned by the user. **Phase 1 was already assigned using a separate, shorter Milestone 1 handoff**; the Phase 1 document supplements that assignment. Send `CURRENT_AGENT_PHASE_01_ADDENDUM.md` to the working agent rather than replacing its prompt or starting it again.

The prior handoff authorizes scoped implementation, tests, documentation, a dedicated branch and push (**not merge**). Do not interpret this roadmap's planning language as revoking that instruction. Later phase assignments likewise authorize their named scope; architectural/product changes outside scope still require approval.

## 2. Existing implementation: don't rebuild it

Verified from repository files during roadmap revision (recheck current `origin/main` before implementation):

- `web_ui_tools` supplies the FastAPI app, localhost hosting, static assets, HTTP session/origin checks, and authenticated same-origin `/api` WebSocket admission (`modules/web_ui_tools/src/web_ui_tools/app.py`). The current login code is valid **until server exit**; the browser-session cookie has its own expiry. The **Lock** control logs out the session; it is not a separate elevated privilege tier.
- Runmux already has the searchable dark explorer, **status-grouped** list, multiple process *view* tabs keyed by run ID, Output/Terminal/Details, and read-only metadata projection.
- Runmux's browser Terminal **already supports xterm.js, WebSocket view/interact attachments, supervisor-managed FIFO input locking, authorized resize, reconnect cleanup, and replay of completed runs** (`modules/runmux/src/runmux/web.py`). No new browser PTY control architecture is required. Opening or closing a view never stops the managed process.
- `runmux run` already uses an argv-oriented CLI launch and supervisor path; inspect `modules/runmux/src/runmux/cli.py` and the underlying client before adding a web launch endpoint. No implicit `shell=True`.
- `modules/runmux/src/runmux/stats.py` already samples process-tree CPU, memory, disk I/O, and best-effort GPU statistics using `modules/resource_metrics/`. **Attribution caveat:** its current network delta comes from a host-wide counter and is populated on each process stats record; do not label it per-process network usage without a separate attribution solution.
- Current browser API deliberately omits full command arguments, cwd, and secrets. A UX mockup does not grant disclosure authorization.

Evidence limits: These facts are supported by source inspection, **not** end-to-end testing of every platform in this revision. Phase agents must verify the actual integration baseline. Observed MangaDL/`file-util` TUI rendering problems have not yet been assigned a root cause.

## 3. Product decisions and invariants

1. Retain dark desktop-first IDE-like workspace, searchable explorer, and process view tabs. Improve rather than rewrite.
2. Stable **Run ID**, never name, is authoritative for selection, tabs, API requests and saved view state. Names can repeat.
3. Output (searchable history/log representation) and Terminal (real emulated screen) are different display models. Do not promise faithful TUI recreation from an arbitrary truncated log tail.
4. Closing a tab, locking the browser session, clearing the displayed log, scrolling or pausing **follow** must never stop or pause the supervised process.
5. Existing browser sessions are authenticated, but process launch/stop/restart are **new write capabilities**. Require explicit user action plus server-enforced session/origin/CSRF protections; don't invent separate user roles solely because the old dashboard was called read-only. A material privilege-policy change should be raised before implementing it.
6. Avoid implicit shell execution, misleading metrics, invented severity counts, unbounded rendering, and disclosure of command/cwd/environment secrets.
7. All development and tests use isolated worktrees, disposable registries, synthetic processes, and dedicated ports; never touch the user's actual Runmux state, supervisors, processes, or another agent's worktree.
8. No new frontend framework, speculative backend service, or remote/network exposure solely to imitate a mockup.

## 4. Phase status / execution units

| Work package | Status at revision | Scope | Dependencies |
|---|---|---|---|
| **1 Launch** | **Merged to origin/main** | New Process tab and verified `runmux run` parity (L01–L09) | Existing auth and supervisor; send Phase 1 addendum |
| **2 Terminal fidelity** | **Merged to origin/main** | Diagnose/fix existing capture, replay, PTY dimensions, Output/Terminal behavior (T01–T07) | Can investigate independently of 1; coordinate frontend edits |
| **3 Explorer** | **Merged into main at `54502666b5724596ee3d21c1e694b8522d5a5151`** | Group/filter/sort, tab state/overflow, safe metadata (N01–N08, D01–D05) | Prefer start after 1 and 2 integration |
| **4A Lifecycle** | **Merged to origin/main (Backend & Frontend)** | Secure stop/restart/pause-resume only where supported (C02–C07) | Phase 1 authorization pattern |
| **4B Enhanced logs** | **Merged to origin/main** | Search, navigation, conservative severity filters/count scopes (T08–T09) | Phase 2 representation contract |
| **5A Overview modes** | **Merged to origin/main at `a0028473`** | Global A/B/C/D selector and persistence (M01–M06) | Stable process header and tabs |
| **5B Live telemetry** | **Merged to origin/main at `9f01984d`** | Reuse audited `runmux.stats`/`resource_metrics`; provenance, unavailable states (M07–M09, M12–M13) | 5A useful but not mandatory |
| **5C Metric history** | Planned, separate approval for storage | Real bounded sampling, charts/ranges and optional detailed drawer (M10–M11) | 5B verified; retention/cost review |
| **6 Advanced workspace** | Candidates only | Inspector, stream panes where streams exist, history/events, presets and layout | Select one approved 6A–6D slice |

**Sequencing:** Phase 2 diagnosis can run in parallel with Phase 1 if the two agents don't independently rewrite `dashboard.js`, `dashboard.css`, or `index.html`. Worktrees prevent collision but not merge conflict. Phase 3 started from the integrated UI and is now merged to main. Phase 4A and 4B are **separate assignments**, as are Phase 5A/5B/5C. No agent should implement every item in Phases 4–6 just because it is documented.

## 5. Completion gate for every assignment

Each agent must report: exact inspected baseline and feature branch, confirmed existing contracts, implemented versus deferred backlog IDs, security/privacy impact, changed files, synthetic tests and outcomes, visually checked behavior as appropriate, explicit limitations/unsupported platforms, final pushed SHA, and whether merge was performed (**default: no**).

Do not claim process-level telemetry from host-level counters, total severity counts from a partial tail, or cross-platform support without verification. Missing data must be represented as unavailable, not zero.

## 6. Reference hierarchy

1. User's **current explicit assignment** (for Phase 1, the earlier Milestone 1 handoff).
2. `CURRENT_AGENT_PHASE_01_ADDENDUM.md` for Phase 1 reconciliation; otherwise the explicitly assigned phase/slice doc.
3. This master for global invariants and dependencies.
4. `Runmux Web UI — Gap Analysis & Feature Backlog` for IDs and roadmap rationale.
5. Minimal/full visual UX specifications and screenshots for appearance; speculative mockup elements are not automatically approved backend behavior.

When requirements conflict, preserve existing supported security/lifecycle behavior and ask the user about genuinely new policy decisions. Treat source code as authoritative for current implementation facts and tests as evidence of behavior.

## 7. Integrations tracker

Update upon actual merge; do not mark work complete merely because a branch exists.

| Package | Integration SHA | Verification | Notes |
|---|---|---|---|
| Phase 1 | `9f01984d` integration baseline | Verified earlier | Browser process launch is integrated on main |
| Phase 2 | `9f01984d` integration baseline | Focused evidence in Phase 2 status | Terminal/output correctness is integrated on main |
| Phase 3 | `54502666b5724596ee3d21c1e694b8522d5a5151` | Windows JS and headless browser checks pass; Python startup hangs | Integrated into main; full argv/cwd disclosure remains deferred |
| 4A / 4B | — | — | Separate implementation assignments |
| 5A / 5B / 5C | 5B: `9f01984d` | 5B backend integrated | 5A/5C remain unassigned |
| Phase 6C backend | — | `codex/runmux-historical-runs-backend-20261024` | Backend implementation verified on its feature branch; dedicated UI remains a separate assignment; not merged |
| Other Phase 6 slices | — | — | User-selected optional enhancements |
