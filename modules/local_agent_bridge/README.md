# Local agent bridge

Manage the LM Studio model and OpenCode MCP bridge used by Codex and Antigravity
(`agy`). The module preserves the existing loader workflow and command options.

## Run

After installing the module through the scripts repository setup:

```powershell
local-agent-bridge --help
local-agent-bridge ls
```

From this module's directory without installing:

```powershell
python -m local_agent_bridge --help
python -m local_agent_bridge ls
```

The implementation is in `local_agent_bridge/cli.py`. The old
`pyscripts/loadlmscodexbridge.py` path was moved into this package.

## Agent resources

These resources are authored here for later integration. They are not installed
or activated by the module package.

| Resource | Purpose |
| --- | --- |
| [Shared skill](skills/local-agent-handoff/SKILL.md) | Task selection, handoff, continuation and review for either coordinator |
| [Codex metadata](skills/local-agent-handoff/agents/openai.yaml) | Automatic skill discovery policy and existing MCP dependency |
| [Worker prompt](skills/local-agent-handoff/resources/local-worker.md) | Canonical behavior prompt for the local model |
| [Worker roles](integrations/opencode-agent.example.json) | OpenCode worker and reviewer examples with recursion guards |
| [Result schema](skills/local-agent-handoff/resources/result.schema.json) | Optional structured final result contract |
| [Coordinator snippet](instructions/coordinator.snippet.md) | Shared policy for a coordinator's effective instructions |
| [Integration notes](docs/INTEGRATION.md) | Future skill links, prompt selection and client verification |
| [Model settings](docs/SETTINGS.md) | Existing baseline, supported options and evaluation guidance |
| [Validation scenarios](docs/VALIDATION.md) | Offline checks and deferred behavioral checks |
| [Research decisions](docs/RESEARCH.md) | Primary sources and accepted/deferred integration methods |
| [Current plan](docs/plans/20261017-1540_coordinator-worker-integration/plan.md) | Resource implementation, later activation, and optional plugins/hooks |

The skill prefers asynchronous dispatch and bounded observation by job ID. The
coordinator selects the actual loaded LM Studio alias and a configured worker role;
no automatic cloud fallback is part of the workflow. The reviewer example blocks
built-in edits and shell execution; it is not an operating-system sandbox.

Package installation exposes the CLI only. Resources currently remain in this
checkout and need explicit linking/configuration, or future plugin packaging, to
be discovered by the clients. See the integration notes before activating them.

See [AGENTS.md](AGENTS.md) for module-specific working guidance.
