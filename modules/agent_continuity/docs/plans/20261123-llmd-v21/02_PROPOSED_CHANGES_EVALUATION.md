# LLMD v2.1 — Proposed UX, API Changes, and Independent Evaluation Brief

**Purpose:** Standalone specification to give another LLM / reviewer for a critical design evaluation **before** implementation.  
**Baseline examined:** `MaxCarlson/scripts` `main` `7b9f596ac1abebd5be8395962bfb8124379b082e`.  
**Related:** [Implementation plan / 18 features](00_IMPLEMENTATION_PLAN.md) and [current source-backed CLI reference](01_CURRENT_CLI_REFERENCE.md).

> The requested changes are **not implemented** in this document. Verify any implementation claims against the latest repository head, not this static baseline.

## 1. User requests consolidated, in order

1. Add a **fourth choice to the post-provider-exit prompt**: switch from the just-exited Codex session to an AGY session, or from AGY to Codex, retaining the same named agent.
2. Color-code Codex and AGY differently. Color-code lifecycle `active`/`inactive`/`completed`. Add per-agent and per-GUI last-activity dates and times in `llmd list`.
3. Add a visual divider/blank line between one GUI heading and the next in the global list.
4. Fix interactive chooser columns shifted by long names; review whether top-level help exposes redundant administrative/internal commands.
5. Add `llmd list -g GUI -N 3`: under **each local agent**, show up to three newest **session activation history** entries, indented. History fields in order: **date/time**, **Codex or AGY**, **native session ID**.
6. Protect against reissuing the same `llmd start` request after a session exits. Show existing native session identity and ask whether the user wants to continue it or create a genuinely new conversation.
7. After the user chooses post-exit option 1/2/3/(4), print the scoped LLMD listing for the current GUI reflecting the resulting state.
8. Make GUI/slot creation automatic when `llmd start -g GUI -n AGENT` is used, just as the positional `llmd start GUI AGENT` already does. The user reproduced `Agent slot not found` using the named syntax.

These eight original user requests are decomposed into **LLMD-01–LLMD-18** in the plan. Subsequent implementation handoffs added LLMD-19 reviewer cycles and LLMD-20/21 exit-menu switching and creation; option 5 is the general inactive-agent picker with linked original prioritized, while option 4 remains same-slot provider switching. The current contract and acceptance table are in `00_IMPLEMENTATION_PLAN.md`.

## 2. Proposed user-visible interfaces

### A. New named agent — equivalent syntaxes

```powershell
$gui = "llm-agent-toolkit"
$agent = "pypi-release-review"
$repo = Join-Path $HOME "src\shared-python-modules"

# Both SHOULD produce equivalent nonmutating previews:
llmd start $gui $agent -p codex -C $repo
llmd start -g $gui -n $agent -p codex -C $repo

# Both SHOULD explicitly register missing GUI/slot and start exactly one new native conversation:
llmd start $gui $agent -p codex -C $repo -N -a
llmd start -g $gui -n $agent -p codex -C $repo -N -a
```

A preview must distinguish "would register GUI", "would create slot", "would launch new Codex", and existing-selection conflicts. A new GUI/slot is not a new ChatGPT GUI conversation. `start` must never invoke a provider in preview mode.

### B. Existing-session duplicate detection

When a named slot already selects a native session, canonicalize the GUI and slot identities; do **not** compare literal command strings.

Proposed interactive flow:
```text
GUI: llm-agent-toolkit
Agent: pypi-manager
Selected: CODEX 01a20924-cb95-7b60-b593-ad88be506291
Lifecycle: inactive
Runtime: NOT OBSERVED (same-runtime lock only)

This agent already has a selected native conversation.
Resume the selected conversation? [Y/n]
  Yes: preview/resume with explicit approval, including reactivation if necessary.
  No: do not launch; explain how to request a new conversation with -N -a.

If the invocation already included -N -a:
Start a NEW Codex conversation under the same slot, preserving history? [y/N]
```

**Policy recommendation:** `-N` remains the explicit new-conversation authorization and `-a` applies mutations. A TTY prompt protects accidental duplicates; a non-TTY invocation can create a new session only with `-N -a`. Declining the prompt neither starts nor resumes anything without an affirmative resumption choice. For an inactive slot, reactivation is separately explicit. For a completed slot, existing completion protections remain; do not silently reactivate.

If provider differs from the selected one, use "switch provider" terminology. If pending bootstrap exists, do **not** present a simple new-session confirmation; direct to `pending`/`doctor`/`recover` first. Inspect selected session/in-use lock again before applying under the appropriate concurrency safeguards.

### C. Post-exit option 4

For Codex:
```text
Runmux-Chart-Fix has exited.

[1] Keep active (default)
[2] Mark completed
[3] Mark inactive
[4] Switch to AGY
Selection:
```

For AGY, option 4 is `Switch to Codex`.

Selecting 4 should first identify whether the opposite provider has any prior activation under **this same slot**. If it does, offer **reuse previous session** versus **start new session**, with explicit confirmation before any new native conversation. If none exists, offer a preview of new initialization and require authorization. Do not create a second LLMD slot.

Only a successful provider bootstrap with an unambiguous captured native ID may change the selected session. A failed/canceled switch keeps the old selection and history. Existing per-session runtime locks and pending-launch recovery protections remain in force.

### D. Post-exit scoped listing

After a lifecycle decision is committed, display the equivalent of `llmd list -g <current GUI>` using the same internal formatter, not a subprocess. When the option 4 operation launches another provider, suppress intermediate duplicate reports and show the scoped summary once when the switch chain settles.

The reporting helper should optionally include the just-completed slot even when default filtering would omit completed entries. Show the actual postdecision state. For a failed update, clearly report failure and display the unchanged state.

### E. List and history display

Requested commands:
```powershell
llmd list
llmd list -g llm-agent-toolkit
llmd list -g llm-agent-toolkit -N 3
llmd list -g llm-agent-toolkit -N 0
llmd list -g llm-agent-toolkit -N 3 --color never
llmd list -g llm-agent-toolkit -N 3 -j
```

Proposed **ASCII representation** (example rows/history, not actual database values):
```text
llm-agent-toolkit                                   Last activity: 2026-11-23 11:26
  Agent                       Provider  Last activity       Lifecycle  Runtime        Session
  pypi-manager                CODEX     2026-11-23 11:26    inactive   NOT OBSERVED   01a20924-...
    History: 2026-11-23 11:26  CODEX     01a20924-cb95-7b60-b593-ad88be506291  *
             2026-11-22 19:32  AGY       <example-native-id>
             2026-11-21 14:16  CODEX     <example-native-id>
  shared-python-integration   CODEX     2026-11-23 09:45    active     UNKNOWN        01a1f505-...

Local-LLM-Optimization                            Last activity: 2026-11-23 08:45
  ...
```

The history line has its **own** ordered columns date/time → provider → ID and is indented right of the agent row. Use activation timestamps, not mutable slot last-activity timestamps, for history entries. History is newest-first and is not deduplicated: repeated activations of one native session are legitimate. A `*` denotes the selected activation; it must not imply the process is running.

Colors when supported: `CODEX` cyan, `AGY` magenta, `active` green, `inactive` yellow/dim, `completed` dim/neutral. Colors are redundant with plain text, not the only state signal. `--color auto` obeys terminal capabilities and `NO_COLOR`. Global list groups need a visually clear blank line or divider. Fit terminal columns without huge whitespace gaps or ANSI-length miscalculation. In narrow terminals, prioritize agent name, provider, lifecycle, and meaningful ID; truncate deterministically and retain full IDs in `-j`.

**History API:** `-N` / `--history-count` is a nonnegative integer *only on `list`*. It does not collide with `start -N/--new`. `-N 0` is the default and adds no history payload to JSON. `-N 3` adds up to three activation records per **displayed** agent in both scoped and global listing. Limits apply to top-level agents, not child history rows.

### F. Interactive selector alignment

Current formatting uses minimum widths such as `{name:<14}`: a longer name pushes the provider and session to the right. Use a shared width-aware table utility that accounts for the selector prefix, all row lengths, ANSI sequences, printable Unicode width, and available terminal width. Align header and data columns in GUI and agent selectors, with tests for long names and narrow terminals.

### G. Help and command consolidation

Preserve core `start`/`continue`/`switch`/`list`/`open`/`history`, as well as diagnostic/recovery `doctor`/`pending`/`recover`/`attach` and administrative `gui`/`slot`. Decide only after caller audit whether `register` should be deprecated; currently `register` applies by default and must not silently change behavior. Make `pane-run` internal: never show `==SUPPRESS==` in normal top-level help, but do not break terminal-launcher integration.

Do not remove `gui add` or `slot create` simply because `start` can auto-register: these remain useful without creating a provider session. Clear documentation should prefer the simplest path for new agents.

## 3. State invariants and edge cases that matter

- Native session identity = provider + environment identity + exact native session ID. Agent slot identity is separate and must remain stable across provider changes.
- Same native session may appear in multiple activation events; selected activation is latest, regardless of whether process exits.
- `active` means lifecycle intent, **not** that the provider process is running. `IN USE`/`NOT OBSERVED`/`PENDING`/`UNKNOWN` are observational labels and subject to environment-ownership limitations.
- A normal exit can prompt for lifecycle action. Nonzero exit must not silently suppress useful error information or launch another model. Any proposed change to show a post-exit summary after abnormal exits should retain the original error code.
- A captured-but-unpersisted bootstrap ID is recoverable, not permission to start again. No auto-retry of ambiguous/billable bootstrap.
- Interactive new-session decisions must be single-use and bound to the observed slot/head state; concurrent starts/rebinds require revalidation to avoid stale-confirmation races.
- User-facing time means **local system timezone**; missing time uses `—`; no conversion of unknown to 1970 or "now".
- Unresolved IDs and literal placeholder-looking IDs must not be silently treated as verified native provider IDs. Use existing validation and provenance rather than only a string-pattern heuristic.
- The existing `list` global vs scoped state filtering is not uniform. Reviewer should recommend whether `-A/--all` means include completed for both; likely yes, but establish a compatibility test.
- Existing scripts, JSON payloads, dry-run semantics, Windows Terminal launch plans, and supported Windows/WSL/Linux environments must be preserved unless explicitly authorized to change.

## 4. Independent LLM evaluation assignment

Ask the reviewer to produce **only** a technical assessment, not code and not a PR.

**Review against** `01_CURRENT_CLI_REFERENCE.md`, `00_IMPLEMENTATION_PLAN.md`, and latest repository source; label anything not verified. Evaluate:

1. **Completeness:** Are all 18 requirements captured? Does any proposed policy conflict with the exact user requests (especially duplicate-start yes/no interaction and the post-exit provider switch)?
2. **Correctness:** Where are session registration, activation and pending-launch transitions performed? Is the proposed new-`start` flow atomic enough? Are there TOCTOU races around checking existing session and confirming a new one?
3. **Compatibility:** Identify old `register`/`start -g/-n` callers, `-N` command-scoping collisions, JSON/schema consumers, and terminal_launcher `pane-run` dependencies. Distinguish necessary behavior changes from optional deprecations.
4. **UX:** Recommend precise default prompts, cancellation handling, status/runtime labeling, history presentation, width rules, UTC/local date policy, colors and non-TTY fallback.
5. **Testing:** Specify focused unit/integration tests for fake provider bootstraps, exit choices, interrupted launches, stale registry state, nested provider switch, concurrent starts, ANSI/Unicode alignment, history repeated entries, and completed slots.
6. **Batching:** Confirm whether Batch A/B/C ordering minimizes risk. Flag any cross-file shared ownership that makes parallel writers unsafe.
7. **Scope discipline:** Do not suggest local inference, production services, new chat creation, destructive registry operations, unapproved API breakage, or automatic retries.

**Expected evaluation output:**
- A verdict (`ACCEPT` / `ACCEPT WITH MODIFICATIONS` / `REVISE`);
- ranked blocking findings with code-path evidence;
- an exact list of ambiguities requiring product decisions;
- a revised acceptance-test matrix and recommended first agent batch;
- an explicit statement that no code was executed/modified if that is the case.

Do not implement, commit, push, merge, publish, or open a new agent session as part of this evaluation. This document is intended as a portable evaluation handoff; the GUI operator may later issue a separate authorized implementation handoff.
