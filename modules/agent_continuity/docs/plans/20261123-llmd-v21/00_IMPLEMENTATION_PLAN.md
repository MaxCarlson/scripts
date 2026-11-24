# LLMD v2.1 — Implementation Plan and Feature Register

**Status:** IN PROGRESS — sequential implementation authorized on `feature/llmd-v21-implementation-20261123`.
**Owner module:** `modules/agent_continuity` in `MaxCarlson/scripts`.
**Baseline:** `scripts/main` at `7b9f596ac1abebd5be8395962bfb8124379b082e`, verified 2026-11-23.
**Companion files:** [Current CLI](01_CURRENT_CLI_REFERENCE.md) and [Proposed Changes / Evaluation Brief](02_PROPOSED_CHANGES_EVALUATION.md).

## 1. Objective and boundaries

Improve LLMD daily operation while keeping its durable GUI/slot/session model, recoverability, activation history, explicit approval before new model turns, existing CLI contracts, and Windows/WSL environment ownership rules. Consolidate requested usability changes into independently testable batches. **Do not implement unrelated orchestration, consume local LLM inference, delete history, publish packages, or merge without approval.**

A GUI alias refers to an existing ChatGPT GUI conversation; LLMD does not create a ChatGPT chat. An agent *slot* may retain several native Codex/AGY sessions over time. The selected session is the latest activation; lifecycle `active`/`inactive`/`completed` is separate from observed runtime state.

## 2. Complete feature backlog — LLMD-01 through LLMD-21

| ID | Priority | Feature | Deliverable / acceptance |
|---|---|---|---|
| **LLMD-01** | P0 | Fourth post-exit choice — opposite provider | On Codex exit show `[4] Switch to AGY`; on AGY exit show `[4] Switch to Codex`. Same GUI/slot, history preserved, explicit new-vs-reuse decision; no duplicate launch |
| **LLMD-02** | P0 | Align interactive selector columns | Headers/values align for variable-length names, selector marker, ANSI styling, Unicode and terminal resizing |
| **LLMD-03** | P0 | Last-activity date and time in list | Show locally formatted date/time for GUI headings and each agent; unknown displays `—`, never invent timestamps |
| **LLMD-04** | P0 | Distinct provider colors | Codex cyan, AGY magenta/purple; neutral unknown; obey auto/always/never and `NO_COLOR` |
| **LLMD-05** | P0 | Status colors | Active green, inactive yellow/dim, completed neutral/dim; status remains readable without color |
| **LLMD-06** | P0 | GUI grouping separators | Blank line or subtle divider between groups; avoid misleading trailing separator |
| **LLMD-07** | P1 | Compact list layout | Width-aware table with no huge unused gap before lifecycle field; full IDs when space permits, deterministic ellipsis when not |
| **LLMD-08** | P1 | Runtime separate from lifecycle | On sufficiently wide output display `IN USE`, `NOT OBSERVED`, `PENDING`, `UNKNOWN` independently; avoid equating `active` with running |
| **LLMD-09** | P1 | Streamline public help | Show ordinary commands prominently, categorize advanced/recovery; hide internal `pane-run` cleanly; retain direct command help |
| **LLMD-10** | P1 | Review redundant registration surface | Positional/named `start` is preferred for new sessions; retain/deprecate `gui`, `slot`, `register` only after compatibility audit, not immediate removal |
| **LLMD-11** | P1 | Shared display utilities | One timestamp, ANSI-safe width/clip, provider/status styling, and session rendering implementation for list, selector and post-exit report |
| **LLMD-12** | P2 | Explicit unresolved/invalid session display | Treat pending IDs, missing IDs and literal placeholder-looking IDs as unresolved; never synthesize provider resume from a placeholder |
| **LLMD-13** | P2 | Responsive terminal display | Narrow/wide widths, wrapping/truncation policy, unicode, redirection, non-TTY and resize coverage |
| **LLMD-14** | P1 | `list -N N` activation-history expansion | Show up to N newest activation entries *under each local agent*, indented; fields are date/time then provider then native ID; selected ID marked; works for global/scoped and JSON when requested |
| **LLMD-15** | P0 | Duplicate-start protection | Existing selected session + attempted new `start` prompts interactively about new vs resume; non-TTY never launches accidentally; no automatic retry of pending bootstrap |
| **LLMD-16** | P0 | Consistent `start` authorization across syntax | Equivalent positional and `-g/-n` forms follow one validation/preview/`-N`/`-a` policy, including reactivation and existing-selection handling |
| **LLMD-17** | P1 | Post-exit scoped agent list | After lifecycle choice or completed/canceled provider switch, render `llmd list -g <current GUI>` with fresh state, including completed target slot; do not double-print |
| **LLMD-18** | P0 | Automatic GUI/slot registration for all `start` forms | `llmd start -g GUI -n AGENT` previews missing alias/slot and `-N -a` registers them and launches, just like positional `start GUI AGENT` |
| **LLMD-19** | P0 | Reviewer handoff and return | Persistent review cycles link an original slot to a distinct reviewer slot; `review` resumes or explicitly starts the reviewer, and `return` deactivates it and reactivates/resumes the exact original session without duplicating native sessions or slots |
| **LLMD-20** | P0 | Exit-menu switch to an existing local agent | Option 5 opens a searchable picker of inactive agents under the current GUI, prioritizes the linked original when present, validates its exact existing session, then atomically deactivates the departing slot and activates/resumes the destination; it never creates a native session |
| **LLMD-21** | P0 | Exit-menu create and switch to a new agent | Option 6 collects a new slot name, Codex/AGY provider, and confirmed working directory; after explicit confirmation it creates the slot, initializes one provider session, durably selects its exact captured ID, then deactivates the departing slot |

**Evidence for LLMD-18:** the named form currently calls `begin_launch` before registration and fails `Agent slot not found`. The positional form calls `dispatcher.register`. This is a verified inconsistency, not an inference about the user's environment.

## 3. Phases and dependencies

### Batch A — Session lifecycle and launch safeguards (P0 first)

**Scope:** LLMD-01, LLMD-15, LLMD-16, LLMD-18.
**Files likely affected:** `dispatcher_cli.py`, `dispatcher.py`, `interactive.py`, focused `dispatcher_*` tests.

1. Define a **single canonical start-intent resolver** for positional and named forms, keyed by normalized GUI alias and slot identity, not by shell-string equality. The preview must show whether GUI/slot exist, which provider/session is selected, pending launch state, and the exact operation that `-a` would perform.
2. In both syntax forms, missing GUI/slot registration is a planned step; no registry/provider mutation on preview. Application registers missing records under durable existing lock/registration semantics **before** launching, but must be idempotent and reject conflicting registrations.
3. Require explicit `-N -a` for **new native conversations** in either form. If a selected session exists, offer **resume or new** interactively (a separate yes/no confirmation for new, with explicit resume authorization); in non-TTY mode a new conversation needs `-N -a`. Never silently overwrite selection, even if the request differs only by working directory or flag ordering.
4. For a different requested provider, show "switch provider", not "identical resume"; keep the same agent slot and preserve all activations. Provider switch post-exit option 4 offers reuse of prior opposite-provider session if safely available, otherwise asks permission for a new one. A successful new switch selects the new session only when its exact native ID is durably captured.
5. Option 4 remains same-slot provider switching. Options 5 and 6 are reserved for cross-slot switching and new-slot creation respectively; all nested provider transitions show one settled result without recursive menu output. Existing nonzero-exit behavior and error propagation must remain safe.

**Acceptance:** both syntax forms preview and create a new slot correctly; duplicate start prompts/resumes safely; cancel/no does not launch; switch Codex→AGY and AGY→Codex retain slot identity/history; nonzero exit, pending/captured bootstrap, in-use sessions and concurrent starts preserve state and never double-bill by auto-retry.

### Batch B — Human-readable rendering and history

**Scope:** LLMD-02–08, LLMD-11, LLMD-14, LLMD-17, plus relevant LLMD-12/13 display cases.
**Files likely affected:** `dispatcher_cli.py`, `interactive.py`, shared rendering helper, rendering/UI tests.

1. Build an isolated, testable row formatter: terminal-width aware, ANSI printable-width safe, stable column definitions, consistent dates, colors, indentation, clipping, non-color fallback.
2. Add per-GUI **and** per-agent "Last Activity" timestamps, and a separating line/blank line between GUI groups. Display current session ID if known, lifecycle label, and when space allows independently computed runtime label.
3. Add `llmd list -N/--history-count N` (`N≥0`; default 0). For every displayed agent, fetch up to N latest **activation records**, newest first. Render each as an indented child row with **date/time | provider | full ID if it fits**. Display a selected-session marker, note repeated activations of the same ID are possible. A missing/invalid ID must be labeled unresolved rather than rendered as a real native ID.
4. JSON output keeps the current no-`-N` schema unchanged; only requested history adds a defined optional per-agent array. A scoped list's `-l` limits agents, not expanded history entries. Test `-A`/completed consistency in global and scoped views.
5. Print the current GUI summary once after the post-exit choice has fully resolved; if option 4 launches a provider, report after that nested operation finishes/cancels/fails. Include the just-completed slot in the post-exit view even when default `list` would hide it.

**Acceptance:** golden snapshots for 40/80/120/200-column output, ANSI on/off, `NO_COLOR`, long names, multibyte symbols, empty GUI, missing timestamps, active/inactive/completed, pending vs in-use, history 0/1/3, repeated activations, per-GUI separators, non-TTY, JSON schema, one and only one post-exit list.

### Batch C — Surface cleanup and migration (after A/B)

**Scope:** LLMD-09, LLMD-10, remaining LLMD-12/13.
**Files likely affected:** parser/help, README, shell completion/launcher/docs/tests as relevant.

1. Keep `start`, `continue`, `switch`, `list`, `open`, `history` discoverable as primary user actions. Keep `gui`, `slot`, `attach`, `pending`, `recover`, `doctor` accessible as admin/recovery. Consider `register` a *candidate* for deprecation only after searching real callers.
2. Fix internal `pane-run` display (`==SUPPRESS==` in help), without breaking launcher invocation. Ensure command help documents `-N` on `start` separately from `-N N` on `list`.
3. Standardize **documented** preview/apply behavior. Changing existing `register` apply-by-default semantics requires a compatibility/deprecation decision and tests; do not silently break scripts.
4. Preserve scripting-facing machine output, error codes, Windows PowerShell 7, WSL and Linux environments, and original short+long flag pairings where applicable.

**Acceptance:** parser/help snapshots, original forms still work, launcher-internal `pane-run` still callable, help hides it; existing `register` clients have an explicit migration path.

### Batch D — Reviewer handoff and return

**Scope:** LLMD-19 plus the context-aware post-exit action from LLMD-01. This batch follows A–C because it reuses canonical start intent, runtime locks, rendering, and lifecycle reporting.

**CLI contract (all mutations preview by default):**

```powershell
# Preview/resume the current reviewer session under a stable reviewer slot.
llmd review -g ORIGINAL_GUI -n ORIGINAL_AGENT -R REVIEWER_AGENT -p codex -C REVIEWER_WORKTREE
llmd review -g ORIGINAL_GUI -n ORIGINAL_AGENT -R REVIEWER_AGENT -p codex -C REVIEWER_WORKTREE -a

# Explicitly create a new reviewer conversation. -N alone is a preview;
# only -N -a authorizes its native provider bootstrap.
llmd review -g ORIGINAL_GUI -n ORIGINAL_AGENT -R REVIEWER_AGENT -p codex -C REVIEWER_WORKTREE -N -a

# Return from the reviewer currently linked to that original slot.
llmd return -g ORIGINAL_GUI -n ORIGINAL_AGENT -a
```

`-R/--reviewer-agent` names a distinct slot under the same GUI alias. Its worktree is controlled by `-C/--cwd`; the original slot keeps its own captured session cwd. A reviewer slot is created only when absent, under the existing registry mutation lock, and is reused on later cycles. If cross-GUI reviewer slots are needed, both ends must be named explicitly in a later compatible extension; this first contract intentionally uses one GUI alias so slot identity is unambiguous.

**State-transition rules:**

1. A review cycle has a stable cycle ID, original slot ID, reviewer slot ID, the original selected `(provider, environment_id, native_session_id)` tuple, source lifecycle states, and one of `pending`, `active`, `returned`, `cancelled`, or `failed`. Durable events are the source of truth; the query projection is rebuildable.
2. `review` first validates both slots, current heads, pending launches, runtime leases, and any open cycle while holding the registry mutation lock. It refuses a second open cycle for either slot, a reviewer slot linked to another active original, a shared native session assigned to both roles, or a slot/session in use. It does not alter the original lifecycle or selection during preview or before a new reviewer bootstrap has captured and persisted one exact ID.
3. If the reviewer slot has a current selected session, `review -a` resumes that exact session and creates or reuses the relationship; a requested provider mismatch is an error that requires `-N -a`. If the reviewer slot has no selected session, only `-N -a` may bootstrap a new native conversation. Historical IDs are never guessed and ambiguous/pending bootstrap attempts are never retried automatically.
4. On successful resume or exact-ID bootstrap, one locked transition rechecks both observed heads and writes the review-cycle activation plus lifecycle changes: original becomes `inactive`, reviewer becomes `active`, and the cycle becomes `active`. A stale confirmation, canceled bootstrap, failed process spawn, or ambiguous/captured-but-unpersisted launch leaves the prior original selection and lifecycle intact; unresolved launch recovery stays with the existing `pending`/`doctor`/`recover`/`attach` safeguards.
5. `return -a` resolves exactly one active cycle for the named original slot. Under the same registry lock it revalidates the reviewer and original heads and locks, appends the cycle-return event, sets reviewer `inactive`, sets the original to its saved pre-review lifecycle unless that state was `completed` (completed stays completed), and selects the recorded original session only if it remains the exact current session. It never creates a native conversation. If the original session is missing or its exact identity changed, return fails without mutating either slot and directs the user to `continue`/`attach` explicitly.
6. The post-exit menu preserves `[4] Switch provider` for the same slot. `[5] Switch to an existing agent` opens the inactive-agent picker; when the current slot is a reviewer, the linked original is prioritized and selecting it performs the linked return transition. `llmd return` remains the direct return command. `[6] Create a new agent` is the separately confirmed new-slot flow. Return after reviewer exit runs only after the reviewer process lock is released. On canceled/failed transitions, the current slot and active review context remain unchanged.
7. Only one transition per cycle can commit. Concurrent `review`/`return` requests serialize on the registry lock and revalidate cycle state; one succeeds, stale contenders get a recoverable conflict. Native session IDs and every prior activation remain in history; repeated activation of the same exact session is not duplicated unless the provider was actually resumed and existing activation semantics record it.

**Acceptance:** Codex↔AGY reviewer/original round trips; same-provider resume; new reviewer session with `-N -a`; no new session without both flags; same and different worktrees; interrupted, canceled, failed, and captured-but-unpersisted bootstrap; reviewer/original slot reuse; missing/changed original head; abnormal exits; in-use locks; duplicate and concurrent transitions; no duplicate slot/native session; and context-aware menu behavior. All provider execution uses disposable registries and fake processes.

### Batch E — Intra-GUI agent switching and new-agent creation

**Scope:** LLMD-20 and LLMD-21. Exit option 4 remains the existing same-slot provider switch; option 5 and option 6 are distinct cross-slot workflows.

**Option 5 — resume an existing inactive agent:**

1. Build picker candidates from inactive, noncompleted slots under the current GUI only. Require one current exact activation/session and no unresolved pending launch. Exclude the departing slot. If the departing slot is a reviewer in an active cycle, put its linked original first while keeping all eligible agents searchable.
2. Selecting a candidate does not mutate state immediately. Under the registry mutation lock, re-read source and destination slots, verify both expected heads/states, verify the destination exact native session exists and is not in use, confirm the GUI is unchanged, and confirm no native session is shared by the two slots.
3. In one durable transition, mark the departing slot `inactive`, mark the destination `active`, and record any necessary activation/link return event. Only then launch the destination's existing provider/session through its exact recorded environment and cwd. Cancellation or any validation/lock failure leaves both slots and all histories unchanged. A selected existing session is never replaced by a newly created session through option 5.

**Option 6 — create a new local agent:**

```text
New agent name: <required>
Provider: Codex | AGY
Working directory: <entered path or explicitly confirmed current directory>
Preview: create slot under <current GUI>, initialize one new <provider> session in <cwd>
Start this new conversation? [y/N]
```

The affirmative confirmation is the interactive equivalent of explicit `-N -a`; preview, blank input, and cancellation create neither a slot nor a native session. Use the canonical launch preparation path and existing exact-ID bootstrap. On successful capture/persistence, one guarded transition activates the new slot, deactivates the departing slot, and records the selection. On failure, cancellation, timeout, or ambiguous capture, leave the departing slot active and retain the pending launch for existing recovery; never retry automatically. Work-directory input must be validated as an existing directory and shown back to the user before confirmation.

**Acceptance:** option 5 picker search/order/filtering; linked-original prioritization; same-GUI restriction; empty/missing/pending/completed destination rejection; exact existing Codex and AGY sessions; destination in-use and stale-head failures without source mutation; concurrency with `continue`/`review`/`return`; no new launch; option 6 duplicate/blank names, provider selection, invalid/unconfirmed cwd, cancellation, authorization, disposable fake bootstrap, exact native-ID selection, prior-history preservation, and interrupted/ambiguous launch recovery. Every case uses a disposable registry and fake provider process.

## 4. Non-negotiable invariants

- No destructive operations, deleting sessions, registry reset, loss of history or in-place worktree changes.
- No local LLM inference as part of testing. Fake provider bootstrap/output and subprocesses in tests; do not launch real Codex/AGY to exercise tests unless separately authorized.
- No new native session from a canceled prompt, noninteractive implicit legacy `start`, or unresolved/pending attempt.
- Do not equate `active` with `IN USE`. Same-runtime locks do not prove cross-OS process state.
- Keep exact provider session IDs and environment ownership; never construct guessed IDs or parse placeholder strings as verified native sessions.
- New `-N` list flag is command-scoped and must not change existing `start -N/--new`.
- Respect `NO_COLOR`, non-TTY, readable plain-text output, and existing JSON contracts.
- Preserve all original flags/API behavior absent an explicitly documented migration decision.

## 5. Test strategy and evidence requirements

**Unit/contract:** `dispatcher_v2_test.py`, `dispatcher_cli_test.py`, `dispatcher_ops_test.py`, `dispatcher_terminal_integration_test.py`, interactive selector tests, CLI parser/help tests, formatter snapshots. Add tests for auto-creation from named syntax, preview no writes, duplicate identical/different CWD/provider commands, legacy naming, both reactivation states, simultaneous starts, pending launch refusal and provider-switch transitions. For LLMD-19–21, cover the transition tables above with real event/materializer state and deterministic fake provider processes.

**Integration (disposable only):** temporary dispatcher registry, fake Codex/AGY provider executable/output, explicit pass/fail bootstrap, artificial session locks, subprocess normal and nonzero exits. No real accounts, no model turns.

**Reports:** command, observed exit status, short output, reviewed SHA, branch/worktree, changed paths, tests actually executed vs proposed, known limitations, and target next approval gate.

## 6.1 Independent Gemini review reconciliation from the implementation handoff

The implementation handoff carries the following reviewer constraints into the plan: review relationships persist across cycles; transitions are atomic and concurrency-safe; original and reviewer slots do not duplicate native sessions or registrations; exact session IDs and recovery safeguards remain authoritative; provider changes and distinct worktrees are supported; and post-exit actions must preserve option 4 while option 5 prioritizes a linked original in the general agent picker. These constraints are incorporated into LLMD-19–21's syntax, state model, transition rules, and acceptance matrix above. The portable evaluation brief in `02_PROPOSED_CHANGES_EVALUATION.md` did not contain a returned Gemini verdict or findings list, so no additional finding is attributed to that document.

## 7. Change-management boundaries

Each implementation batch uses its own isolated worktree/feature branch, or a single sequential feature branch if one agent owns every modified file. No simultaneous writers to `dispatcher_cli.py` or `interactive.py`. Commit and push authorized feature changes for review, **do not merge**. Do not change other tools/modules without a demonstrated interface dependency. Do not start public publishing, background inference or local model loading.

The v2.1 documentation began as a design proposal. This implementation handoff authorizes the sequential A–E implementation described here; compatibility changes outside that scope still require an approval gate. Remaining evaluation criteria are listed in [02_PROPOSED_CHANGES_EVALUATION.md](02_PROPOSED_CHANGES_EVALUATION.md).
