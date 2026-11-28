# agent_continuity

Local-first GUI–Agent Session Continuity Module with the backward-compatible `agents` CLI and the named-session dispatcher (`llmd` / `llm-dispatcher`) for native OpenAI Codex CLI, Google Antigravity CLI (`agy`), and Claude Code sessions.

See [docs/agent-session-continuity-master-plan.md](./docs/agent-session-continuity-master-plan.md) for the governing Master Implementation Plan (v3.0) and [docs/adr/ADR-001-phase0-architecture-decisions.md](./docs/adr/ADR-001-phase0-architecture-decisions.md) for Phase 0 architecture decisions.

## Listing and registering conversations (LLMD v2)

`llmd list` shows the ten most recently active registered conversations and their active and inactive agents; `-A` also includes completed agents and removes default limits. An explicit `-l` limits results even with `-A`. Output reports omitted counts, local activity times, lifecycle, and observed runtime separately. Use `-N 3` to include three recent activation-history entries under each shown agent, `-j` for JSON, and `-c never` to disable color. Global JSON keeps schema version 1; scoped JSON retains `action`, `gui`, and `slots`. History adds an optional per-agent `activation_history` array only when `-N` is positive.

### Semantic terminal presentation (LLMD-39)

Human-readable output uses semantic colors for GUI names, agents, providers, timestamps, native session IDs, lifecycle states, runtime observations, and launch outcomes. Labels remain meaningful without color. Lifecycle and runtime are separate: `active` means the slot lifecycle is active, while `IN USE` is an LLMD-managed process-lock observation; `NOT OBSERVED` does not prove a provider is stopped. Pending, unknown, failed, interrupted, and unresolved records keep distinct text and styles.

Listings and selectors adapt to the available terminal width using terminal-cell measurements. Wide terminals use aligned rows; narrower terminals stack fields and clip only when required to fit. Full native IDs are kept when space permits. GUI groups have visible headings and separators, and empty groups are labeled. The same style palette is used by human-readable selectors, post-exit choices, `history`, `last`/`recent`, `doctor`, launch previews, and diagnostics.

`-c/--color auto|always|never` controls human-readable output on supported subcommands, including the interactive menu and nested selectors. `auto` enables ANSI for interactive terminals unless `TERM=dumb`; on Windows it temporarily enables VT processing on the actual output console and restores the prior console mode when the command ends. This does not change persistent terminal settings. `NO_COLOR` disables color in all modes, including `always`, and redirected output defaults to plain text. JSON schemas and values are unchanged and ANSI-free. Captured ANSI output demonstrates emitted control codes; it does not by itself prove how a particular terminal renders them.

```powershell
llmd list
llmd list "Project" -l 25
llmd list -g "Project" -A -j
llmd register "Project"
llmd register "Project" "Agent" -p codex -i "SESSION_ID"
llmd register -g "Project" -n "Agent" -p agy -i "SESSION_ID" -d
llmd continue "Project" "Agent"  # resume the exact selected session
llmd continue "Project" "Agent" -d  # preview without launching
llmd list -g "Project" -N 3
```

Registration applies by default and never launches a provider. `-d` previews it. Existing associations are left unchanged; selecting a different session requires `-s/--select` and preserves history. Runtime use is not observed in this release, so verify the session is not in use before changing a selection. Registration uses existing events and a single mutation lock; interrupted operations can be retried. LLMD operational commands execute by default; use `-d/--dry-run` to preview. `-a/--apply` remains a compatibility alias. `start` and `continue` also accept GUI and agent positional names.

## Persistent profiles and stable agent identity (LLMD v2.3.0)

Launch profiles hold normalized, non-secret provider settings and can be assigned to a slot or selected for one invocation. Settings resolve as invocation options over the chosen profile over provider defaults; `--no-profile` bypasses an assigned profile for that invocation. Profiles are revalidated against the destination provider/runtime and current paths each time. They do not store prompts, credentials, raw configuration, unknown arguments, new-session authorization, or permission-bypass settings, and cannot restore authorization that was not explicitly supplied for the current launch.

```powershell
llmd profile create safe-codex -p codex -s sandbox=workspace-write -s approval_policy=on-request
llmd profile assign -g Project -n Agent -P safe-codex
llmd continue Project Agent -P safe-codex -d
llmd profile list
llmd workflow-type Project Agent handoff
llmd list -g Project -j
llmd agent-number Project LegacyAgent 12 --source "verified handoff record 2026-11-27"
```

`standard`, `handoff`, and `goal` are descriptive workflow metadata only; legacy slots remain untyped until explicitly changed. Each slot receives an immutable `slot_id` and each GUI membership a positive, monotonically allocated `#agent_number`. Numbers are allocated atomically with slot creation, never consumed by dry-run, and never reused. Existing numbers are retained; importing independently verified legacy numbers requires the explicit `agent-number --source` command. JSON keeps its existing schema version and adds optional identity/profile metadata fields.

Release review boundaries: persistent profiles are the v2.2.0 slice; workflow types and stable numbering ship together as v2.3.0 because they form checkpoint-ready identity metadata. This branch combines all three for qualification. Checkpoints, runtime discovery, terminal ownership and transfer remain separately owned roadmap work.

## Portable launch context (LLMD v2.4.0 candidate)

Provider switches and workspace restoration resolve exact repository/worktree observations, effective and explicit working directories, authorized additional directories, runtime identity, workflow and logical agent identity, compatible terminal settings, portable instructions, and destination-scoped provider preferences from saved session/workspace records. Common semantic settings are translated only where the destination adapter has verified support. Previews classify values as preserved, translated, restored, unsupported, or conflicting; missing paths and permission broadening block execution. Raw source-provider arguments are never replayed. Unsupported provider-specific options do not erase unrelated portable context.

The qualified six-direction matrix uses guarded Codex, AGY, and Claude substitutes. Resource snapshots retain exact resource IDs, revisions, and byte digests, while workflow content is delivered through session-specific additive initialization where supported. Provider-loaded context, context surviving compaction/resume, and Claude workflow initialization remain unverified or unsupported; inherited Claude workflow initialization is rejected before provider invocation.

## Session-specific instructions and native allocation (LLMD v2.5.0 candidate)

`start`, `switch` to a new session, and `review` of a new reviewer accept repeatable `-I/--instructions-file` (the older `--instruction-file` remains valid). Paths resolve from the effective launch workspace. LLMD records ordered canonical paths, stable path identities, and exact content digests; it does not store instruction text. Exact-session resume never replays initialization. If a saved source changed or disappeared, LLMD refuses to submit a partial payload; `-Y/--replace-instructions` explicitly authorizes changed bytes or a replacement set. Changing workflow selection preserves independently selected custom files.

```powershell
llmd start Project Agent -p codex -N -I .\AGENTS.md --instructions-file .\review\rules.md -d
llmd start Project Agent -p codex -N -Y -I .\AGENTS.md -a
```

Workflow instructions may be submitted by the legacy fixed-bootstrap path where supported; that path consumes an initialization model turn, and provider-effective loading or persistence through resume is unverified. The guarded Codex native-allocation path defers ordered instructions and the LLMD-59 one-time prompt to the exact interactive attach; neither is submitted during allocation. The native AGY path refuses instruction and prompt delivery before allocation. Claude's UUID allocator reserves an ID only; it does not start Claude, persist a provider transcript, or prove effective cwd or resumability. Claude workflow instruction initialization remains unsupported. Codex/AGY native-allocation activation and live prompt delivery remain unqualified and disabled.

## Named Agent Dispatcher

`llmd` stores local GUI aliases, named agent slots, lifecycle state, pending launches, and ordered session activations in the same durable event spool and rebuildable SQLite index used by `agents`. A local GUI alias does not create a conversation in ChatGPT.

Install the module to generate both dispatcher executables:

```powershell
llmd
llm-dispatcher --help
```

With an interactive terminal, `llmd` opens the selector. Type to filter names, use Up/Down and Enter to select, Esc to go back, Ctrl+N to register an alias or slot, and Ctrl+A on the agent list to open all selected sessions. Ctrl shortcuts avoid conflicting with incremental text search. Noninteractive no-argument calls print help and do not open a menu.

Operational commands execute by default. `start GUI AGENT -p PROVIDER` resumes its selected exact session, or creates missing local records and initializes the first native session when no session is selected. `continue` resumes only an exact existing session and never creates one. `review` resumes an existing reviewer or initializes a new reviewer slot. `switch -p PROVIDER` performs the requested provider switch; `switch -r` explicitly reuses a prior session. Use `-d/--dry-run` to preview. `-a/--apply` remains a compatibility alias:

```powershell
llmd gui add -n AgentImprovement
llmd gui rename -g AgentImprovement -n AgentPerformance
llmd slot create -g AgentImprovement -n AgentPerf
llmd start -g AgentImprovement -n AgentPerf -p agy
llmd start -g AgentImprovement -n AgentPerf -p codex -N
llmd start -g AgentImprovement -n AgentClaude -p claude
llmd continue -g AgentImprovement -n AgentClaude
llmd attach -g AgentImprovement -n AgentPerf -p agy -i <native-session-id>
llmd attach -g AgentImprovement -n AgentClaude -p claude -i <session-uuid>
llmd switch -g AgentImprovement -n AgentPerf -p codex
llmd switch -g AgentImprovement -n AgentPerf -p agy -r
llmd list -g AgentImprovement
llmd history -g AgentImprovement -n AgentPerf
llmd pending -g AgentImprovement
llmd open -g AgentImprovement -k 2
llmd open -g AgentImprovement -k 4
llmd slot disable -g AgentImprovement -n AgentPerf
llmd review -g AgentImprovement -n AgentPerf -R AgentReview -p codex -C "C:\\worktrees\\review"
llmd return -g AgentImprovement -n AgentPerf -a
```

After a normal provider exit, option 4 reuses or explicitly creates the opposite provider under the same slot. It revalidates the departing activation before changing selection; new sessions inherit that session's recorded environment and working directory, reused sessions retain their own recorded values, and incompatible environments are rejected. Canceling option 4 returns to the exit menu. Option 5 opens a searchable picker of inactive agents in the current GUI and resumes the selected exact session; it never starts a new session. Option 6 collects a new name, provider, and confirmed existing working directory, then requires an affirmative confirmation before creating a slot and initializing one new session. The linked original agent is listed first when returning from a reviewer.

Post-exit switching keeps `-C/--cwd` and provider-native arguments scoped to the session that received them. Options 4–6 explain when an override can or cannot apply to the selected destination. For compatible provider arguments, choose to apply them explicitly or use destination defaults; incompatible arguments require confirmation to proceed with defaults or cancellation. Existing-agent destinations default to their own recorded environment and working directory. Option 6 uses the newly selected directory. Cancel if you need different settings, then resume the destination directly with its own `-C` and provider options.

`llmd review -g GUI -n ORIGINAL -R REVIEWER -p PROVIDER -C WORKTREE` resumes an existing reviewer session or initializes a first session for an empty reviewer slot. Add `-N` to replace the reviewer's selected session; prior sessions remain in history. The original may be active or inactive; its lifecycle and exact selected session remain unchanged until the reviewer launch durably captures its exact identity. `llmd return -g GUI -n ORIGINAL` deactivates the reviewer, reactivates the original, and resumes the original's recorded exact provider session. Review cycles retain pre-review lifecycle and slot/session transitions durably through SQLite index rebuilds. `-N -a` remains a valid legacy spelling. Provider execution in automated tests uses fake processes only.

Starting a new Codex or AGY session uses the bounded two-stage bootstrap. The dispatcher persists a pending launch, runs one fixed initialization-only model turn in a read-only/headless provider invocation, captures the exact Codex JSONL `thread.started.thread_id` or AGY JSON `conversation_id`, then resumes that identity interactively. Claude Code uses its documented `--session-id <UUID>` option for one direct interactive start and does not run a separate bootstrap turn. LLMD commits one reserved UUID and one durable spawn claim per pending launch; repeated or concurrent invocations cannot allocate a competing UUID or spawn a second session. It associates the session only after one exact, unique, nonempty UTF-8 JSONL transcript with valid object records is found. Malformed, unreadable, contradictory, or duplicate evidence is reported as unavailable; a complete scan with no exact transcript is confirmed absence at that time. A clean exit without a transcript remains pending for exact-ID recovery. Neither a reserved UUID nor transcript presence proves live resumability. Exact Claude resume uses `claude --resume <UUID>`, never `--continue` (which selects the provider's most recent conversation); no live provider resume probe is performed.

If the bootstrap exits unexpectedly or cannot return one successful, unambiguous ID, the dispatcher records that the attempt has already started and will not repeat a potentially billable initialization automatically. `llmd pending` shows any captured ID and recovery detail. If the exact ID is known, resolve the pending launch with `llmd attach -g GUI -n AGENT -p PROVIDER -i SESSION_ID -L LAUNCH_ID -a`; otherwise inspect the native provider's session list and attach only after verifying the intended session. Repeated selections of a previously bound native session remain separate entries in activation history.

`llmd open` creates opaque per-slot `PaneSpec` requests and delegates grouping and execution to the reusable `terminal_launcher` package. It submits the launch by default; pass `-d` to inspect the plan without submitting it. Unresolved or pending session IDs are listed for manual recovery and are never turned into a guessed resume command. The dispatcher does not construct `wt.exe` commands itself.

The pane wrapper prompts after a normal zero exit. Keep active is the default; a nonzero exit or an unexpected wrapper/terminal shutdown leaves the current session and slot state unchanged. Switching to an existing or new agent validates the destination before changing the departing slot's lifecycle.

## Current Status

- **M1/M2 continuity foundation:** Integrated and preserved
- **Named dispatcher:** Integrated from `feature/llmd-agent-dispatcher-20261119` at `db8d5779`.
- **Terminal launch integration:** `llmd open` uses `terminal_launcher` for immutable launch planning, previews, layout grouping, and request submission. Real pane geometry remains unverified without a live Windows Terminal smoke test.
- **Session-ID correlation:** New Codex and AGY sessions use per-process structured bootstrap output; Claude uses an operator-unseen LLMD UUID passed to its direct interactive `--session-id` option and exact `--resume` afterward. No global hook installation is required for initial association. Failed/interrupted launches are never retried automatically; manual attachment requires an operator-verified ID.

## Installation

`agent-continuity` requires the reusable `terminal-launcher` package at runtime. The repository setup workflow reads package metadata and installs local modules in dependency order, so it installs `terminal-launcher` before `agent-continuity`. Windows Terminal itself is not a Python dependency and is only needed when submitting a real Windows Terminal launch.

For a local development install from the repository root, install both source packages in one pip invocation so the local dependency satisfies the requirement without relying on a package index:

```powershell
python -m pip install -e .\modules\terminal_launcher -e ".\modules\agent_continuity[dev]"
```

For wheel deployment, build both packages from the repository root and install both wheels in one invocation. The dependency metadata still requires `terminal-launcher`; installing only the dispatcher wheel without a compatible terminal-launcher distribution will fail clearly.

```powershell
python -m pip wheel --no-deps --wheel-dir .\dist .\modules\terminal_launcher .\modules\agent_continuity
python -m pip install .\dist\terminal_launcher-0.2.0-py3-none-any.whl .\dist\agent_continuity-2.3.0-py3-none-any.whl
```

The two packages remain independently installable: `terminal-launcher` has no dependency on `agent-continuity`. Running source directly without installing the dispatcher remains available for non-terminal commands, but `llmd open` requires the declared dependency:

```powershell
python -m agent_continuity --help
```

## Windows Terminal acceptance (manual desktop check)

The automated suite captures `wt.exe` arguments and does not verify real pane geometry or child startup. When a Windows desktop session with Windows Terminal is available, run `llmd open` with harmless Python processes and explicitly authorize submission with `-a`. Verify two side-by-side panes, the three-pane left-plus-stacked-right arrangement, and the four-pane grid; check composite titles, pane working directories, Unicode/space-containing paths, argument preservation, explicit `--window` targeting, and a missing/invalid target failure. A harmless pane command can be `python.exe -c "import time; print('pane smoke'); time.sleep(8)"`. Use a temporary directory and a dedicated test window; do not use provider sessions for this acceptance check.

## Quick Start (Phase 1 M1)

Legacy `agents` mutating commands default to **dry-run** and require `-a` / `--apply` to persist changes. The `llmd` dispatcher contract is documented separately above; this v2.0 change does not alter the `agents` CLI.

```powershell
# 1. Register a ChatGPT GUI workflow
agents wf add -w procwatch -t "ProcWatch Development" -u "https://chatgpt.com/c/<uuid>" -r "C:\Users\mcarls\src\scripts" -a

# 2. Manually associate a native Codex or AGY session
agents link -w procwatch -p codex -s 019a1234-5678-7000-8000-abcdef012345 -e windows -a

# 3. Look up all sessions and continuity pointers for a workflow
agents find -w procwatch

# 4. Inspect unlinked, candidate, or conflicting associations
agents inbox

# 5. Rebuild the SQLite query index from durable events
agents rebuild -a

# 6. Run diagnostics
agents doctor -v
```

## Storage Layout

By default, state is stored under `~/.agent_continuity` (override with `AGENT_CONTINUITY_HOME`):

```text
~/.agent_continuity/
├── config.json                 # Optional user config & extra spool roots
├── environment.json            # Persistent local environment identity
├── events/
│   └── <environment_id>/       # Atomic per-event JSON files (durable source of truth)
│       └── <ts>_<event_id>.json
└── index.sqlite                # Derived SQLite WAL index (single designated writer)
```

## Native launch options and cwd previews (LLMD-22–24, LLMD-30–31)

Pass provider options only after LLMD's explicit `--` separator. LLMD keeps the tokens as argv elements, retains the selected native session ID, and does not interpret a provider shell string:

```powershell
llmd continue GUI AGENT -C "C:\worktrees\feature" -a -- --sandbox workspace-write --ask-for-approval on-request
llmd start GUI AGENT -p codex --new -a -C "C:\worktrees\feature" -- --sandbox workspace-write --ask-for-approval on-request
llmd switch -g GUI -n AGENT -p agy -a -- --sandbox --model gemini-test --effort high
llmd review -g GUI -n IMPLEMENTER -R REVIEWER -p codex -a -- --sandbox workspace-write
llmd return -g GUI -n IMPLEMENTER -a -- --sandbox workspace-write
```

Managed Codex options include `--sandbox/-s` (`read-only`, `workspace-write`, `danger-full-access`), `--ask-for-approval/-a` (`on-request`, `never`), `--model/-m`, `--profile/-p`, repeatable `--add-dir`, `--enable`, and `--disable`, `-c/--config` for supported settings, plus `--search`, `--no-alt-screen`, `--no-daemon`, `--strict-config`, and `--approve-for-me`. Managed AGY options include `--sandbox`, `--model`, `--effort` (`low`, `medium`, `high`, `xhigh`, `max`), repeatable `--add-dir`, `--agent`, and safe inline JSON `--settings`. Claude Code accepts `--model`, `--effort` (`low`, `medium`, `high`, `xhigh`, `max`), `--permission-mode` (`default`, `manual`, `acceptEdits`, `plan`, `auto`, `dontAsk`), repeatable `--add-dir`, and `--agent`. Claude's `--session-id`, `--resume`, `--continue`, `--fork-session`, print/background/cloud/desktop/worktree/teleport/remote-control modes, settings overrides, and permission-bypass controls are reserved or rejected. LLMD validates managed enums and paths, and summarizes only allowlisted non-sensitive settings. Additional directories must be absolute paths in the selected provider runtime and must exist there.

Other provider flags require explicit authorization before the separator: `llmd continue GUI AGENT -U -a -- --future-native-flag value`. `-U/--allow-native-unknown` permits generic argv forwarding only. It does not permit session selection, execution/bootstrap controls, cwd/worktree changes, remote execution, executable selection, permission bypasses, secrets, or raw prompts/configuration. Unknown permission-related flags are named in the preview with values omitted and remain unverified. LLMD preserves unknown token boundaries exactly, but cannot determine the meaning or safety of a newly added provider option; review the preview and installed provider help before authorizing unfamiliar flags. Native options are invocation-scoped; they are not replayed by `llmd last` or passed between agents/providers automatically. `llmd open` continues to reject provider arguments because one pane request may contain different providers.

### One-time launch prompts (LLMD-59)

`start`, `switch`, `continue`, `review`, `return`, and exact terminal-session `last -r` accept one of `-Q/--clipboard-prompt`, `-F/--prompt-file`, or `-M/--prompt`. These options are mutually exclusive; `-P` remains the profile selector. Prompt files use UTF-8 and preserve line breaks. Dry-run does not read or display prompt content. LLMD does not persist the text, include it in launch history or exit summaries, or replay it after an uncertain launch. Addressed `Agent:` and `To-Agent:` handoffs must match the exact registered target slot.

Codex and Claude command construction passes a one-time prompt through their interactive initial/follow-up argument; live delivery is not qualified here, and uncertain launches never replay it. AGY prompt delivery is rejected because LLMD has no qualified exact-session submission interface for its managed AGY path. Clipboard input uses the host clipboard reader (PowerShell on Windows, `pbpaste` on macOS, or `wl-paste`/`xclip` on Linux). Clipboard and prompt-file contents are limited to 1 MiB.

### Worktree location convention (LLMD-61)

LLMD recursive spool discovery prunes repository-root `.worktree` directories, and the scripts repository ignores `/.worktree/`. LLMD currently restores and records existing worktree identities but does not create Git worktrees. Any future LLMD-owned worktree provisioner must use repository-root `/.worktree/<short-name>`; existing worktrees are preserved in place.

Without `-a`, `continue`, existing-session `start`, `switch`, `review`, and `return` show a launch preview. It includes the executable and structured argv, cwd, environment/runtime, selected native session, and requested permission settings. `verified_effective` is always `null`; LLMD does not claim that requested settings have been enforced. Preview resolves the executable from PATH without launching or version-probing Codex/AGY.

`-C/--cwd` on an existing session is invocation-scoped and must refer to an existing directory in the recorded runtime. Windows-to-WSL paths are checked against the exact recorded distribution using argv-only `wsl.exe --exec test -d`. If the requested path belongs to a different detected Git repository/worktree, preview reports `repository_context_changed`; the session's stored cwd and provenance remain unchanged. For new sessions, the explicitly selected cwd is recorded as the new session's initial provenance.

New-session Codex/AGY bootstrap remains the fixed read-only initialization step and captures the provider's exact session ID before the interactive launch. Claude instead launches interactively with a reserved UUID because its CLI exposes `--session-id`; LLMD resolves the pending launch only after exact transcript evidence appears. Previews do not allocate that identity or launch a provider. Native launch options are applied only to the current invocation. New-session `start` and `switch` resolve one concrete environment for preview and pending-launch state. Historical `continue` and `switch -r` use compare-and-swap against the current activation; `switch -r` also requires `-R` for inactive agents and rejects completed agents. Use `start -d -j` to preview as one JSON document; operational `start` resumes by default when a selected session exists.

## Terminal-scoped launch history (LLMD-27–29)

LLMD reads `TERMINAL_SESSION_ID` and `TERMINAL_SESSION_OWNER_PID` from the environment without changing either variable. A valid terminal-session UUID scopes `llmd last`; a missing or malformed UUID is an error and never falls back to global activity. Owner PID is diagnostic metadata only. Launch history is stored as immutable events with a rebuildable SQLite projection and separate launch IDs for concurrent invocations and terminal panes. Each launcher-created pane receives a distinct internal `pane-run -T` UUID, which continues through post-exit provider switches, agent switches, new-agent creation, and reviewer returns. Pane history therefore cannot overwrite the originating shell's history or another pane's context. A launch still marked `launching` has an unknown outcome and is not evidence that its provider process is alive.

```powershell
llmd last                 # latest launch from this terminal
llmd last -j              # one JSON document
llmd last -N 10           # latest ten launches from this terminal
llmd last -a               # resume the exact recorded native session
llmd last -R -a            # explicitly reactivate an inactive slot, then resume
llmd recent -N 20 -j       # read-only history across terminals
```

`last -a` revalidates the recorded GUI, slot and exact native session before resuming. It does not replay stored cwd, native arguments, or permission overrides; use explicit current-invocation options when needed. Completed slots cannot be resumed, and inactive slots require both `-R` and `-a`. `recent` is read-only. Terminal history captures requested/effective launch cwd separately from recorded native cwd, along with available Git repository/worktree/branch/commit and supported safe settings; unavailable Git metadata remains null.

## Testing

```powershell
cd modules/agent_continuity
python -m pytest
```

## Interactive continuation and runtime status

`llmd continue` opens a flat searchable picker across registered conversations; `llmd continue "Project"` or `-g "Project"` scopes it. Type to filter GUI, agent, provider, or native session ID; use arrows and Enter to choose, Backspace to edit, and Esc to cancel. Active agents sort first by recent activity. Inactive agents remain visible and require confirmation to reactivate. The confirmation applies only when execution is enabled; `-d` keeps the operation preview-only. Completed agents are hidden unless `-A` is supplied, and the picker will not resume completed agents. A missing session association never starts a provider.

Runtime status is independent of registry lifecycle. `IN USE` means the same-runtime LLMD session lock is currently held; `PENDING` marks an unresolved launch whose owning environment is established; `NOT OBSERVED` means that lock was not observed; `UNKNOWN` means runtime identity is unavailable or belongs to a different environment. Local ownership requires matching persisted environment ID, runtime kind, hostname, and (for WSL) distribution metadata. A missing or mismatched identity is `UNKNOWN`; identical cloned environment metadata and hostnames cannot be distinguished with the available identity fields. Windows and WSL use separate local lock visibility, so status cannot establish activity across those boundaries. Managed `continue` atomically acquires the session lock before launching and rejects contention. Use `-d` for preview. The lock is held while the provider subprocess runs and released on exit or spawn failure. `attach`, historical `continue`, and reuse `switch` refuse to change selection while the current session's managed lock is held; selecting the already-current session remains a no-op. Process-exit observations retain the session identity that the child ran, even if selection later changes.

## Starting and selecting historical sessions

A start for an existing selected session resumes that exact session by default; pass `-d` for a preview. A slot without a selected session is initialized by `start` itself, creating missing local GUI/agent records atomically. Add `-N` when an existing selected session should be replaced by a new native conversation; prior activations remain in history. `-N -a` remains accepted. Pending launches, ambiguous bootstrap outcomes, conflicting associations, inaccessible environments, and unresolved identities block automatic creation.

```powershell
llmd start "Project" "Agent" -p codex -d                 # explicit preview
llmd start "Project" "Agent" -p codex --new -a          # explicit new conversation
llmd continue "Project" "Agent" -p agy                  # resume historical selection
llmd continue "Project" "Agent" -i "SESSION_ID" -d      # preview exact history selection
llmd switch -g "Project" -n "Agent" -p agy -r           # reuse latest known AGY session
```

`continue -p` selects a historical session only when that provider has one unambiguous session in the agent history. If multiple sessions match, use `-i/--session-id`; unknown IDs are rejected and never trigger a new session. Selecting a historical session records an activation transition, while selecting the already current session remains a no-op. Inactive direct targets require `--reactivate`; completed agents require a separate lifecycle change. Direct `continue` resumes by default; add `-d` to preview. The old `-a` spelling remains valid.

## Operational diagnostics and recovery

`llmd doctor` prints a human-readable summary by default and supports deterministic JSON with `-j`. It inspects SQLite integrity, the existing registry lock, selected sessions, session locks, and pending bootstrap records. It does not create lock files or synchronize event spools; its JSON remains schema version 1. Runtime observations require established local environment ownership. `NOT OBSERVED` does not prove the provider is stopped, and registry-lock contention is not evidence that a lock is stale.

`llmd recover -g GUI -n AGENT` previews metadata-only recovery when a pending launch contains one durably captured exact session ID. Use `-a` to apply. Recovery refuses cross-environment/unknown ownership, lock contention, missing or conflicting captured IDs, and concurrent selection changes. It never launches, resumes, terminates, or retries a provider. When bootstrap succeeded but the ID was not persisted, inspect provider state and attach only a verified ID; automatic retry is unsafe.

## LLMD v2.0 action defaults and startup progress

Operational dispatcher commands execute by default. `start` initializes a first session when none is selected, resumes the selected exact session otherwise, and uses `-N` for explicit replacement. `continue` never creates a session. `review` initializes a missing reviewer or resumes the selected reviewer; `switch -p` executes the requested provider change, and `switch -r` explicitly reuses history. Use `-d/--dry-run` to preview. `-a/--apply` remains accepted for compatibility; combining `-a` and `-d` is an error. Read-only `list`, `history`, `last`, `recent`, `doctor`, and `pending` remain read-only. Use `llmd last -r` (or legacy `llmd last -a`) to resume the exact terminal-scoped session.

The operational command expresses intent: `start` on an empty slot and `review` with an empty reviewer initialize by default; `-N` requests replacement; a provider-named `switch` performs that provider change. `-a` is optional and remains a compatibility alias. Existing-session reactivation, historical identity selection, and destructive operations retain their safeguards. The separate legacy `agents` command remains dry-run by default and is unchanged. External scripts that depended on the previous implicit-preview behavior must add `-d`; only in-repository callers were audited and migrated.

For human-readable provider launches, LLMD writes flushed monotonic startup progress to stderr and emits periodic elapsed updates only during blocking initialization/bootstrap, about every four seconds. Reporting stops before interactive provider handoff so it cannot write into a long-running provider TUI. JSON stdout is not used for progress, and progress messages do not print provider argv. Stages include registry/environment discovery, launch reservation, bootstrap, exact-ID capture/persistence, and interactive handoff. The fixed read-only Codex/AGY bootstrap remains because installed help did not establish a safe exact-ID creation path without an initialization turn; no newest-session-file heuristic is used. Provider startup acceleration is unverified. Timing goals (first progress near 250 ms and subsecond dispatcher-only overhead) are targets, not guarantees; dispatcher-only measurements are recorded in the feature plan status.

At wide widths, listing name/session columns are allocated from the data in that result. At 120 columns the renderer preserves full 36-character UUIDs when they fit and uses additional stacked rows for longer identities rather than clipping timestamps or session IDs unnecessarily. Terminal widths are measured in display cells; JSON remains unchanged.

```powershell
llmd doctor -g "LLM-Dispatcher" -n "shared-python-integration" -j
llmd recover -g "LLM-Dispatcher" -n "shared-python-integration"
llmd recover -g "LLM-Dispatcher" -n "shared-python-integration" -a
```
