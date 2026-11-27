# LLMD CLI — Current Behavior and Source Reference

**Evidence baseline:** LLMD v1.7.1 integrated main at `ae04cbe08acaef235c9d0b1264fa3fdc3c2a4a57`; the v2.0.0 section below describes the active feature branch.
**Document type:** source reference and migration notes. Windows terminal and provider behavior is not claimed unless separately qualified in the active plan status.

## LLMD v2.1.1 — Claude Code native provider corrections

`claude` is a third canonical provider available through the shared dispatcher: registration, attachment, exact continuation, start, three-provider switching, reviewer/return cycle, open panes, registry listing and activation history. A new Claude session receives one durable LLMD-reserved UUID using interactive `claude --session-id <UUID>`; LLMD does not create a separate model bootstrap turn. The association is committed only after one unique, nonempty exact transcript is successfully decoded and validated. Malformed, inaccessible, contradictory or duplicate transcript evidence is unavailable; confirmed absence means the store scan completed without that exact transcript. A clean exit without a transcript stays pending with its UUID for later recovery. Every pending UUID has one durable spawn claim, so repeating an interrupted launch cannot spawn a competing session. Exact resume requires a UUID and uses `claude --resume <UUID>`, not `--continue`. Broad transcript-history discovery is unsupported because Claude's transcript record schema is internal. Transcript presence is not a live provider resume guarantee.

Managed Claude arguments are `--model`, `--effort`, `--permission-mode`, `--add-dir`, and `--agent`. LLMD blocks identity, fork, print/background/cloud/desktop/worktree/teleport/remote-control, alternate-config, and permission-bypass controls, including short aliases. Unknown safe-looking arguments require `--allow-native-unknown`; this does not override managed conflict checks. Previews do not allocate UUIDs. Authentication stays with Claude Code; LLMD-56 does not install hooks or require `local_agent_bridge`.

## LLMD v2.0.0 action-default contract

## LLMD v2.0.0 action-default contract (active implementation)

`start`, `continue`, `switch`, `open`, `review`, `return`, `attach`, GUI/slot creation, and ordinary slot lifecycle commands execute by default. `start GUI AGENT -p PROVIDER` resumes the selected exact session or creates missing local records and initializes a first session when no session is selected. `continue` only resumes an exact existing identity. `review` resumes a selected reviewer or initializes its first session; `switch -p PROVIDER` performs the requested provider change, while `switch -r` explicitly reuses a prior session. Add `-d/--dry-run` to request a preview. `-a/--apply` remains an accepted compatibility alias; `-a` and `-d` together are rejected before registry access. Read-only `list`, `history`, `last`, `recent`, `doctor`, and `pending` remain read-only. `last -r/--resume` explicitly resumes the exact terminal-scoped launch; `last -a` remains compatible.

The command itself expresses ordinary initialization intent. `-N/--new` explicitly replaces a selected session and preserves its prior activation; `-N -a` remains valid. On an existing selected session, interactive `start -N` retains its replacement confirmation. An empty start/reviewer slot may initialize without `-N` or `-a`. `switch` no longer requires `-a` to perform the explicitly requested provider change. Pending launches, ambiguous bootstrap outcomes, conflicting associations, inaccessible environments, and unresolved identities are errors, not empty-slot signals. Inactive-session reactivation, historical identity selection, generic native-option authorization, ambiguous-operation confirmation, and destructive/recovery safeguards remain in force. Provider arguments after `--` are preserved as argv. The separate legacy `agents` CLI keeps its existing dry-run-by-default contract.

## 1. Scope and architecture

`llmd` (the `agent_continuity` dispatcher CLI) tracks locally named GUI aliases, agent slots, lifecycle states, native Codex/Antigravity sessions, pending launches, and ordered activation history. A GUI alias is a *local registry identity* for a ChatGPT conversation; it does not create or rename the ChatGPT conversation itself.

Core source:
- `modules/agent_continuity/agent_continuity/dispatcher_cli.py` — argparse commands, launch path, exit prompt, list renderer, diagnostics.
- `modules/agent_continuity/agent_continuity/dispatcher.py` — registration, slot state, session activation, pending launch orchestration.
- `modules/agent_continuity/agent_continuity/interactive.py` — keyboard selector and agent action menus.
- `modules/agent_continuity/agent_continuity/materializer.py` and `schema.py` — event-backed SQLite state, timestamps, activation history.
- `modules/agent_continuity/tests/` — dispatcher CLI, v2, operations, interactive/terminal integration tests.
- `modules/agent_continuity/README.md` — user-facing reference; some examples remain from the legacy forms.

The durable event spool and rebuildable SQLite index contain GUI records, agent-slot records, pending launches, session activations, and process observations. The slot's selected native session comes from its latest activation. Lifecycle state (`active`, `inactive`, `completed`) is **not** live process status.

## 2. Commands present today

| Command | Primary function | Current notable arguments and behavior |
|---|---|---|
| `llmd` | Interactive selector on a TTY; help/error for noninteractive invocation | GUI → agent → session action; Ctrl+N New, Ctrl+A Open All |
| `gui add` | Register local GUI alias | `-n/--name`, executes by default; `-d` previews; `-a` compatibility alias |
| `gui rename` | Rename alias and retain stable identity | `-g/--gui`, `-n/--name`, execute by default; `-d` previews |
| `gui list` | List active local GUI aliases | `-H/--home`, `-j/--json` |
| `slot create` | Create slot under an existing GUI alias | `-g`, `-n/--agent-name`, execute by default; `-d` previews |
| `slot disable/enable/complete` | Change slot lifecycle | `-g`, `-n`; execute by default; `-d` previews; does not erase history |
| `list [GUI]` | Show aliases/agents | `-g`, `-l/--limit`, `-A/--all`, `-c/--color auto\|always\|never` |
| `last` | Show terminal-scoped launch history | Read-only unless `-r/--resume` (or compatibility `-a`) is supplied; `-N` lists history |
| `register [GUI] [AGENT]` | Register identities and optionally associate an existing exact native session | `-g`, `-n`, `-p/--provider`, `-i/--session-id`, `-d/--dry-run`, `-s/--select`; **applies by default** |
| `history` | Show all activation entries for a slot | `-g`, `-n`; oldest-first output with provider, native ID, environment, provenance |
| `pending` | Show unresolved launches | Optional `-g`; prints captured ID when available |
| `doctor` | Read-only registry/runtime diagnostics | Optional `-g`, `-n`, `-j` |
| `recover` | Metadata-only recovery of a safely captured pending ID | `-g`, `-n`, `-a` |
| `attach` | Bind a verified existing native session ID | `-g`, `-n`, `-p`, `-i`, optional `-e/--environment`, `-C/--cwd`, `-L/--launch-id`; execute by default, `-d` previews |
| `start [GUI] [AGENT]` | Resume the selected exact session or initialize the first session | `-g`, `-n`, `-p`, `-C`, `-e`, `-d`, `-N/--new` for replacement; `-a` is optional |
| `switch` | Execute the requested provider switch or explicitly reuse an exact historical session | `-g`, `-n`, `-p`, `-r/--reuse-previous`; `-a` is optional; `-d` previews |
| `continue [GUI] [AGENT]` | Resume selected/historical session | `-g`, `-n`, `-p`, `-i`, `-R/--reactivate`, `-A/--all` in picker, `-C/--cwd`; `-d` previews |
| `open` | Submit multi-pane launch plan to Windows Terminal | `-g`, `-k/--panes-per-tab` 1–4, `-t/--terminal`, `-w/--window`; `-d` previews |
| `review` / `return` | Transition between original and reviewer slots | Review resumes or initializes the reviewer by default; `-N` replaces its selected session; `-d` previews |
| `pane-run` | Internal terminal-launcher wrapper | `-s/--slot-id`, `-L/--launch-id`; unintentionally visible as `==SUPPRESS==` in global help |

Global options include `-h/--help`, `-H/--home`, `-j/--json`, and `-V/--version`. Many subcommands duplicate `-H` and `-j` for subcommand placement. Provider values are `codex`, `agy`, and `claude`.

## 3. Start-path lifecycle and authorization

Equivalent positional and named `start` forms use one lifecycle contract. With an existing selected session, `start` resumes that exact identity by default; `-d` previews. For an empty slot or missing local GUI/slot, `start` creates the local records and reserves the first native session by default under the existing lock. `-N/--new` explicitly requests replacement when a selected session exists; `-N -a` remains compatible. Missing or ambiguous session identity, pending launch, provider conflict, inaccessible environment, inactive/completed lifecycle, or CAS failure must abort before creating a new launch. `continue` never initializes. Use `switch -p` to request a provider change explicitly.

## 4. Session lifecycle, launch and recovery

Starting a new Codex or AGY session first creates a durable pending launch and runs one fixed initialization-only provider invocation. It captures the exact native conversation ID from that invocation's structured output, associates it with the slot, and then opens the interactive provider. This can incur one initialization model turn. Claude instead reserves one UUID, records a one-shot launch claim, and starts interactively with `--session-id`; it does not use a bootstrap model turn.

If the bootstrap fails, times out, returns ambiguous IDs, or cannot persist the association, LLMD retains recoverable pending state and **does not automatically retry** a potentially billable launch. Recovery is through `pending`, `doctor`, `recover`, or verified `attach`, as appropriate. Existing sessions have a same-runtime per-session lock; lock absence is not proof that another environment is idle.

On **normal provider exit code 0**, the `_run_pane` wrapper prints:
```text
Agent has exited.
[1] Keep active (default)
[2] Mark completed
[3] Mark inactive
[4] Switch provider
[5] Switch to existing agent
[6] Create a new agent
```

Options 2 and 3 change only the departing slot's lifecycle; 4 opens a provider picker for Codex, AGY, or Claude (defaulting to the prior opposite-provider behavior), 5 resumes an inactive exact session in the current GUI (prioritizing the linked original during reviewer return), and 6 creates a separately confirmed new slot/session. Destinations are validated before the departing slot is deactivated. Option 6 requires explicit confirmation; option 5 never creates a native session. A nonzero exit reports its code and does not present this normal-exit menu. Resolved exit paths show one fresh scoped listing.

New provider bootstrap persists pending state before initialization, captures the exact ID from the provider process output, and resumes only that ID. Failure, timeout, ambiguous capture, or interruption remains recoverable and is never retried automatically. Read-only initialization is still one model turn for a newly created session.

## 5. Listing and display details

- Global and GUI-scoped `list` apply the same active/inactive/completed filtering. Completed slots are included with `-A`; configured limits and omitted counts are reported consistently.
- `-N/--history-count` expands each shown agent with its newest activation records. JSON keeps its prior schema unless history expansion is requested.
- Listings show local GUI/agent activity times, semantic providers, lifecycle, independent runtime observation, and exact or explicitly unresolved session identities.
- The renderer groups agent rows under GUI headings, separates groups, adapts tables to available display-cell width, and stacks rows when a table would needlessly truncate an identity or timestamp. JSON remains ANSI-free.
- `active`/`inactive`/`completed` describe registry lifecycle; `IN USE`, `NOT OBSERVED`, `PENDING`, and `UNKNOWN` are distinct runtime observations and do not prove provider process state across Windows/WSL boundaries.

The materialized schema stores `created_at`, `updated_at` and `last_activity_at` for GUI and slot records, plus activation `activated_at` values. `last_activity_at` can reflect registration/session activity or process observations; it is not guaranteed to be the timestamp of the last model response. Null values need a visible missing-data marker.

## 6. Compatibility and remaining constraints

The earlier discrepancies are resolved: positional/named `start` share creation/authorization rules, internal `pane-run` is hidden from ordinary help, list lifecycle/history behavior is consistent, and post-exit actions validate destinations before transitions. `register` remains apply-by-default for compatibility. LLMD-47 makes operational dispatcher commands execute by default, with `-d` preview and `-a` compatibility alias; the distinct legacy `agents` CLI remains dry-run by default.

**Superseded v1.7.1 baseline note:** At that release, `start`/`review` required `-N -a` for new conversations and provider switches required `-a`. LLMD-47 changes the contract below: operational commands execute by default, `-d` previews, and `-a` remains a compatibility alias. `-N` still explicitly requests replacement when a selected session exists, and `-N -a` remains valid. `switch -r` and ordinary resume operations reuse exact known sessions. Inactive reactivation and historical identity choices retain their explicit safeguards. Unknown provider arguments still require `-U/--allow-native-unknown`; that authorization does not certify unknown option semantics.

## 7. Evidence and limitations

The v1.7.1 baseline was verified from source and the committed release worktree. LLMD v2.0.0 status and executed validation are recorded in `STATUS.md`; provider help inspection was help-only, tests used guarded fakes, and installation smoke used a disposable target. The plan and checklist remain the normative acceptance record.

## Implementation update (feature branch)

The original baseline notes above remain historical. The authorized implementation adds `review`/`return`, `list -N/--history-count`, and exit-menu options 5/6. Option 4 continues to switch providers within the same slot. `start` initializes an empty slot by default; `-N` explicitly requests replacement, and `-N -a` remains a compatible spelling. Review and switch relationships are durable events with rebuildable projections; all automated provider bootstrap tests use fake child processes.

### Native launch customization (LLMD-22–24, LLMD-30–31)

Provider arguments are parsed as structured argv only after a literal `--` on `start`, `continue`, `switch`, `review`, and `return`. Installed `codex resume --help` and `agy --help` were inspected without starting a session or model turn. Managed Codex flags cover sandbox, approval, model, profile, additional directories, feature toggles, supported config settings, search, inline terminal mode, strict config, and automatic review. Managed AGY flags cover sandbox, model, effort, additional directories, agent profile, and safe inline JSON settings. Value validation and previews are provider-specific; extra directories must exist in the target runtime.

Unmanaged flags require `-U/--allow-native-unknown` before `--`. This only authorizes generic argv forwarding; LLMD still rejects recognized session identity, bootstrap/print/exec, execution mode, executable/runtime selection, remote launch, cwd/worktree controls, permission bypasses and sensitive/raw data. Unknown permission-affecting flags are shown by name in previews with values omitted. LLMD preserves the structured argv boundaries, but cannot determine the semantics or safety of unfamiliar provider flags; inspect the installed provider help and preview before authorizing them. `open`/terminal-pane launches reject provider passthrough for mixed-provider safety. Options 4–6 validate options for their selected destination before changing lifecycle state.

`-C/--cwd` on existing sessions applies to one invocation and does not update stored session provenance. Local directories and additional directories must be absolute and exist in the selected provider runtime. Windows-to-WSL paths are checked against the session's recorded distribution with argv-only `wsl.exe --exec test -d`. Preview resolves PATH without invoking/version-probing a provider and shows argv, cwd, environment, session, requested permissions, and a null/unverified effective-permissions field. New-session bootstrap remains fixed and read-only; user overrides are forwarded only on resuming the exact captured ID.

### Terminal-scoped launch history (LLMD-27–29)

`llmd last` reads only the history keyed by the valid UUID in `TERMINAL_SESSION_ID`; absent or malformed IDs produce an error, never a global fallback. `TERMINAL_SESSION_OWNER_PID` is read-only diagnostic metadata. Launcher-created panes receive distinct internal UUIDs through `pane-run -T` instead of inheriting the profile-owned terminal key; that same context follows options 4–6, reviewer returns, and repeated transitions. `last -N COUNT` displays terminal-local history; `last -a` resumes the exact recorded provider/environment/native session after current-state validation, while inactive slots require `last -R -a`. Resume does not replay stored cwd or native settings; explicit `-C` and options after `--` apply only to that resume and are validated/previewed before activation. A `launching` record has an unknown outcome after hard termination, not a verified running process. `llmd recent [-N COUNT] [-j]` is cross-terminal and read-only. History uses immutable dispatcher events and a rebuildable SQLite projection.

LLMD-25 persistent launch profiles remain the next planned batch; LLMD-26 native lock diagnostics remain deferred.

### v1.5.2 correctness follow-up

New-session `start` and `switch` resolve one concrete environment for preview and launch reservation; an omitted `-e` keeps the selected slot's environment when creating a new provider session. Post-exit options 4–6 do not automatically carry the departing session's `-C` or native argv. The destination's recorded environment/cwd and provider defaults are used unless compatible overrides are explicitly authorized in the prompt; incompatible options can proceed with destination defaults or cancel. Option 6 uses its separately chosen new working directory. `continue` picker validates cwd before reactivation, and historical `continue`/`switch -r` use the captured current activation as a compare-and-swap guard. `switch -r` requires `-R` to reactivate inactive slots and rejects completed slots. Existing-session `start -j` emits a single JSON document.

### LLMD-39 semantic presentation update

LLMD 1.7.1 centralizes semantic styles in `terminal_format.py`. GUI headings and agent names are bold and distinct; Codex and AGY have separate colors; timestamps, IDs, labels, lifecycle, runtime and launch outcome have their own semantics. `active` remains a lifecycle state; `IN USE`/`NOT OBSERVED` remain runtime observations; an unverified or interrupted launch is not reported as a verified running process.

`list`, scoped list, selectors, continue picker, post-exit menu, history, `last`/`recent`, doctor, launch previews and related diagnostics use semantic presentation. Tables use terminal-cell widths and switch to stacked rows when needed. Empty groups, pending identities, selected history, and known unresolved IDs are labeled. Full session IDs are shown when the terminal can fit them.

`-c/--color auto|always|never` is available on supported subcommands and propagates into the interactive menu and its nested selectors and diagnostics. `auto` requires an interactive terminal and is disabled by `TERM=dumb`; on Windows LLMD temporarily enables VT processing for the actual output console and restores its prior mode when dispatch completes. This does not alter persistent terminal settings. `NO_COLOR` disables ANSI regardless of mode. JSON data and schema are unchanged and contain no escape sequences. Unit capture verifies ANSI sequences and cell widths, while actual PowerShell/Windows Terminal rendering is reported as a separate smoke check.

### LLMD v2.0.0 — action defaults, startup timing and responsive columns

Operational commands execute by default. `start` initializes an empty slot or resumes its selected exact session; `-N` explicitly requests replacement. `continue` only resumes exact existing sessions. `review` initializes a missing reviewer or resumes its selected session. `switch -p` performs the requested provider change, while `switch -r` explicitly reuses history. Use `-d/--dry-run` for a preview; `-a/--apply` remains a compatibility alias and conflicts with `-d`. Read-only commands stay read-only. `last -r/--resume` and legacy `last -a` resume the exact terminal-scoped identity. Inactive/completed lifecycle protections and unresolved/pending launch guards are unchanged.

Human-readable startup progress is flushed to stderr before registry processing and periodically only during blocking initialization/bootstrap, approximately every four seconds. Periodic reporting stops at interactive provider handoff; it is not injected during provider TUI lifetime. Stages use a monotonic clock; provider argv and sensitive values are not included. JSON stdout remains free of progress. The fixed read-only Codex/AGY bootstrap remains because inspected CLI help did not establish a safe exact-ID creation method without an initialization turn. A two-sample local measurement with mocked provider handoff found existing-session `start` median dispatcher time reduced from 29.39 ms (v1.7.1) to 15.87 ms (v2.0.0), with first progress at median 0.02 ms; these figures measure dispatcher work only. Provider startup acceleration remains unverified.

Listing column widths are allocated from the data in each result. A real 36-character UUID remains complete at 120 columns when layout constraints allow; longer identities trigger stacked rows before timestamps/session IDs are clipped unnecessarily. External scripts that relied on implicit preview behavior must add `-d` to their LLMD operational invocations. Repository search found and migrated preview-dependent examples/tests; callers in other repositories were not edited or verified.
