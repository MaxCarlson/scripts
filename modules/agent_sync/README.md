# agent_sync

`agent_sync` coordinates work between primary LLM CLIs and delegated worker LLMs without creating a second orchestration stack.

It is the repo-local layer for:

- sequential handoffs between Claude, Codex, Gemini, Copilot, and local workers
- bounded delegation from a primary agent to another LLM CLI
- high-stakes review and verification workflows
- local LM Studio work through the existing `llm_local` module when available
- audit logging of all delegated prompts and worker outputs

It is intentionally separate from `ai-orchestrator`: `ai-orchestrator` is the service-backed Postgres/task-queue/WebUI system, while `agent_sync` is the lightweight local CLI that an active coding agent can call inside a repository.

## Install

From `scripts/modules/agent_sync`:

~~~bash
python -m pip install -e .
~~~

## Basic commands

~~~bash
agent-sync init -r /path/to/repo
~~~

~~~bash
agent-sync workers -r /path/to/repo -a
~~~

~~~bash
agent-sync delegate -r /path/to/repo -E -k summarize -w local-lmstudio -f handoff.md -l standard
~~~

~~~bash
agent-sync review -r /path/to/repo -E -w gemini -f plan.md
~~~

~~~bash
agent-sync verify -r /path/to/repo -E -w claude -f implementation-notes.md
~~~

## Safety default

External workers are never invoked unless `-E` / `--allow-external` is passed. Without it, commands render the prompt and planned worker but exit before calling any CLI or local model.

## Worker config

`agent-sync init` writes:

~~~text
.agent_sync/workers.json
~~~

Command-backed workers use template tokens:

- `{prompt}`: prompt text as one command argument
- `{prompt_file}`: path to a temporary UTF-8 prompt file
- `{repo_root}`: repository root
- `{task_type}`: task type such as `review` or `verify`
- `{context_level}`: `brief`, `standard`, or `full`

Local workers use `llm_local.client.complete()` and expect LM Studio at `http://localhost:1234/v1` unless configured otherwise.

## Context levels

- `brief`: concise task packet, minimal background
- `standard`: balanced packet with constraints, expected output, and source context
- `full`: larger packet including more rationale and validation requirements

## Replacement note

This module intentionally absorbs the useful parts of the prototype `llm_orchestrator` module. Do not keep both `modules/llm_orchestrator` and `modules/agent_sync` for this workflow.
