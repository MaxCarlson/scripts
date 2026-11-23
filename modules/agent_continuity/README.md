# agent_continuity

Local-first GUI–Agent Session Continuity Module with the backward-compatible `agents` CLI and the named-session dispatcher (`llmd` / `llm-dispatcher`) for native OpenAI Codex CLI and Google Antigravity CLI (`agy`) sessions across Windows 11 and WSL2.

See [docs/agent-session-continuity-master-plan.md](./docs/agent-session-continuity-master-plan.md) for the governing Master Implementation Plan (v3.0) and [docs/adr/ADR-001-phase0-architecture-decisions.md](./docs/adr/ADR-001-phase0-architecture-decisions.md) for Phase 0 architecture decisions.

## Listing and registering conversations (LLMD v2)

`llmd list` shows the ten most recently active registered conversations, with up to ten active agents each. `llmd list "Project"` includes active and inactive agents; `-A` also includes completed agents and removes default limits. An explicit `-l` limits results even with `-A`. Output reports omitted counts. Use `-j` for JSON and `-c never` to disable color; JSON contains complete session IDs and truncation metadata. Global JSON uses schema version 1. Scoped JSON retains `action`, `gui`, and `slots` and adds count metadata.

```powershell
llmd list
llmd list "Project" -l 25
llmd list -g "Project" -A -j
llmd register "Project"
llmd register "Project" "Agent" -p codex -i "SESSION_ID"
llmd register -g "Project" -n "Agent" -p agy -i "SESSION_ID" -d
llmd continue "Project" "Agent"  # preview; add -a to resume
```

Registration applies by default and never launches a provider. `-d` previews it. Existing associations are left unchanged; selecting a different session requires `-s/--select` and preserves history. Runtime use is not observed in this release, so verify the session is not in use before changing a selection. Registration uses existing events and a single mutation lock; interrupted operations can be retried. Legacy mutation and launch commands remain dry-run by default. `start` and `continue` also accept GUI and agent positional names without changing their execution defaults.

## Named Agent Dispatcher

`llmd` stores local GUI aliases, named agent slots, lifecycle state, pending launches, and ordered session activations in the same durable event spool and rebuildable SQLite index used by `agents`. A local GUI alias does not create a conversation in ChatGPT.

Install the module to generate both dispatcher executables:

```powershell
llmd
llm-dispatcher --help
```

With an interactive terminal, `llmd` opens the selector. Type to filter names, use Up/Down and Enter to select, Esc to go back, Ctrl+N to register an alias or slot, and Ctrl+A on the agent list to open all selected sessions. Ctrl shortcuts avoid conflicting with incremental text search. Noninteractive no-argument calls print help and do not open a menu.

Mutations and provider launches are dry-run by default. Review the preview, then add `-a` / `--apply`:

```powershell
llmd gui add -n AgentImprovement -a
llmd gui rename -g AgentImprovement -n AgentPerformance -a
llmd slot create -g AgentImprovement -n AgentPerf -a
llmd start -g AgentImprovement -n AgentPerf -p agy -a
llmd attach -g AgentImprovement -n AgentPerf -p agy -i <native-session-id> -a
llmd switch -g AgentImprovement -n AgentPerf -p codex -a
llmd switch -g AgentImprovement -n AgentPerf -p agy -r -a
llmd list -g AgentImprovement
llmd history -g AgentImprovement -n AgentPerf
llmd pending -g AgentImprovement
llmd open -g AgentImprovement -k 2
llmd open -g AgentImprovement -k 2 -a
llmd open -g AgentImprovement -k 4 -a
llmd slot disable -g AgentImprovement -n AgentPerf -a
```

Starting a new provider session uses a bounded two-stage bootstrap. The dispatcher first persists a pending launch, then runs one fixed initialization-only model turn in a read-only/headless provider invocation. Codex's JSONL `thread.started.thread_id` or AGY's JSON `conversation_id` is captured from that specific child process, associated with the intended slot, and immediately resumed in the interactive pane. The user's actual assignment is not sent during bootstrap. A new slot start therefore uses one initialization model turn; continuing or reusing an existing session does not.

If the bootstrap exits unexpectedly or cannot return one successful, unambiguous ID, the dispatcher records that the attempt has already started and will not repeat a potentially billable initialization automatically. `llmd pending` shows any captured ID and recovery detail. If the exact ID is known, resolve the pending launch with `llmd attach -g GUI -n AGENT -p PROVIDER -i SESSION_ID -L LAUNCH_ID -a`; otherwise inspect the native provider's session list and attach only after verifying the intended session. Repeated selections of a previously bound native session remain separate entries in activation history.

`llmd open` creates opaque per-slot `PaneSpec` requests and delegates grouping and execution to the reusable `terminal_launcher` package. Preview is dry-run; pass `-a` to submit it to Windows Terminal. Unresolved or pending session IDs are listed for manual recovery and are never turned into a guessed resume command. The dispatcher does not construct `wt.exe` commands itself.

The pane wrapper prompts after a normal zero exit. Keep active is the default; a nonzero exit or an unexpected wrapper/terminal shutdown leaves the current session and slot state unchanged.

## Current Status

- **M1/M2 continuity foundation:** Integrated and preserved
- **Named dispatcher:** Integrated from `feature/llmd-agent-dispatcher-20261119` at `db8d5779`.
- **Terminal launch integration:** `llmd open` uses `terminal_launcher` for immutable launch planning, previews, layout grouping, and request submission. Real pane geometry remains unverified without a live Windows Terminal smoke test.
- **Session-ID correlation:** New Codex and AGY sessions use per-process structured bootstrap output and explicit resume-by-ID; no global hook installation is required for initial association. Failed or interrupted bootstrap attempts stay recoverable and are not repeated automatically. Manual attachment remains available for interrupted attempts and pre-existing sessions.

## Installation

`agent-continuity` requires the reusable `terminal-launcher` package at runtime. The repository setup workflow reads package metadata and installs local modules in dependency order, so it installs `terminal-launcher` before `agent-continuity`. Windows Terminal itself is not a Python dependency and is only needed when submitting a real Windows Terminal launch.

For a local development install from the repository root, install both source packages in one pip invocation so the local dependency satisfies the requirement without relying on a package index:

```powershell
python -m pip install -e .\modules\terminal_launcher -e ".\modules\agent_continuity[dev]"
```

For wheel deployment, build both packages from the repository root and install both wheels in one invocation. The dependency metadata still requires `terminal-launcher`; installing only the dispatcher wheel without a compatible terminal-launcher distribution will fail clearly.

```powershell
python -m pip wheel --no-deps --wheel-dir .\dist .\modules\terminal_launcher .\modules\agent_continuity
python -m pip install .\dist\terminal_launcher-0.1.1-py3-none-any.whl .\dist\agent_continuity-1.1.0-py3-none-any.whl
```

The two packages remain independently installable: `terminal-launcher` has no dependency on `agent-continuity`. Running source directly without installing the dispatcher remains available for non-terminal commands, but `llmd open` requires the declared dependency:

```powershell
python -m agent_continuity --help
```

## Windows Terminal acceptance (manual desktop check)

The automated suite captures `wt.exe` arguments and does not verify real pane geometry or child startup. When a Windows desktop session with Windows Terminal is available, run `llmd open` with harmless Python processes and explicitly authorize submission with `-a`. Verify two side-by-side panes, the three-pane left-plus-stacked-right arrangement, and the four-pane grid; check composite titles, pane working directories, Unicode/space-containing paths, argument preservation, explicit `--window` targeting, and a missing/invalid target failure. A harmless pane command can be `python.exe -c "import time; print('pane smoke'); time.sleep(8)"`. Use a temporary directory and a dedicated test window; do not use provider sessions for this acceptance check.

## Quick Start (Phase 1 M1)

All mutating commands default to **dry-run** and require `-a` / `--apply` to persist changes.

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

## Testing

```powershell
cd modules/agent_continuity
python -m pytest
```
