# LLMD CLI — Current Behavior and Source Reference

**Evidence baseline:** `MaxCarlson/scripts` `main` at `7b9f596ac1abebd5be8395962bfb8124379b082e` (2026-11-23).
**Document type:** descriptive, not a proposal. This records code-inspected behavior; it is **not** a claim that these workflows have been rerun on the user's Windows installation.

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
| `gui add` | Register local GUI alias | `-n/--name`, `-a/--apply` |
| `gui rename` | Rename alias and retain stable identity | `-g/--gui`, `-n/--name`, `-a` |
| `gui list` | List active local GUI aliases | `-H/--home`, `-j/--json` |
| `slot create` | Create slot under an existing GUI alias | `-g`, `-n/--agent-name`, `-a` |
| `slot disable/enable/complete` | Change slot lifecycle | `-g`, `-n`, `-a`; does not erase history |
| `list [GUI]` | Show aliases/agents | `-g`, `-l/--limit`, `-A/--all`, `-c/--color auto\|always\|never` |
| `register [GUI] [AGENT]` | Register identities and optionally associate an existing exact native session | `-g`, `-n`, `-p/--provider`, `-i/--session-id`, `-d/--dry-run`, `-s/--select`; **applies by default** |
| `history` | Show all activation entries for a slot | `-g`, `-n`; oldest-first output with provider, native ID, environment, provenance |
| `pending` | Show unresolved launches | Optional `-g`; prints captured ID when available |
| `doctor` | Read-only registry/runtime diagnostics | Optional `-g`, `-n`, `-j` |
| `recover` | Metadata-only recovery of a safely captured pending ID | `-g`, `-n`, `-a` |
| `attach` | Bind a verified existing native session ID | `-g`, `-n`, `-p`, `-i`, optional `-e/--environment`, `-C/--cwd`, `-L/--launch-id`, `-a` |
| `start [GUI] [AGENT]` | Initialize a new native provider session | `-g`, `-n`, `-p`, `-C`, `-e`, `-a`, `-N/--new`; **two distinct parsing paths** |
| `switch` | Start or select a different provider session under an existing slot | `-g`, `-n`, `-p`, `-r/--reuse-previous`, `-C`, `-e`, `-a` |
| `continue [GUI] [AGENT]` | Resume selected/historical session | `-g`, `-n`, `-a`, `-p`, `-i`, `-R/--reactivate`, `-A/--all` in picker, `-C/--cwd` |
| `open` | Submit multi-pane launch plan to Windows Terminal | `-g`, `-k/--panes-per-tab` 1–4, `-t/--terminal`, `-w/--window`, `-a` |
| `pane-run` | Internal terminal-launcher wrapper | `-s/--slot-id`, `-L/--launch-id`; unintentionally visible as `==SUPPRESS==` in global help |

Global options include `-h/--help`, `-H/--home`, `-j/--json`, and `-V/--version`. Many subcommands duplicate `-H` and `-j` for subcommand placement. Provider values are `codex` and `agy`.

## 3. Important start-path discrepancy (confirmed in code and user log)

The implementation defines `positional_start = (command == "start" and gui_pos is not None)`.

**Positional path:**
```powershell
llmd start "GUI" "Agent" -p codex -C "C:\path\repo"        # preview, no registration or provider call
llmd start "GUI" "Agent" -p codex -C "C:\path\repo" -N -a  # register missing GUI + slot, then launch
```

The positional preview uses `dispatcher.register(..., apply=False)`, and application requires both `-N` and `-a`. An already-selected session is refused with a continue/switch hint. Registration creates any missing local GUI and agent-slot records; it does not create a ChatGPT conversation.

**Named-argument path:**
```powershell
llmd start -g "GUI" -n "Agent" -p codex -C "C:\path\repo"
llmd start -g "GUI" -n "Agent" -p codex -C "C:\path\repo" -a
```

This takes the legacy `begin_launch` path without first registering a missing GUI/slot and without the same positional `-N` gate. The user's observed failure was `Error [invalid_input] Agent slot not found: 'pypi-release-review'`. Thus **automatic slot creation is not consistent across equivalent start syntaxes**. A fix must preserve the existing-session and pending-launch safeguards, not merely catch that error and retry.

## 4. Session lifecycle, launch and recovery

Starting a new native session first creates a durable pending launch and runs one fixed initialization-only provider invocation. It captures the exact Codex or AGY native conversation ID from that invocation's structured output, associates it with the slot, and then opens the interactive provider. This can incur one initialization model turn.

If the bootstrap fails, times out, returns ambiguous IDs, or cannot persist the association, LLMD retains recoverable pending state and **does not automatically retry** a potentially billable launch. Recovery is through `pending`, `doctor`, `recover`, or verified `attach`, as appropriate. Existing sessions have a same-runtime per-session lock; lock absence is not proof that another environment is idle.

On **normal provider exit code 0**, the `_run_pane` wrapper currently prints:
```text
Agent has exited.
[1] Keep active (default)
[2] Mark completed
[3] Mark inactive
```

Option 2 or 3 changes only the slot lifecycle state. Option 1/blank leaves it active. A nonzero exit reports the code and leaves the selected session and lifecycle state unchanged; the three-choice menu is not shown. The post-exit path does **not** print a scoped agent list today.

The interactive agent action menu **already** offers "Switch provider — new conversation" and "Switch provider — reuse previous conversation", but post-exit option 4 does not exist.

## 5. Listing and display details

- `list` with no GUI limits to ten GUI headings by default and, per GUI, displays up to ten **active-only** agent slots. `-A` removes the per-GUI agent cap but does not itself override that active-only query in the global path (an asymmetry worth regression-testing).
- `list -g GUI` queries **all** agent states, hides `completed` without `-A`, and defaults to ten shown agents. It sorts active before inactive before completed, rather than strictly by recency.
- The plain text renderer shows GUI headings and agent rows with name, provider, native session ID and lifecycle state. It uses terminal-width clipping but no last-activity timestamp.
- A colorized provider field uses the same ANSI cyan color for both Codex and AGY. An inactive row is dimmed; the lifecycle label `active` is not given its own color.
- Adjacent GUI groups do not get a dedicated visual separator. Long terminal widths can cause very large gaps between session IDs and status.
- The interactive GUI and slot selectors already format `last_activity_at` as local `YYYY-MM-DD HH:MM`, but fixed field widths cause long agent names to shift later columns. The interactive selector does not use the `list` renderer.

The materialized schema stores `created_at`, `updated_at` and `last_activity_at` for GUI and slot records, plus activation `activated_at` values. `last_activity_at` can reflect registration/session activity or process observations; it is not guaranteed to be the timestamp of the last model response. Null values need a visible missing-data marker.

## 6. Outstanding CLI design inconsistencies

1. `start` behaves differently for positional and `-g/-n` inputs.
2. `register` applies by default, unlike most mutating commands.
3. `switch` and `start` can initiate provider operations without a unified plain-language "resume versus new" decision when a slot already selects a session.
4. `pane-run` appears in top-level `-h` as `==SUPPRESS==` rather than being fully omitted.
5. `list` global and scoped modes do not apply `--all`/completed-slot semantics consistently.
6. History exists in the registry and `history` command, but `list` cannot expand the most recent N activations for each agent.
7. Post-exit lifecycle menu and interactive selector are separate code paths; presentation and actions can diverge.
8. `active` is a lifecycle label, not an observed process-running indicator; rendering these as synonyms would be misleading.

## 7. Evidence and limitations

Examined repository source at the pinned baseline, the published README, and user-supplied `llmd list`, `llmd -h`, and `start -g/-n` output. This document does not claim interactive terminal tests were executed against that commit. Proposed future behavior lives in `02_PROPOSED_CHANGES_EVALUATION.md`; implementation sequencing and acceptance are in `00_IMPLEMENTATION_PLAN.md`.

## Implementation update (feature branch)

The original baseline notes above remain historical. The authorized implementation adds `review`/`return`, `list -N/--history-count`, and exit-menu options 5/6. Option 4 continues to switch providers within the same slot. New-session creation through `start` retains the explicit `-N -a` convention. Review and switch relationships are durable events with rebuildable projections; all automated provider bootstrap tests use fake child processes.

### Native launch customization (LLMD-22–24, LLMD-30–31)

Provider arguments are parsed as structured argv only after a literal `--` on `start`, `continue`, `switch`, `review`, and `return`. Installed `codex resume --help` and `agy --help` were inspected without starting a session or model turn. Managed Codex flags cover sandbox, approval, model, profile, additional directories, feature toggles, supported config settings, search, inline terminal mode, strict config, and automatic review. Managed AGY flags cover sandbox, model, effort, additional directories, agent profile, and safe inline JSON settings. Value validation and previews are provider-specific; extra directories must exist in the target runtime.

Unmanaged flags require `-U/--allow-native-unknown` before `--`. This only authorizes generic argv forwarding; LLMD still rejects recognized session identity, bootstrap/print/exec, execution mode, executable/runtime selection, remote launch, cwd/worktree controls, permission bypasses and sensitive/raw data. Unknown permission-affecting flags are shown by name in previews with values omitted. LLMD preserves the structured argv boundaries, but cannot determine the semantics or safety of unfamiliar provider flags; inspect the installed provider help and preview before authorizing them. `open`/terminal-pane launches reject provider passthrough for mixed-provider safety. Options 4–6 validate options for their selected destination before changing lifecycle state.

`-C/--cwd` on existing sessions applies to one invocation and does not update stored session provenance. Local directories and additional directories must be absolute and exist in the selected provider runtime. Windows-to-WSL paths are checked against the session's recorded distribution with argv-only `wsl.exe --exec test -d`. Preview resolves PATH without invoking/version-probing a provider and shows argv, cwd, environment, session, requested permissions, and a null/unverified effective-permissions field. New-session bootstrap remains fixed and read-only; user overrides are forwarded only on resuming the exact captured ID.

### Terminal-scoped launch history (LLMD-27–29)

`llmd last` reads only the history keyed by the valid UUID in `TERMINAL_SESSION_ID`; absent or malformed IDs produce an error, never a global fallback. `TERMINAL_SESSION_OWNER_PID` is read-only diagnostic metadata. Launcher-created panes receive distinct internal UUIDs through `pane-run -T` instead of inheriting the profile-owned terminal key. `last -N COUNT` displays terminal-local history; `last -a` resumes the exact recorded provider/environment/native session after current-state validation, while inactive slots require `last -R -a`. Resume does not replay stored cwd or native settings; explicit `-C` and options after `--` apply only to that resume and are validated/previewed before activation. A `launching` record has an unknown outcome after hard termination, not a verified running process. `llmd recent [-N COUNT] [-j]` is cross-terminal and read-only. History uses immutable dispatcher events and a rebuildable SQLite projection.

LLMD-25 persistent launch profiles remain the next planned batch; LLMD-26 native lock diagnostics remain deferred.

### v1.5.2 correctness follow-up

New-session `start` and `switch` resolve one concrete environment for preview and launch reservation; an omitted `-e` keeps the selected slot's environment when creating a new provider session. Post-exit options 4–6 do not automatically carry the departing session's `-C` or native argv. The destination's recorded environment/cwd and provider defaults are used unless compatible overrides are explicitly authorized in the prompt; incompatible options can proceed with destination defaults or cancel. Option 6 uses its separately chosen new working directory. `continue` picker validates cwd before reactivation, and historical `continue`/`switch -r` use the captured current activation as a compare-and-swap guard. `switch -r` requires `-R` to reactivate inactive slots and rejects completed slots. Existing-session `start -j` emits a single JSON document.
