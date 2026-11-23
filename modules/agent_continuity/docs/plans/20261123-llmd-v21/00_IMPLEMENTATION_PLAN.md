# LLMD v2.1 — Implementation Plan and Feature Register

**Status:** PROPOSED / awaiting implementation review. Documentation only; no source behavior is changed by this branch.  
**Owner module:** `modules/agent_continuity` in `MaxCarlson/scripts`.  
**Baseline:** `scripts/main` at `7b9f596ac1abebd5be8395962bfb8124379b082e`, verified 2026-11-23.  
**Companion files:** [Current CLI](01_CURRENT_CLI_REFERENCE.md) and [Proposed Changes / Evaluation Brief](02_PROPOSED_CHANGES_EVALUATION.md).

## 1. Objective and boundaries

Improve LLMD daily operation while keeping its durable GUI/slot/session model, recoverability, activation history, explicit approval before new model turns, existing CLI contracts, and Windows/WSL environment ownership rules. Consolidate requested usability changes into independently testable batches. **Do not implement unrelated orchestration, consume local LLM inference, delete history, publish packages, or merge without approval.**

A GUI alias refers to an existing ChatGPT GUI conversation; LLMD does not create a ChatGPT chat. An agent *slot* may retain several native Codex/AGY sessions over time. The selected session is the latest activation; lifecycle `active`/`inactive`/`completed` is separate from observed runtime state.

## 2. Complete feature backlog — LLMD-01 through LLMD-18

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

**Evidence for LLMD-18:** the named form currently calls `begin_launch` before registration and fails `Agent slot not found`. The positional form calls `dispatcher.register`. This is a verified inconsistency, not an inference about the user's environment.

## 3. Phases and dependencies

### Batch A — Session lifecycle and launch safeguards (P0 first)

**Scope:** LLMD-01, LLMD-15, LLMD-16, LLMD-18.  
**Files likely affected:** `dispatcher_cli.py`, `dispatcher.py`, `interactive.py`, focused `dispatcher_*` tests.

1. Define a **single canonical start-intent resolver** for positional and named forms, keyed by normalized GUI alias and slot identity, not by shell-string equality. The preview must show whether GUI/slot exist, which provider/session is selected, pending launch state, and the exact operation that `-a` would perform.
2. In both syntax forms, missing GUI/slot registration is a planned step; no registry/provider mutation on preview. Application registers missing records under durable existing lock/registration semantics **before** launching, but must be idempotent and reject conflicting registrations.
3. Require explicit `-N -a` for **new native conversations** in either form. If a selected session exists, offer **resume or new** interactively (a separate yes/no confirmation for new, with explicit resume authorization); in non-TTY mode a new conversation needs `-N -a`. Never silently overwrite selection, even if the request differs only by working directory or flag ordering.
4. For a different requested provider, show "switch provider", not "identical resume"; keep the same agent slot and preserve all activations. Provider switch post-exit option 4 offers reuse of prior opposite-provider session if safely available, otherwise asks permission for a new one. A successful new switch selects the new session only when its exact native ID is durably captured.
5. Integrate the post-exit menu with the switch operation without recursive wrapper launches, hidden duplicate prompts or forced new sessions. Existing nonzero-exit behavior and error propagation must remain safe.

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

**Unit/contract:** `dispatcher_v2_test.py`, `dispatcher_cli_test.py`, `dispatcher_ops_test.py`, `dispatcher_terminal_integration_test.py`, interactive selector tests, CLI parser/help tests, formatter snapshots. Add tests for auto-creation from named syntax, preview no writes, duplicate identical/different CWD/provider commands, legacy naming, both reactivation states, simultaneous starts, pending launch refusal and provider-switch transitions.

**Integration (disposable only):** temporary dispatcher registry, fake Codex/AGY provider executable/output, explicit pass/fail bootstrap, artificial session locks, subprocess normal and nonzero exits. No real accounts, no model turns.

**Reports:** command, observed exit status, short output, reviewed SHA, branch/worktree, changed paths, tests actually executed vs proposed, known limitations, and target next approval gate.

## 6. Change-management boundaries

Each implementation batch uses its own isolated worktree/feature branch, or a single sequential feature branch if one agent owns every modified file. No simultaneous writers to `dispatcher_cli.py` or `interactive.py`. Commit and push authorized feature changes for review, **do not merge**. Do not change other tools/modules without a demonstrated interface dependency. Do not start public publishing, background inference or local model loading.

The documentation in this branch is a **design proposal**; unresolved product decisions and requested evaluation criteria are explicitly listed in [02_PROPOSED_CHANGES_EVALUATION.md](02_PROPOSED_CHANGES_EVALUATION.md).
