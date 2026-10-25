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
Existing project config may override global settings. Check the selected project
with `local-agent model verify <alias> -d <project-directory> -j`; this compares
static metadata with OpenCode's effective provider/model API response when online.
It separately reports LM Studio's loaded context from `lms ps`, or `null` when the
CLI cannot establish it. The command is read-only and does not start services.

## Runtime lifecycle

`local_agent run` keeps the existing foreground model/server workflow. Explicit
context changes need an output limit; the tested Q4_K_M `qwen38_23GB` profile uses
8,192 output tokens. The opt-in 65,536 context command and its hardware caveats are
in [README](../README.md) and [SETTINGS](SETTINGS.md). Conflicting existing
metadata requires an explicit correction flag.

Keep the server running while jobs execute. Record `jobId`, `sessionId`, initiating
`messageId`, directory, provider/model, and explicit agent on each `opencode_fire`,
including same-session follow-ups. If a job ID is unknown after compaction, inspect
the original session and directory, latest messages/parts, permissions/questions,
and initiating message before deciding active/completed/failed/uncertain. A session
completion does not establish the initiating turn's completion without correlation.
A timeout stops observation, not the turn; do not duplicate the job or cancel an
active session just because its handle is lost. The coordinator skill owns this
manual fallback because job polling lives in the pinned external `opencode-mcp`
package.

Before accepting worker edits, compare actual authorized paths and a baseline diff
or hashes, then run focused tests independently. Treat `session.summary.files = 0`
as unreliable, and do not attribute a diff without exclusive workspace/baseline
evidence. Keep one active turn per session.

Refresh client connections after configuration changes and validate discovery in
fresh Codex and agy sessions. The installer does not perform model calls. Follow
[VALIDATION.md](VALIDATION.md) for the still-pending actual handoff scenarios.
