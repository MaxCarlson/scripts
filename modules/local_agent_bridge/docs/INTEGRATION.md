# Integration

Use `local_agent setup plan` and `setup apply`; see [README](../README.md).
Generic and local sources remain separate as described in [COMPOSITION.md](COMPOSITION.md).
For current dotfiles links and exact adoption examples, see [MIGRATION.md](MIGRATION.md).

## Installed contributions

| Client | Resource |
| --- | --- |
| Codex | Effective global AGENTS.md (including CODEX_HOME/active override detection) |
| Codex | User skill in ~/.agents/skills, or explicitly adopted existing legacy custom skill |
| Codex | Missing settings defaults and the opencode_worker MCP contribution |
| agy | One effective global AGENTS.md/GEMINI.md |
| agy | Skills in ~/.gemini/antigravity-cli/skills |
| agy | Missing Gemini settings defaults, CLI/global MCP entries and CLI bridge permission |
| OpenCode | Separate agents/local-worker.md and agents/local-reviewer.md |

The current adapters target Codex and Antigravity CLI. Multiple active agy global
instruction files, competing role names, duplicate skill discovery or unmanaged
resource collisions require reconciliation. Installer metadata alone does not
prove that a client discovered the skill or selected the actual local model.

The worker roles share one canonical prompt. Both deny recursive task/skill
handoff; the reviewer also denies built-in edits and shell execution. Inspect
other MCP/custom tools before treating that as an inspection-only environment.
These rules are tool restrictions, not an operating-system sandbox.

The configured lmstudio alias is used when known. No placeholder alias or cloud
fallback is installed when it is missing; run the existing model workflow first.
The global OpenCode model/provider configuration is preserved by resource setup.
Existing project config may override global settings and must be checked at runtime.

## Runtime lifecycle

`local_agent run` keeps the existing foreground model/server workflow. Keep the
server running while jobs execute. Prefer opencode_fire and bounded observation
by job ID; a timeout does not cancel inference. Cancellation affects the whole
OpenCode session, so keep one active turn per session. The shared skill contains
complete task/result/recovery procedures.

Refresh client connections after configuration changes and validate discovery in
fresh Codex and agy sessions. The installer does not perform model calls. Follow
[VALIDATION.md](VALIDATION.md) for the still-pending actual handoff scenarios.
