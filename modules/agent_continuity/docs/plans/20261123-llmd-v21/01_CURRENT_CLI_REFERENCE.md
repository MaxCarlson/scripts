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
| `continue [GUI] [AGENT]` | Resume selected/historical session | `-g`, `-n`, `-a`, `-p`, `-i`, `-R/--reactivate`, `-A/--all` in picker |
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
