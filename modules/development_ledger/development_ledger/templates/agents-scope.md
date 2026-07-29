<!-- development-ledger:managed-instructions:start -->
## Scoped Project Rules: `{{SCOPE_PATH}}`

This file governs `{{SCOPE_PATH}}` and its descendants. More deeply nested instruction files take precedence for their own subtrees.

- Treat `{{DOCS_PATH}}` as this scope's planning, handoff, and development-ledger control plane.
- Read `{{ROOT_WORKFLOW_PATH}}`, `docs/HANDOFF.md`, the active plan, and its generated `ledger/PROGRESS.md` before substantial edits in this scope.
- Keep this scope's plans and evidence separate from repository-wide or sibling-scope plans unless a plan explicitly coordinates them.
- Preserve existing interfaces and scope-specific conventions; update source, tests, configuration, and documentation together.
- Before publishing a source pass, update the active plan state block with objective, hypothesis, target IDs, implementation states, test mappings, local-environment dependencies, and manual checks.
- Do not edit generated ledger projections or `RUNS.jsonl` manually.
- Run the canonical validation target for this scope when available and never claim success without execution evidence.
- Use a separate local patch branch for local-LLM source changes and follow a generated `LOCAL_HANDOFF.md` narrowly.
<!-- development-ledger:managed-instructions:end -->
