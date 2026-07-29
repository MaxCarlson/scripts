# Setup Template Inventory

These templates are packaged with `development_ledger` and rendered by `development-ledger setup`.

## Native instruction templates

- `agents-root.md` — canonical essential repository rules
- `agents-scope.md` — canonical rules for an independent subtree
- `claude-root.md` / `claude-scope.md` — Claude Code imports of canonical and shared rules
- `gemini-root.md` / `gemini-scope.md` — Gemini CLI imports of canonical and shared rules
- `copilot-root.md` — repository-wide Copilot instructions with essential rules inline
- `copilot-scope.md` — path-specific Copilot instructions using `applyTo`

Instruction templates contain managed markers. Setup replaces only the marked region in existing native instruction files.

## Documentation templates

- `workflow.md` — shared cross-agent workflow protocol
- `docs-readme.md` — repository-wide docs overview
- `scope-docs-readme.md` — subtree planning-scope overview
- `plans-readme.md` — plan directory conventions
- `handoff.md` — create-only initial handoff scaffold

The shared workflow and Copilot path-specific files are setup-managed. README and handoff scaffolds are create-only so existing user documentation is never overwritten.

## Template tokens

Depending on the template, setup replaces:

- `{{REPOSITORY_NAME}}`
- `{{SCOPE_PATH}}`
- `{{DOCS_PATH}}`
- `{{ROOT_WORKFLOW_PATH}}`
- `{{ROOT_WORKFLOW_IMPORT}}`
- `{{AGENTS_IMPORT}}`
- `{{APPLY_TO}}`

Unresolved uppercase tokens cause setup to fail before any write occurs.
