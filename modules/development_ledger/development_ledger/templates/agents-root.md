<!-- development-ledger:managed-instructions:start -->
## Repository and Development-Ledger Rules

These rules are required for all work in `{{REPOSITORY_NAME}}` unless a more specific nested `AGENTS.md` overrides them for its subtree.

### Before editing

- Read `{{ROOT_WORKFLOW_PATH}}`, the nearest applicable `docs/HANDOFF.md`, the active plan, and its generated `ledger/PROGRESS.md` when present.
- Treat the nearest directory containing both an instruction file and `docs/` as the project scope for adjacent files and descendants.
- Preserve existing public interfaces, behavior, data formats, and repository conventions unless the active plan explicitly authorizes a breaking change.

### While implementing

- Keep source, tests, configuration, and documentation consistent.
- Add or update automated tests for meaningful behavior changes, including normal, edge, and failure cases.
- Avoid destructive operations, production mutation, credential exposure, external communication, or material cost without explicit authorization.
- Do not edit generated ledger files manually.

### Before stopping or publishing

- Update the active plan's development-ledger state block with the bounded objective, hypothesis when diagnostic, target IDs, implementation states, test mappings, environment dependencies, and manual checks.
- Run the repository's canonical validation command when the current environment supports it. Never claim a test or command passed without execution evidence.
- Record any behavior that cannot be automated as an explicit manual check with exact instructions and expected results.
- Keep remote and local source edits on separate branches. Do not modify the same branch concurrently.

### After validation evidence returns

- Read the generated progress, traceability, manual-check, and handoff projections before changing source again.
- Continue remotely only when evidence shows material progress or supports a distinct bounded hypothesis.
- When the generated evidence recommends local debugging, follow the narrow `LOCAL_HANDOFF.md` assignment rather than reimplementing the full feature.
<!-- development-ledger:managed-instructions:end -->
