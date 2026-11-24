# agent_sync Replacement Notes

Replace `scripts/modules/agent_sync/` with this directory.

Do not install the prototype `scripts/modules/llm_orchestrator/`; its useful functionality has been folded into `agent_sync`.

Keep these existing modules:

- `scripts/modules/llm_local/`
- `scripts/modules/llm-models/`
- `scripts/modules/agent_memory/`

Optional follow-up integrations:

1. Make `agent_sync.adapters.local` optionally consult `llm_models.ModelAssignmentManager` before calling `llm_local`.
2. Implement the reserved `dispatch`, `integrate`, `start`, `handoff`, and `resume` stubs from the existing Phase 2/3 plans.
3. Register `agent-sync` in `modules/scripts_help/scripts_help/registry/registry.py` if the registry entry is missing.
