## Current feature batch — LLMD-25 / LLMD-48 / LLMD-49 (v2.3.0 candidate)

**Status:** Implementation, release documentation, focused validation, Claude/review tests, help-registry compatibility, and disposable install qualification are complete on `feature/llmd-25-48-49-20261127` at pushed commit `78d9674de7d3edd7a2a0ffc9a7acb689c103ffac`. The comprehensive module run had 8 failures; every failed case passed in a subsequent focused rerun, and the suite was not repeated per instruction. Final Ruff, diff, and version checks pass. The candidate awaits independent GUI review; no main merge has occurred.

**Release boundaries for review:** LLMD-25 is independently releasable as v2.2.0. LLMD-48 and LLMD-49 form v2.3.0 because workflow metadata and stable numbering must ship together as checkpoint-ready identity metadata. Both are additive to the standalone v2.1.1 provider release; no runtime-discovery, terminal-lifecycle, or checkpoint-owned implementation files are changed here.

**Implementation choices:** Store definitions and assignments in immutable dispatcher events and rebuildable SQLite projections, matching the existing registry's durability model. Profile files were considered but rejected because they split atomic updates and projection recovery from the dispatcher event stream. Allocate numbers from the per-GUI reservation high-water mark while holding the existing dispatcher mutation lock, and persist the assigned number in the slot-created event; computed display ordinals were rejected because renames, late events, and transfer would make them unstable.

**LLMD-25 profile contract:** Profiles have immutable `profile_id`, case-insensitive unique name, provider, optional supported `runtime_kind`, optional default working directory, a monotonically increasing revision, and normalized managed settings only. Settings are constrained to provider-supported, non-secret fields (sandbox/approval or permission mode, model, reasoning effort, provider profile, additional directories, and supported feature/search toggles). Never persist prompts, credentials, raw `--config`/`--settings` strings, unknown argv, `--allow-native-unknown`, new-conversation/reactivation authorization, or permission-bypass controls. A retired profile remains in event history and is unusable; a slot assigned to a retired or incompatible profile fails closed until explicitly reassigned or explicitly bypassed for that invocation.

Use `llmd profile list|show|create|update|retire|assign|clear`. Management operations execute by default and accept `-d/--dry-run`; `-a/--apply` remains compatible. Launch commands accept `--profile NAME` to select an invocation-scoped profile and `--no-profile` to bypass the slot assignment for that invocation; without either, use the slot's assigned profile. Reject both together. Resolve settings as invocation > selected profile > provider/runtime defaults. A single invocation value replaces the profile value for the same normalized field; repeatable fields are replaced as a collection. Report each resolved field's provenance in text/JSON preview. Revalidate provider, runtime, and every profile path for each launch; never fall back silently when validation fails. Profile application does not bypass existing new-session, reactivation, permission, identity, executable, or unknown-native-option gates and never replays authorization that the operator has not supplied for the current invocation.

**LLMD-48 workflow contract:** Add nullable `workflow_type` to a slot, with allowed explicit values `standard`, `handoff`, and `goal`. `NULL` means legacy/untyped and preserves the exact current behavior. Add `llmd workflow-type GUI AGENT TYPE` (and `-d/--dry-run`, compatible `-a/--apply`) to change it explicitly. The field is descriptive metadata only in this release; it does not change provider, permissions, installer mode, handoff mode, delegation, or native goal state. Every change is an immutable event; no implicit default migration converts legacy slots.

**LLMD-49 identity contract:** `gui_id` and `slot_id` are immutable keys; aliases and names are display labels only. Add positive `agent_number` per current GUI membership. New slots allocate `MAX(reserved number for gui_id)+1` under the dispatcher lock and store it in the same `dispatcher.slot_created` event and materialized transaction. Dry-run previews may show a provisional candidate but never reserve it. A rebuild replays explicit numbers; historic creation events without a number receive deterministic monotonically increasing reservations in event-ingest order, preserving any event-provided assignment and never reusing a number. Keep reservations after slot removal or future transfer; a transferred slot receives a new destination-GUI number while its source reservation remains permanently reserved. If independently verified external legacy numbers are supplied, only import them through an explicit reconciliation action that records the source and rejects collisions; never infer them from aliases, list position, or session IDs. Return `agent_number` from registration/create APIs and include it in text, status, and JSON listing without changing existing JSON schema version or removing fields.

**Checkpoint interface for Agent #3:** Checkpoints should key an agent reference by immutable `slot_id`, record the immutable `gui_id` and the observed membership/`agent_number` as snapshot provenance, and store `workflow_type` plus `profile_id`/revision (and a digest of normalized profile settings) as optional metadata. Display aliases/names are labels, not identity. LLMD owns these dispatcher fields; Agent #3 owns checkpoint storage and terminal/runtime files. A checkpoint consumer must tolerate `workflow_type=null`, absent profile references, and slots whose present GUI membership later changes. This contract does not itself claim that a session or terminal is open.

**Acceptance:** Use disposable registries and fake providers. Cover schema-v3 upgrade and v4 rebuild compatibility; profile create/update/retire/assign/clear, precedence and provenance; provider/runtime mismatch and stale profile paths before any mutation; no secret/raw configuration persistence; explicit authorization revocation; dry-run purity; legacy slots; workflow-type orthogonality and JSON; concurrent slot creation with globally unique per-GUI numbers; event replay/rebuild; gaps and permanent reservations; registration/list/status JSON; and profile/workflow metadata references usable by a future checkpoint without touching Agent #3-owned files.

---

# LLMD v2.1 — Implementation Plan and Feature Register

## LLMD-56 — Claude Code provider release (v2.1.1 corrective candidate)

**Status:** Offline implementation and validation completed on `feature/llmd-56-claude-provider-20261127`; the v2.1.1 candidate was accepted and merged to main through PR #46 at baseline `7b28b81cad915982ab38961c7538ca1c2ff5f032`. Profiles, workflow types, and numbering were deferred at that release and are implemented in the current v2.3.0 candidate; hooks and checkpoint features remain deferred.

**CLI contract:** `claude` is a canonical provider accepted by dispatcher registration, attach, start, continue, switch, review, return, listing/history, recovery, open/pane resume, provider selectors, and semantic output. Exact resume requires a valid UUID and uses `claude --resume <UUID>`; never use `--continue` because it means the provider's most recent conversation. First-session start allocates one UUID only after the LLMD pending launch is committed, then invokes the provider interactively as `claude --session-id UUID [managed-or-authorized-native-argv]`. No prompt, print, cloud, background, desktop, worktree, teleport, remote-control, fork, settings-file, alternate identity, or permissions-bypass option is accepted through native forwarding. The safe managed surface is `--model`, `--effort`, `--permission-mode`, `--add-dir`, and `--agent`; common safe unknown options still require `--allow-native-unknown` and are previewed, but that authorization cannot override reserved identity/execution/permission controls. Registry list/history works; broad transcript-wide native history discovery remains unsupported until its internal schema is qualified.

**Identity state rules:** UUID reservation is not native session creation. One UUID reservation and one durable one-shot spawn claim are committed per pending Claude launch. Repeated or concurrent execution of a claimed launch cannot allocate another UUID or spawn again. The exact reservation, claim, and process outcome survive interruption and reconstruction. LLMD associates the session only after a clean provider exit and a unique, nonempty, strict-UTF-8 JSONL transcript with object records and no contradictory root session identity. Malformed, unreadable, contradictory, or duplicate transcript evidence is unavailable and raises a metadata error; `None` means the exact transcript store was scanned successfully and no candidate was present at that time. Neither result establishes native resumability. A clean exit with confirmed transcript absence remains unresolved and pending so later exact-ID recovery can use the same UUID; failed/interrupted starts retain their candidate and are never automatically retried. Explicit `recover` may resolve a pending Claude candidate only after rechecking the unique exact transcript under registry/session locks. Otherwise an operator must verify provider state and explicitly attach. Previews allocate no UUID and launch no provider.

**Transition rules:** All provider changes preserve the destination's exact session and environment/cwd. New Claude sessions follow the direct pending/UUID path. Existing Claude sessions resume exactly. Reviewer launch associates and activates the reviewer only after transcript evidence, then atomically completes the review-cycle transition; failed creation leaves the original selected identity/lifecycle unchanged and the cycle recoverable. Return resumes the original provider/session ID unchanged. Windows is the qualified launch target; a nonempty local transcript lookup is unavailable for WSL-owned Claude stores, so such new launches must remain unresolved or be explicitly attached after operator verification. Authentication remains Claude-managed. Hook installation/activation is not included.

**Provider evidence and acceptance:** Installed Claude Code v2.1.332 help/version was inspected without inference; official references are [CLI reference](https://code.claude.com/docs/en/cli-reference), [session management](https://code.claude.com/docs/en/sessions), and [hooks](https://code.claude.com/docs/en/hooks). The CLI reference specifies UUID `--session-id`, exact `--resume`, and warns that `--continue` selects the current directory's most recent session. The session page documents continuously written JSONL transcripts at `~/.claude/projects/.../<session-id>.jsonl`, while noting transcript record layout is internal. LLMD validates strict decoding, JSONL object records, contradictory root identity, and unique exact-path evidence but never infers live resumability. Tests use disposable registries, fixture transcripts, and fake providers; no Claude/Codex/AGY inference is authorized. Validate provider discovery/missing executable, first start and failed/interrupted starts, exact resume/attach/recover, duplicate/concurrent start protection, all three-provider switching, review/return, JSON/rebuild/history, Windows paths and argument protection, plus full Codex/AGY compatibility. Do not merge before independent GUI review.

## LLMD-46/47 final action and startup-reporting corrections (v2.0.0)

### LLMD-47 — action-default CLI contract

Operational commands (`start`, `continue`, `switch`, `open`, `review`, `return`, `attach`, GUI/slot creation, and ordinary slot lifecycle changes) execute by default. `start GUI AGENT -p PROVIDER` resumes its selected exact session, or creates missing local records and reserves the first provider session when no selected session exists. `start ... -N/--new` explicitly requests a replacement native conversation and keeps prior activations in history. `continue` only resumes an exact existing identity and never creates one. `review` follows the same create-or-resume rule for its distinct reviewer slot. `switch ... -p PROVIDER` performs the explicitly requested provider change; `switch -r/--reuse-previous` remains the explicit way to select an existing historical provider session. Conflicting, pending, inaccessible, or ambiguous state is an error, never an empty slot.

Operational commands accept `-d/--dry-run` for a side-effect-free preview; legacy `-a/--apply` remains an accepted execution alias, and supplying both flags is an error. Neither flag nor `-N` is required for ordinary first-session creation. `-N -a` remains valid and compatible. Read-only `list`, `history`, `last`, `recent`, `doctor`, and `pending` stay read-only. `last -r/--resume` explicitly resumes the exact terminal-scoped session; `last -a` remains a compatibility alias for resume. Recovery and destructive operations retain their existing explicit safeguards.

`-N` is affirmative new-conversation intent, not an apply gate. For an existing selected session, interactive `start -N` retains the confirmation that protects the prior association; canceled prompts do not reserve a launch. Noninteractive `start -N` is explicit intent supplied on the command line. `start` on an empty slot is itself the affirmative initialization command. `review` on an empty reviewer slot initializes that reviewer; `review -N` replaces the reviewer's selected identity subject to the existing review-cycle transaction. Inactive-slot reactivation, historical identity selection, generic native-option authorization, ambiguous-target confirmation, and destructive-operation confirmations remain unchanged. Provider argv following `--` stays opaque to argparse and is never shell-string executed. The separate legacy `agents` CLI is outside this change.

Implementation audit includes all in-repository invocation sites, tests, examples, docs, help text, JSON behavior, and interactive flows that previously depended on implicit previews. Preview-dependent callers must opt into `-d`; external repositories are reported for coordinated migration.

### LLMD-46 — startup stage timings

Instrument dispatcher startup and launch with monotonic durations for registry synchronization, environment/executable discovery, Git context, launch reservation, fixed bootstrap, exact session capture/persistence, and interactive provider handoff. Emit a flushed first progress line promptly and periodic elapsed-time progress only during blocking initialization/bootstrap, at approximately 3–5 second intervals, and stop periodic reporting before the interactive provider process begins. Progress is human-readable stderr only (never JSON stdout); redact provider arguments and secrets. Measure dispatcher-only overhead separately from provider/bootstrap runtime. Optimize measured redundant synchronization and process discovery; subsecond dispatcher-only work and first progress near 250 ms are targets, not assertions absent controlled evidence. Actual provider startup acceleration remains unverified.

Inspect installed Codex/AGY help, available local documentation and source, and fake-provider behavior for a reliable exact-session creation/capture interface that avoids a separate bootstrap turn. Do not infer from newest-session files or replace the current fixed read-only bootstrap unless the exact-ID protocol is documented and demonstrated safely.

### Deferred LLMD-39 responsive refinement

Allocate column widths from each rendered group's actual values, terminal-cell widths, and available width. Preserve complete native UUIDs whenever they fit; use a stacked row before needlessly clipping timestamps or IDs. Cover long and short agent names, 36-character UUIDs, Unicode/combining characters, empty groups, narrow widths, and wide layouts. JSON and semantic ANSI behavior remain unchanged.

### Acceptance and delivery

Cover default first-session creation, existing-session resume, explicit replacement, reviewer initialization, provider switching, legacy flags, `-d` purity, contradictory flags, `last -r`/`last -a`, concurrent first starts, unresolved pending launches, interrupted bootstrap recovery, exact session reuse, human/JSON progress routing, secret redaction, and heartbeat termination before interactive handoff. Use fake providers and disposable registries exclusively. Bump package, module, and help-registry metadata consistently to 2.0.0. Validate module and relevant compatibility suites, Ruff, installation/CLI smoke, version consistency, and diff checks. This batch requires independent GUI review before integration.

**Status:** Historical LLMD v2.1 register; active v2.0.0 corrections are tracked in the section above and `STATUS.md` on `feature/llmd-46-47-action-defaults-latency-20261127`.
**Owner module:** `modules/agent_continuity` in `MaxCarlson/scripts`.
**Baseline:** `scripts/main` at `7b9f596ac1abebd5be8395962bfb8124379b082e`, verified 2026-11-23.
**Companion files:** [Current CLI](01_CURRENT_CLI_REFERENCE.md) and [Proposed Changes / Evaluation Brief](02_PROPOSED_CHANGES_EVALUATION.md).

## 1. Objective and boundaries

Improve LLMD daily operation while keeping its durable GUI/slot/session model, recoverability, activation history, explicit approval before new model turns, existing CLI contracts, and Windows/WSL environment ownership rules. Consolidate requested usability changes into independently testable batches. **Do not implement unrelated orchestration, consume local LLM inference, delete history, publish packages, or merge without approval.**

A GUI alias refers to an existing ChatGPT GUI conversation; LLMD does not create a ChatGPT chat. An agent *slot* may retain several native Codex/AGY sessions over time. The selected session is the latest activation; lifecycle `active`/`inactive`/`completed` is separate from observed runtime state.

## 2. Complete feature backlog — LLMD-01 through LLMD-24, LLMD-39, LLMD-46 and LLMD-47

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
| **LLMD-22** | P0 | Provider-native argv passthrough | `start`, `continue`, `switch`, `review`, and `return` accept structured tokens only after `--`; exact session identity and LLMD-owned bootstrap/directory/session flags remain protected. Unsupported `open` passthrough is rejected explicitly |
| **LLMD-23** | P0 | Invocation-scoped working directory | `-C/--cwd` applies to supported resume paths, validates local or recorded-WSL runtime directories, flags detected repository/worktree context changes, and never rewrites existing native-session cwd provenance |
| **LLMD-24** | P0 | Launch preview and permission diagnostics | Before provider execution, show resolved executable/argv, cwd, recorded runtime/environment, exact session (or captured-ID placeholder), and requested permission flags. Effective permissions are always marked unverified |
| **LLMD-39** | P0 | Semantic terminal presentation | Central semantic palette, ANSI-safe aligned/stacked output across LLMD human views, clear lifecycle/runtime/outcome distinctions, no-color and JSON compatibility, Windows/Unicode terminal coverage |
| **LLMD-46** | P0 | Startup latency instrumentation and optimization | Monotonic stage timings, immediate/periodic flushed progress, redacted stderr diagnostics, measured dispatcher-only overhead, and a safe exact-session bootstrap alternative assessment |
| **LLMD-47** | P0 | Action-default CLI | Operational LLMD commands execute by default with explicit `-d` preview and compatible `-a`; read-only commands stay read-only; preserve explicit new-session, reactivation, and destructive safeguards |

## v1.5.2 correctness follow-up

- Resolve one concrete environment for preview and launch reservation. When a new provider session follows a Windows or WSL session, omitted `-e` retains the selected session environment; an explicit selector resolves to the same stored environment ID.
- Keep `-C` and native argv scoped to their invoking session across post-exit options 4–6. Prompt before applying compatible overrides to a destination, present destination defaults for incompatible options, and allow cancellation before any registry transition.
- Validate picker cwd before reactivation. Apply historical `continue` and `switch -r` selections with expected-current compare-and-swap; `switch -r` requires `-R` for inactive slots and rejects completed slots.
- Keep `start -j` previews to a single JSON document for both selected-session and new-session paths.
- Acceptance covers environment preview/pending parity, post-exit options and worktrees, override prompts/cancel/failure, inactive/completed lifecycle, stale activation, failed resumes, and JSON/text output.

**Deferred:** LLMD-25 (persistent launch profiles) and LLMD-26 (native lock diagnostics) are out of scope for v2.1 because they add persistent policy/locking semantics beyond invocation-scoped argv and existing LLMD runtime locks.

**Evidence for LLMD-18:** the named form currently calls `begin_launch` before registration and fails `Agent slot not found`. The positional form calls `dispatcher.register`. This is a verified inconsistency, not an inference about the user's environment.

## 3. Phases and dependencies

### Batch A — Session lifecycle and launch safeguards (P0 first)

**Scope:** LLMD-01, LLMD-15, LLMD-16, LLMD-18.
**Files likely affected:** `dispatcher_cli.py`, `dispatcher.py`, `interactive.py`, focused `dispatcher_*` tests.

1. Define a **single canonical start-intent resolver** for positional and named forms, keyed by normalized GUI alias and slot identity, not by shell-string equality. The preview must show whether GUI/slot exist, which provider/session is selected, pending launch state, and the exact operation that `-a` would perform.
2. In both syntax forms, missing GUI/slot registration is a planned step; no registry/provider mutation on preview. Application registers missing records under durable existing lock/registration semantics **before** launching, but must be idempotent and reject conflicting registrations.
3. Require explicit `-N -a` for **new native conversations** in either form. If a selected session exists, offer **resume or new** interactively (a separate yes/no confirmation for new, with explicit resume authorization); in non-TTY mode a new conversation needs `-N -a`. Never silently overwrite selection, even if the request differs only by working directory or flag ordering.
4. For a different requested provider, show "switch provider", not "identical resume"; keep the same agent slot and preserve all activations. Provider switch post-exit option 4 offers reuse of prior opposite-provider session if safely available, otherwise asks permission for a new one. A successful new switch selects the new session only when its exact native ID is durably captured.
5. Option 4 captures the departing exact activation before prompting and revalidates it under the registry lock before either reusing a session or reserving a new launch. New sessions inherit the departing session's recorded environment and native cwd; reused sessions resume from their own recorded environment and cwd. Unsupported or incompatible runtimes fail before selection or launch state changes. Canceling option 4 returns to the post-exit menu without changing state or printing a duplicate summary.
6. Option 4 remains same-slot provider switching. Options 5 and 6 are reserved for cross-slot switching and new-slot creation respectively; all nested provider transitions show one settled result without recursive menu output. Existing nonzero-exit behavior and error propagation must remain safe.

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
2. `review` accepts an original in `active` or `inactive` lifecycle only when it has an exact selected session; `completed` or sessionless originals are rejected. It validates both slots, current heads, pending launches, runtime leases, and any open cycle while holding the registry mutation lock. It refuses a second open cycle for either slot, a reviewer slot linked to another active original, a shared native session assigned to both roles, or a slot/session in use. It does not alter the original lifecycle or selection during preview or before a new reviewer bootstrap has captured and persisted one exact ID. An already-inactive original remains inactive throughout review.
3. If the reviewer slot has a current selected session, `review` resumes that exact session and creates or reuses the relationship; a requested provider mismatch is an error that requires explicit `-N` replacement intent. If the reviewer slot has no selected session, `review` initializes the reviewer by default. `review -N` replaces the selected reviewer identity; the prior session remains in activation history. `-N -a` remains compatible. Historical IDs are never guessed and ambiguous/pending bootstrap attempts are never retried automatically.
4. On successful resume or exact-ID bootstrap, one locked transition rechecks both observed heads and writes the review-cycle activation plus lifecycle changes: original becomes `inactive`, reviewer becomes `active`, and the cycle becomes `active`. A stale confirmation, canceled bootstrap, failed process spawn, or ambiguous/captured-but-unpersisted launch leaves the prior original selection and lifecycle intact; unresolved launch recovery stays with the existing `pending`/`doctor`/`recover`/`attach` safeguards.
5. `return -a` resolves exactly one active cycle for the named original slot. Under the same registry lock it revalidates the reviewer and original heads and locks, appends the cycle-return event, sets reviewer `inactive`, sets the original `active`, and selects the recorded original session only if it remains the exact current session. The saved pre-review lifecycle remains in the durable cycle for history; explicit return is an activation request, including when the original had been inactive before review. It never creates a native conversation. If the original session is missing or its exact identity changed, return fails without mutating either slot and directs the user to `continue`/`attach` explicitly.
6. The post-exit menu preserves `[4] Switch provider` for the same slot. `[5] Switch to an existing agent` opens the inactive-agent picker; when the current slot is a reviewer, the linked original is prioritized and selecting it performs the linked return transition. `llmd return` remains the direct return command. `[6] Create a new agent` is the separately confirmed new-slot flow. Return after reviewer exit runs only after the reviewer process lock is released. On canceled/failed transitions, the current slot and active review context remain unchanged.
7. Only one transition per cycle can commit. Concurrent `review`/`return` requests serialize on the registry lock and revalidate cycle state; one succeeds, stale contenders get a recoverable conflict. Native session IDs and every prior activation remain in history; repeated activation of the same exact session is not duplicated unless the provider was actually resumed and existing activation semantics record it.

**Acceptance:** Codex↔AGY reviewer/original round trips beginning with both active and inactive originals; same-provider resume; automatic first reviewer initialization and explicit `-N` replacement; dry-run purity; same and different worktrees; interrupted, canceled, failed, and captured-but-unpersisted bootstrap; reviewer/original slot reuse; missing/changed original head; abnormal exits; in-use locks; duplicate and concurrent transitions; no duplicate slot/native session; and context-aware menu behavior. Option-4 acceptance also covers stale current-session changes during both new and reuse prompts, recorded Windows/WSL environment and cwd inheritance, incompatible target rejection without pending launches, and cancellation followed by a separate lifecycle choice with one scoped summary. All provider execution uses disposable registries and fake processes.

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

### Batch F — Native launch customization, cwd validation, and preview

**Scope:** LLMD-22–LLMD-24. New-session authorization remains explicit (`start --new -a`; reviewer creation `review -N -a`; post-exit option 6 confirmation). User-native options apply only to the interactive resume after bootstrap has captured and durably associated the exact session ID.

**CLI syntax:**

```text
llmd continue GUI AGENT -C WORKTREE -a -- --sandbox workspace-write --ask-for-approval on-request
llmd start GUI AGENT -p codex --new -a -C WORKTREE -- --sandbox workspace-write --ask-for-approval on-request
llmd switch -g GUI -n AGENT -p agy -a -- --sandbox --model MODEL --effort high
llmd review -g GUI -n ORIGINAL -R REVIEWER -p codex -a -- --sandbox workspace-write
llmd return -g GUI -n ORIGINAL -a -- --sandbox workspace-write
```

The separator is mandatory. The verified Codex `resume` allowlist is `--sandbox/-s`, `--ask-for-approval/-a`, `--model/-m`, repeatable `--enable`/`--disable`, and boolean `--search`, `--no-alt-screen`, `--no-daemon`. AGY accepts boolean `--sandbox`, `--model`, and `--effort`; `--mode` is rejected as an execution-mode override. Identity selection (`--last`, `--conversation`, etc.), bootstrap/print/exec controls, LLMD-owned cwd/worktree/add-dir controls, config/profile/settings overrides, and AGY permission bypass are rejected. `open`/terminal-pane native overrides are rejected because `open` may contain mixed providers; launch one selected slot with `continue` instead. Option 4–6 transitions validate options against the selected destination provider before any lifecycle transition.

`-C/--cwd` overrides only the current interactive launch for an existing session. Validate local paths as existing directories; for Windows-to-WSL paths require an absolute path and check it with argv-only `wsl.exe --distribution <recorded-distro> --exec test -d <path>`. A different repository/worktree root is surfaced in preview. Do not update native-session provenance when resuming with an override. For a newly created session, `-C` is the selected initial cwd and is recorded as its provenance.

Preview resolves the executable from PATH without invoking the provider, outputs a structured argv vector (never a shell string), cwd, environment ID/runtime/distro/ownership, session identity or bootstrap placeholder, and requested permission settings. `verified_effective` remains `null` because a preview cannot prove provider enforcement. No configuration is persisted. New-session bootstrap retains its fixed read-only prompt/flags and ID capture, then passes user overrides only to the captured-ID interactive resume.

**Acceptance:** exact Codex/AGY option placement from installed `--help`; explicit separator and spaces preserved as argv tokens; allowed repeated Codex feature flags; rejection of session identity, execution, bootstrap, settings, and directory conflicts; preview purity; requested-vs-effective permission diagnostics; cwd existence/runtime checks on Windows and WSL2; repository/worktree change detection; existing native cwd/history preserved; fake bootstrap receives no user overrides while interactive resume receives them; provider failure retains exact session/pending recovery state. Global pytest fixtures prepend controlled fake provider names, filter installed provider paths, and fail on every unexpected provider spawn, including resume commands. Tests must never invoke live Codex/AGY.

## 4. Non-negotiable invariants

- No destructive operations, deleting sessions, registry reset, loss of history or in-place worktree changes.
- No local LLM inference as part of testing. Fake provider bootstrap/output and subprocesses in tests; do not launch real Codex/AGY to exercise tests unless separately authorized.
- No new native session from a canceled prompt, `-d/--dry-run`, `continue`, or an unresolved/pending attempt. Operational `start`, `review`, and provider-named `switch` are explicit command intent for their documented initialization transitions.
- Do not equate `active` with `IN USE`. Same-runtime locks do not prove cross-OS process state.
- Keep exact provider session IDs and environment ownership; never construct guessed IDs or parse placeholder strings as verified native sessions.
- New `-N` list flag is command-scoped and must not change existing `start -N/--new`.
- Respect `NO_COLOR`, non-TTY, readable plain-text output, and existing JSON contracts.
- Keep provider overrides invocation-scoped and argv-only; never pass them into fixed bootstrap, persist them as profiles, or claim effective permission changes from requested flags alone.
- Preserve all original flags/API behavior absent an explicitly documented migration decision.

## 5. Test strategy and evidence requirements

**Unit/contract:** `dispatcher_v2_test.py`, `dispatcher_cli_test.py`, `dispatcher_ops_test.py`, `dispatcher_terminal_integration_test.py`, interactive selector tests, CLI parser/help tests, formatter snapshots. Add tests for auto-creation from named syntax, preview no writes, duplicate identical/different CWD/provider commands, legacy naming, both reactivation states, simultaneous starts, pending launch refusal and provider-switch transitions. For LLMD-19–21, cover the transition tables above with real event/materializer state and deterministic fake provider processes.

**Integration (disposable only):** temporary dispatcher registry, fake Codex/AGY provider executable/output, explicit pass/fail bootstrap, artificial session locks, subprocess normal and nonzero exits. No real accounts, no model turns.

**Reports:** command, observed exit status, short output, reviewed SHA, branch/worktree, changed paths, tests actually executed vs proposed, known limitations, and target next approval gate.

## 6.1 Independent Gemini review reconciliation from the implementation handoff

The implementation handoff carries the following reviewer constraints into the plan: review relationships persist across cycles; transitions are atomic and concurrency-safe; original and reviewer slots do not duplicate native sessions or registrations; exact session IDs and recovery safeguards remain authoritative; provider changes and distinct worktrees are supported; and post-exit actions must preserve option 4 while option 5 prioritizes a linked original in the general agent picker. These constraints are incorporated into LLMD-19–21's syntax, state model, transition rules, and acceptance matrix above. The portable evaluation brief in `02_PROPOSED_CHANGES_EVALUATION.md` did not contain a returned Gemini verdict or findings list, so no additional finding is attributed to that document.

## 7. Change-management boundaries

Each implementation batch uses its own isolated worktree/feature branch, or a single sequential feature branch if one agent owns every modified file. No simultaneous writers to `dispatcher_cli.py` or `interactive.py`. Commit and push authorized feature changes for review, **do not merge**. Do not change other tools/modules without a demonstrated interface dependency. Do not start public publishing, background inference or local model loading.

The v2.1 documentation began as a design proposal. This implementation handoff authorizes the sequential A–E implementation described here; compatibility changes outside that scope still require an approval gate. LLMD-39 is authorized on its own isolated branch and pauses for independent GUI review before integration; after acceptance, standing authorization permits normal reconciliation and GitHub merge workflow. Remaining evaluation criteria are listed in [02_PROPOSED_CHANGES_EVALUATION.md](02_PROPOSED_CHANGES_EVALUATION.md).

## Batch G — Terminal-specific launch context (LLMD-27–29)

**Approved persistence design:** append-only dispatcher launch-history events in the existing event spool, with a rebuildable SQLite projection. `TERMINAL_SESSION_ID` and `TERMINAL_SESSION_OWNER_PID` are read-only environment inputs. Only a syntactically valid UUID is a terminal scope key; owner PID is diagnostic metadata and never an ownership key. Missing or malformed IDs must not trigger a global fallback.

Each launch has a unique launch ID, so concurrent invocations, Windows Terminal panes and repeated launches from one shell append distinct records. Each launcher-created pane receives a distinct launcher-owned UUID through the hidden `pane-run -T` argument; it must not overwrite the initiating profile-owned shell ID or share another pane's context. That same context must be forwarded through post-exit options 4–6, including reviewer returns and subsequent transitions in the pane. The projection stores stable GUI/slot IDs, exact provider/session/environment identity, launch and exit timestamps/status, requested and effective launch cwd, recorded native session cwd, detected repository/worktree/branch/commit, and an allowlisted non-sensitive settings summary. Bootstrap records begin without a native ID and gain the exact ID only after safe capture; unresolved starts remain visibly pending/interrupted and are never retried automatically. A `launching` record means the outcome is unknown after hard termination, not that a live provider process has been verified.

**CLI contract:**

```text
llmd last                 # show the latest launch in this terminal only
llmd last -j              # one JSON document for this terminal's latest record
llmd last -N COUNT        # show the COUNT newest records for this terminal
llmd last -a              # resume the exact recorded session
llmd last -R -a           # explicitly reactivate an inactive slot, then resume
llmd recent               # read-only cross-terminal history
llmd recent -N COUNT -j   # bounded JSON history (read-only)
llmd last -C WORKTREE -a -- --sandbox workspace-write  # explicit invocation-scoped settings
```

`last -a` requires a recorded exact session ID and revalidates GUI/slot/session selection and session ownership under existing lifecycle guards. Completed slots are rejected. Inactive slots require both `-R` and `-a`. A missing, malformed, or stale terminal scope is a clear error; no global latest-session fallback is allowed. Resume never replays stored launch permissions, generic native options, or a stale launch cwd; only explicit current-invocation `-C`/native options may override defaults, and these are validated and previewed before activation. `recent` never mutates or resumes and redacts terminal IDs by default; JSON can expose terminal UUIDs only as registry metadata, not credentials.

Interrupted starts, failed spawns, normal/nonzero exits, bootstrap capture, resume, and post-exit switches each update history through new immutable events. A pane’s launch is separate even if multiple panes inherit diagnostic owner metadata. Git metadata is observational and may be incomplete when the target runtime cannot be queried safely; it never changes session provenance.

**Acceptance:** event rebuild/idempotence; multiple terminals and panes; concurrent starts; absent/malformed UUID; interrupted bootstrap and failed provider process; exact session resume and inactive/completed safeguards; no cwd/permission replay; requested/effective/native cwd distinction; Windows/WSL worktree metadata; post-exit switches; JSON/text history and read-only cross-terminal listing; old event-spool compatibility.

## Batch H — Comprehensive native CLI support (LLMD-30–31)

Common provider options become first-class managed settings when they are documented by the installed provider: permissions, sandbox/approval policy, additional directories, model, reasoning effort, supported configuration values and profiles. Managed settings receive provider-specific value validation, safe preview reporting and an allowlisted non-sensitive history summary. Codex config uses structured `-c key=value` arguments; AGY session settings use its structured `--settings` input only for supported non-secret keys. Raw prompts, credentials, file contents and arbitrary configuration are never persisted.

Unknown provider arguments are accepted only after explicit `--allow-native-unknown`; the option authorizes forwarding but does not bypass identity/bootstrap/execution-mode/executable/cwd conflict checks, or permission preview safeguards. The `--` delimiter remains mandatory. Structured argv token boundaries and provider-specific placement are preserved exactly. LLMD cannot establish the semantics or safety of unfamiliar provider flags, including aliases introduced by later provider versions; previews identify recognized permission-affecting settings and redact their values, but the operator must inspect installed help and review unfamiliar options. Unsafe recognized bypass/remote/executable/session-selection arguments remain forbidden even with authorization.

Managed `--add-dir` paths and AGY `additional_directories` values must be absolute in the selected provider runtime and are validated in that runtime before preview or launch. Relative paths are rejected to avoid depending on a host cwd different from the provider's effective cwd.

The common interface works on `continue`, `start`, `switch`, `review`, and `return` as applicable. New-session bootstrap remains fixed read-only and receives no interactive overrides; options affect only the subsequent interactive launch. Terminal-pane `open` propagation is supported only when a homogeneous provider/option contract is provable; otherwise LLMD reports an actionable explicit unsupported-combination error before any pane or lifecycle mutation.

**Acceptance:** exact option placement from installed help without inference; Codex resume and AGY conversation resume; managed aliases/equal forms/repeated flags; config/model/profile/reasoning/add-dir/permission settings; explicitly authorized generic passthrough; unsafe identity, mode, bootstrap, path and executable conflicts; permission preview; no raw setting persistence; WSL/Windows quoting; fixed bootstrap isolation; failure/session-history preservation; fake-provider isolation.

At the time of this v2.1 batch, LLMD-25 persistent launch profiles were next; they are now in the v2.3.0 candidate together with LLMD-48/49. LLMD-26 native lock diagnostics remain deferred.

## Batch I — Semantic terminal presentation (LLMD-39)

**Initial release:** LLMD 1.7.0. **Corrective release:** LLMD 1.7.1 (color-mode propagation and scoped Windows console VT support).

Centralize named semantic colors in `terminal_format.py`. Human-readable list, scoped list, selectors, continuation picker, post-exit menu, history, `last`/`recent`, doctor, launch previews, and related diagnostic messages use the same semantic palette. Keep text labels meaningful when color is disabled. Lifecycle (`active`/`inactive`/`completed`), runtime observation (`IN USE`/`NOT OBSERVED`/`PENDING`/`UNKNOWN`), and launch outcome (success/failure/interruption/unverified) remain independent dimensions.

Use bright blue bold for GUI headings, warm yellow bold for agent names, cyan Codex, magenta AGY, muted gray timestamps/labels, neutral gray native IDs, green active/in-use/success, amber inactive/pending/warnings, dim gray completed/not-observed, blue-gray unknown, red failures/unresolved IDs, and orange interruption. `-c/--color auto|always|never` applies consistently to subcommands that support human output, including interactive menus and nested selectors; `NO_COLOR` always disables styles. `auto` requires an interactive terminal and is disabled by `TERM=dumb`; on Windows, temporarily enable VT processing for the actual output console and restore the original mode after dispatch. This is invocation-scoped and does not persist terminal settings. Redirected streams remain plain by default. JSON fields/schemas are unchanged and contain no ANSI codes.

Listings compute available columns in terminal cells after accounting for Unicode width, combining characters and ANSI sequences. Use an aligned one-line row when the width permits, two-line rows at moderate widths, and stacked rows in narrow terminals. Prefer complete session IDs; clip deterministically only when the terminal cannot fit them. GUI groups have clear headings and subtle separators, with a blank-line separation retained as the no-color fallback. Empty groups, selected history rows, pending identities, and known unresolved placeholders are labeled explicitly. Rendering must not infer validity from UUID-like appearance or mutate stored IDs.

**Acceptance:** actual ANSI code/reset assertions for semantic fields and padded provider/lifecycle regression; auto/always/never and `NO_COLOR`; redirected output; Windows VT enable/restore on the actual output handle; widths 40/60/80/100/120/200; ANSI-safe cell measurement, CJK and combining marks; long session IDs; empty groups and selected/unresolved history; distinct runtime/lifecycle/outcome; launch, doctor, selector and post-exit output; JSON byte purity and schema compatibility. Capture checks prove emitted text/ANSI only; Windows Terminal and WSL/SSH smoke results are reported separately from actual visual rendering.

## Expanded roadmap — LLMD-25 through LLMD-56 (historical specifications; current state is recorded above)

This section preserves the roadmap sequence and design contracts from the v2.0.0 planning pass. Current delivery status and release evidence are maintained at the beginning of this file and in `STATUS.md`; the later Claude v2.1.1 merge and the v2.3.0 LLMD-25/48/49 candidate supersede the historical priority state below. Remaining roadmap entries are specifications, not authorization to implement them.

### Priority, ownership and sequence

1. **LLMD-56 Claude Code basic provider** — completed and merged as v2.1.1 through PR #46; live resumability qualification remains separately gated.
2. **LLMD-25 persistent profiles → LLMD-48 workflow types → LLMD-49 numbering** — implemented in the current v2.3.0 feature candidate. Freeze stable GUI/slot membership and number-allocation concepts before checkpoint or transfer schemas.
3. **LLMD-50/51 instruction discovery and additive initialization**, using the bridge interface below; then **LLMD-52/53 authoritative runtime identity and addressed-handoff validation** and **LLMD-54 activity/session reconciliation**.
4. **LLMD-40 and LLMD-26/41 terminal/runtime coordination** with Agent #3, then **LLMD-42 durable checkpoints → LLMD-43 shared restoration queue → LLMD-44 topology restore → LLMD-45 owned-session shutdown**.
5. Finalize **LLMD-55 cross-GUI transfer** only after LLMD-25/48/49 identity and membership contracts, plus checkpoint references, are stable.

Agent #1 owns dispatcher schemas/CLI, profiles, workflow initialization, number allocation, activity materialization, recipient validation, and cross-module shared interfaces. Agent #3 owns managed terminal lifecycle, native runtime discovery, and checkpoint internals; Agent #1 integrates their versioned contracts without editing their owned files. The legacy `agents` CLI remains compatible. LLMD remains a session continuity and initialization system, not an execution engine or plan tracker.

### Feature contracts and acceptance

| ID | Planned contract and minimum acceptance |
|---|---|
| **LLMD-25 — Persistent launch profiles** | Persist named, non-secret launch settings with explicit precedence `invocation > selected profile > provider/runtime default`. Validate provider/runtime compatibility at selection and show resolved provenance in preview. Revoked or absent authorization is never restored by a profile; profiles cannot store credentials, prompts, raw config, or permission-bypass options. Test precedence, provider mismatch, missing/changed profile, secret exclusion, and revocation across provider switches. |
| **LLMD-26/41 — Native runtime discovery** | Discover exact native processes/sessions for direct provider resumes, detached tasks, and LLMD-managed sessions. Record `observed`, `confirmed inactive`, and `unavailable/unknown` separately; absence of local evidence is never proof of inactivity. Cover races, PID reuse, platform/runtime ownership, detached tasks and permission/access failures using fixtures. |
| **LLMD-40 — Managed terminal lifecycle** | Integrate with Terminal Launcher 0.2's managed launch receipts, ownership, and lifecycle through its public API. Capture terminal/window/tab/pane identities and report requested versus observed layout separately. Keep terminal-launcher independent of LLMD; verify both dependency floors and consumer behavior before widening the version range. |
| **LLMD-42 — Durable workspace checkpoints** | Checkpoint an exact task/session envelope and workspace revision atomically. Capture actually open native sessions via verified observation, not merely slots marked active. Preserve exact provider/session/environment/worktree identities and mark missing or changed source evidence stale. Test crash recovery, partial writes, concurrent checkpoints, and immutable source references. |
| **LLMD-43 — Shared manual restoration queue** | Store queue entries in one atomic durable queue shared across agents/terminals. Deduplicate by immutable checkpoint/slot identity, support explicit claim/complete/cancel transitions, and prevent double restoration under concurrent operators. Preserve unresolved entries across restart and index rebuild. |
| **LLMD-44 — Automatic topology restoration** | Restore only a previously captured and operator-authorized terminal topology. Persist requested pane layout separately from observed pane receipts; use LLMD-40 receipts to determine what actually opened. Revalidate exact sessions, cwd/worktree and ownership before any launch; partial failures leave an actionable durable recovery record. |
| **LLMD-45 — Bounded owned-session shutdown** | Terminate only sessions for which LLMD/Terminal Launcher has verified ownership. Require bounded timeouts, report requested/sent/observed exit state distinctly, and leave unrelated or unverified processes untouched. Test refusal on identity ambiguity, races with resume/transfer, timeout, and partial termination. |
| **LLMD-48 — Workflow types** | Add persistent `standard`, `handoff`, and `goal` workflow types independently of permissions, provider, handoff mode, installer mode, delegation backend, or native goal activation. Untyped legacy slots retain current behavior; changing type requires an explicit operator action and emits a durable event. Test migration, JSON/listing, every independent dimension, and no implicit behavior changes. |
| **LLMD-49 — Agent numbers** | Allocate monotonically increasing positive numbers atomically per immutable GUI ID. Allocation is included in the committed creation event and registry transaction; previews never consume numbers and numbers are never reused. Reconcile legacy numbers only from verified sources; preserve independently verified assignments. Expose authoritative values in registration, list/status, JSON and future handoff exports. Reserve source numbers permanently after transfer; destination allocation is deterministic and collision-free. Test concurrent creation, event replay, gaps, legacy reconciliation, preview purity and transfer reservations. |
| **LLMD-50 — Prepared instruction discovery** | Discover packaged, installed, callable and runtime-verified instruction resources through the bridge API below. Resolve resources by stable ID and version/digest without installing hooks or mutating global instructions. Report missing, changed, unsupported, and unavailable resources distinctly. Test Codex/AGY, Windows/WSL, revision drift and provider switching. |
| **LLMD-51 — Additive workflow initialization** | For genuinely new native sessions, add assignment-free workflow context once through a provider-supported initialization surface; do not replay it on resume or create an unnecessary separate model turn. Permit an optional custom instruction-file reference and persist only minimal revision provenance, never full resource text or secrets. Concurrent starts, interruption, missing/changed resources, provider switches and Windows/WSL must be safe. If a provider cannot initialize additively, surface the limitation rather than silently skipping or mutating global instructions. |
| **LLMD-52 — Authoritative runtime identity** | Resolve runtime identity from trusted runtime/process metadata, distinguishing managed, unmanaged, unavailable and contradictory values. Preserve exact names including spaces. A native session prompt or incoming handoff never supplies authority to derive or mutate LLMD identity. Test multi-agent/subagent isolation, stale IDs, unavailable sources, and competing identities. |
| **LLMD-53 — Addressed-handoff validation** | Validate a handoff recipient deterministically against the authoritative runtime identity. Parse exact names (including spaces), reject contradictory structured headers, and ignore quoted/code-fenced examples as instructions. Unmanaged and unavailable identity are different outcomes. Hooks are read-only and must never grant permissions. Track hook/resource states separately as installed, callable, and runtime-verified. Do not add unconditional AGY `invocationNum` filtering or a general bootstrap-validation bypass. |
| **LLMD-54 — Activity and association reconciliation** | Detect stale activity and reconcile native-session associations from immutable events and verified provider evidence, including out-of-order events and direct native resumes. Prefer event time plus stable sequence/identity; never let late observations silently replace a newer selected session. Unavailable evidence stays unknown. Test duplicate/out-of-order events, provider repurposing, exact-ID retention and projection rebuild. |
| **LLMD-55 — Cross-GUI slot transfer** | Atomically move an immutable slot identity between GUI memberships while preserving native session identity, workflow/profile, history, source historical membership/number reservations and checkpoint references. Require explicit destination conflict handling and stable destination numbering; refresh runtime identity only from safe verified evidence. Support transfer-back without number reuse. Serialize against concurrent launch/review/return and test crashes, stale heads, duplicate names, cross-GUI conflict, reconstruction and rollback. |
| **LLMD-56 — Claude Code provider (P0)** | Add canonical provider ID `claude` through the shared adapter abstraction. Minimum release supports registration, first-session creation, exact `--resume`, attach/recover, listing/history, provider-safe argv and Codex/AGY switching. Qualify operator-supplied UUID via `--session-id`; distinguish reserved identity from confirmed creation and durable resumability. Exit-before-first-prompt, interrupted/failed initialization, duplicate IDs and concurrent starts remain unresolved/pending, never guessed or auto-retried. Preserve Claude permission controls; reject identity-changing, bypass, or incompatible execution flags. Authentication remains provider-managed. Normalize lifecycle events only from offline fixtures; do not install hooks or activate prepared workflows. Acceptance includes missing executable, Windows paths, dry-run purity, exact resume, registry rebuild, switch directions, and full Codex/AGY regression suite. Live qualification requirements are reported separately. |

### `local_agent_bridge` interface boundary (proposed v1)

The bridge owns reusable instruction contents, package/install layout, global instructions, skills and provider hook installation. LLMD owns resource selection, additive initialization, continuity, authoritative agent identity and recipient validation. Define a small read-only `workflow-instructions/v1` API with `list_resources(provider, runtime) -> ResourceDescriptor[]` and `read_resource(resource_id, revision) -> ResourceSnapshot`; descriptors carry stable resource ID, revision/digest, provider scope and availability, and snapshots are immutable. LLMD stores only selected IDs/digests and minimal revision provenance. No circular dependency, duplicated resource ownership, shared-global instruction mutation, hook installation, or resource-content copy into LLMD registry is permitted.

Codex `UserPromptSubmit`/`SessionStart` and AGY `PreInvocation` are qualification targets, not verified capabilities. Verify each installed version's schema and behavior before enabling a hook path. Keep installed, callable and runtime-verified as separate states; hooks used for identity/recipient observation are read-only. Missing/changed resources and unavailable hooks produce explicit outcomes; they never broaden permissions or bypass validation.
## LLMD-57 — Cross-provider launch-context portability

**Status:** Implementation and guarded cross-provider execution qualification completed locally on `feature/llmd-57-portable-launch-context-20261127`, based on v2.3.0 candidate `85447be1b4d1ade361b212a4b39862f23fc3363e`. Final full-module and compatibility qualification, task-only diff review, commit, and push remain.

**Design contract:** Resolve an explicit portable context from existing slot, profile, environment, session, and workspace records. Do not persist or translate raw source-provider argv. Keep provider/model preferences destination-scoped. Normalize semantic reasoning, filesystem, approval, network, context/search/MCP settings; emit destination arguments only for capabilities verified in the provider adapter. Treat unknown, incompatible, or conflicting settings as preview entries and preserve unrelated portable settings. Missing directories, worktrees, or runtime identities are errors; never recreate or substitute them. Permissions may remain equal or become stricter, never silently broader.

**Integration:** Share one resolver and preview result across switch/start/continue/open/review-return, option 4, native-session replacement, and workspace restore. Preview each item as preserved, translated, restored, unsupported, or conflicting and require explicit handling of material incompatibilities before launch. Preserve exact repository/worktree/branch observations, explicit cwd overrides, approved additional roots, runtime identity, workflow/agent identity, compatible terminal settings, portable instructions, and non-secret launch settings.

**Qualification:** Guarded fake providers only; all six directions exercise actual CLI switch/continue invocation, round trips, historical-session reuse, nested worktrees, explicit `-C`, multiple repositories, incompatible options, destination preferences, permission non-broadening, and Windows/WSL boundaries. The affected 87-test set passed with `pytest-xdist -n 4`. Workflow-resource bytes/digests and session-specific delivery have focused end-to-end coverage. Provider-loaded context, resume persistence, and real WSL/provider behavior remain unverified. Keep all LLMD-57 test evidence separate from the v2.3.0 release candidate.

## LLMD-58 — Reproducible provider exit summary

For normal, abnormal, and handled interrupted launches, render the actual executed identity: GUI, agent name and number, immutable slot ID, provider, exact native session ID, and effective cwd. Include a directly copyable `llmd continue` command using platform-appropriate shell escaping. Reconstruct only validated safe settings from the actual invocation and inherited profile, including authorized additional directories; omit secrets, bootstrap/reservation arguments, and one-time prompts. Explicitly list settings that cannot be reproduced and preserve existing lifecycle/uncertainty gates. Never use stale selected-slot state when the executed launch record is available.

**Acceptance:** Disposable provider processes cover zero/nonzero/interrupted exits, profile inheritance, exact session selection, spaces/Unicode in paths, PowerShell and POSIX quoting, authorized directories, secret/transient exclusion, and non-reproducible settings. Parsed resume commands must preserve identity and must not broaden permission settings.

## LLMD-59 — One-time native launch prompt delivery

Add mutually exclusive `-Q/--clipboard-prompt`, `-F/--prompt-file`, and `-M/--prompt` launch inputs. `-P` is already assigned to `--profile`, so clipboard input uses `-Q`. Resolve clipboard/file/inline content once, preserve multiline Unicode, validate addressed handoffs against the exact registered launch target, and deliver only through provider-documented interactive mechanisms for the exact destination session. Dry-run output must never include prompt content. Do not persist raw prompt text or place it in an exit/resume command. If delivery outcome is uncertain, refuse automatic resubmission; if the provider lacks a supported interactive submission API, fail explicitly rather than automate keystrokes.

**Acceptance:** Guarded provider adapters qualify exact-once delivery, Unicode, multiline text, addressed handoff validation, dry-run redaction, file/clipboard errors, exact session correlation, uncertainty without replay, and unsupported-provider refusal. Initial bootstrap optimization is coordinated through the Agent #3 design boundary; no implicit goals or extra model turns are introduced.

## LLMD-61 — Repository-local worktree convention

All new worktrees provisioned by scripts-owned LLMD functionality live at repository-root `/.worktree/<short-name>` using singular `.worktree`. Add a root ignore rule and exclude this directory from recursive repository discovery. Preserve existing worktrees and do not relocate them during execution. Apply the convention only to LLMD provisioning owned by this repository; do not modify tooling owned by other repositories.

**Acceptance:** Path-planning and discovery tests cover nested repositories, existing active worktrees, singular path spelling, ignore behavior, and exclusion from recursive discovery. No existing worktree is moved and no external repository tooling is changed.
