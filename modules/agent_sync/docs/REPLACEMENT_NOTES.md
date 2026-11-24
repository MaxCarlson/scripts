# agent_sync Replacement Notes (Historical)

This file records the original scripts-side replacement plan. Current source
ownership for transferred modules is `llm-agent-toolkit`; develop and install
those modules from the toolkit repository, not from `scripts/modules/`.

Do not install the prototype `scripts/modules/llm_orchestrator/`; its useful functionality has been folded into `agent_sync`.

The canonical replacements are:

- `llm-agent-toolkit/modules/llm_local/`
- `llm-agent-toolkit/modules/llm-models/`
- `llm-agent-toolkit/modules/agent_memory/`

Agent Memory notes are persistent user data, separate from its source. Use
`AGENT_MEMORY_ROOT` to select a store and the canonical `agent-memory migrate`
command to copy a legacy store before removing local residual data.

Optional follow-up integrations:

1. Make `agent_sync.adapters.local` optionally consult `llm_models.ModelAssignmentManager` before calling `llm_local`.
2. Implement the reserved `dispatch`, `integrate`, `start`, `handoff`, and `resume` stubs from the existing Phase 2/3 plans.
3. Register `agent-sync` in `modules/scripts_help/scripts_help/registry/registry.py` if the registry entry is missing.
