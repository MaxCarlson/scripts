# Local agent bridge: corrected scope

This document replaces the earlier redesign proposal. The user's clarification
defines the scope: the Python script already does what is wanted.

Current storage override: the user requested the skill and everything else inside
`modules/local_agent_bridge/` for now. The resources have been created there;
dotfiles ownership discussed below is a future integration option, not an action
performed in this checkpoint. The module README lists the current paths.

## Intended result

1. Port the authoritative Python script into a simple installable module/CLI,
   preserving its arguments, defaults and behavior.
2. Focus the design work on helping Codex and Antigravity use the connected local
   model effectively: shared skill, global instructions, worker prompt, settings
   and a clear handoff/result workflow.

“agy/gemini” means Antigravity in this conversation. Standalone Gemini CLI is
outside scope. The PowerShell bridge is defunct; no feature parity is needed.

## Minimal module boundary

Proposed files under `modules/local_agent_bridge/`:

- `pyproject.toml`: initial version 1.0.0, Python >=3.11, no new runtime dependencies,
  console entry point `local-agent-bridge = local_agent_bridge.cli:main`.
- `local_agent_bridge/__init__.py`: matching version.
- `local_agent_bridge/cli.py`: existing Python script, with only packaging and
  entry-point adjustments needed to expose its existing main().
- `local_agent_bridge/__main__.py`: module invocation.
- `README.md`, `AGENTS.md`, and focused compatibility tests.

Keep the implementation in one file initially. No speculative decomposition.
The old Python path can become a thin compatibility launcher once the installed
CLI works. Both entry points use the same parser and implementation.

Preserve current flags, aliases, defaults, ls behavior, configuration destinations,
load/unload behavior, named model operations and server lifecycle. A module port
does not introduce new commands or change existing side effects.
Update the help registry for CLI discovery.

No new configure/serve/doctor command hierarchy, preview/apply system, transactional
configuration engine, mandatory analysis-only worker, or permission framework.
Findings from code inspection are optional follow-up issues, not migration tasks.
If a problem actually prevents the port, document that narrow issue separately.

## Agent integration is the main deliverable

See [interaction-guide.md](interaction-guide.md) for concrete draft instructions,
skill workflow, local-worker prompt, settings recommendations and validation.

Ownership:

- scripts owns the bridge package and its documentation.
- dotfiles owns shared agent resources and their existing installer wiring.
- One `local-agent-handoff` skill serves Codex and agy.
- Codex global instruction source: `symlinked/llms/codex/AGENTS.md`.
- Antigravity global instruction source: `symlinked/llms/gemini/GEMINI.md`;
  “gemini” in this dotfiles path does not add standalone Gemini CLI to scope.
- Existing scripts root AGENTS.md needs no bridge-specific workflow.
- A local-worker prompt should be maintained once in dotfiles alongside the shared
  skill's resources, with deployment documented for OpenCode. Do not duplicate it
  into two competing canonical copies in the package and skill.

Prompt ownership is deliberately simplified from the previous proposal: this is
an agent resource, while the bridge remains a loader/configuration tool.
The module README links the shared resource and explains how to use it.

## Current boundaries

No scripts have been changed. The user's “don't change the scripts yet” and “no
delegation right now” remain active. Documentation work does not invoke the worker,
change live settings or install shared resources. No commits/pushes/merges authorized.

The current [plan.md](plan.md) replaces the seven-task redesign. Its first part is
a small packaging change; its second part is the substantive agent-integration work.
