# Development Ledger

`development_ledger` bootstraps reusable coding-agent instructions and turns plan intent, Git state, normalized automated-test results, and manual checks into a compact append-only history for remote and local LLM handoff.

The module lives in the `scripts` repository but is repository-agnostic. It can configure and track other repositories without copying its Python source into them.

## Capabilities

- Dry-run-first repository setup with explicit `--write`
- Safe injection into existing `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, and Copilot instruction files
- Repository-wide and independently scoped subproject `docs/` areas
- Structured plan state embedded in normal Markdown plans
- JUnit XML and generic script-result normalization
- Immutable per-plan run and manual-check history
- Generated LLM progress, traceability, manual-check, and local-handoff views
- Stall, loop, regression, and remote/local routing analysis

## Repository setup

Preview setup for a repository with two independent scopes:

```powershell
python -m development_ledger setup -r C:\path\to\repo -s apps/web -s services/api
```

Configure modules conveniently:

```powershell
python -m development_ledger setup -r C:\path\to\repo -m module_one -m module_two -w
```

Configure every immediate directory under `modules/`:

```powershell
python -m development_ledger setup -r C:\path\to\repo -A -w
```

Select only particular agent wrappers:

```powershell
python -m development_ledger setup -r C:\path\to\repo -a codex -a claude -w
```

The dedicated entry point and standalone script are equivalent:

```powershell
development-ledger-setup -r C:\path\to\repo -m module_one -w
```

```powershell
python setup_development_ledger.py -r C:\path\to\repo -m module_one -w
```

Setup always creates or manages canonical `AGENTS.md` rules. Claude, Gemini, and Copilot wrappers are added according to the selected agents. Existing unmarked instruction content is preserved, while only the module's marked blocks are refreshed.

## Per-plan outputs

For each tracked plan, the module maintains:

```text
ledger/
├── RUNS.jsonl
├── LATEST.json
├── PROGRESS.md
├── TRACEABILITY.md
├── MANUAL_CHECKS.md
└── LOCAL_HANDOFF.md
```

- `RUNS.jsonl` is the immutable plan/run ledger.
- `LATEST.json` is the latest normalized event.
- `PROGRESS.md` is the primary fresh-LLM orientation document.
- `TRACEABILITY.md` maps plan items to automated and manual evidence.
- `MANUAL_CHECKS.md` contains user-executable checks that automation cannot complete.
- `LOCAL_HANDOFF.md` is generated when local Codex is recommended.

Raw logs remain supporting evidence and may be retained separately according to repository policy.

## Plan and validation quick start

Validate a plan document without modifying files:

```powershell
python -m development_ledger validate-plan -p path/to/plan.md
```

Preview a validation event:

```powershell
python -m development_ledger record -p path/to/plan.md -o path/to/ledger -r . -j pytest.xml -s powershell-results.json
```

Persist the event and regenerate projections:

```powershell
python -m development_ledger record -p path/to/plan.md -o path/to/ledger -r . -j pytest.xml -s powershell-results.json -w
```

Record a manual check result:

```powershell
python -m development_ledger manual -p path/to/plan.md -o path/to/ledger -r . -i MC-001 -s passed -n "Verified on Windows 11" -w
```

See `docs/` for architecture, setup, plan syntax, dispatcher integration, instruction discovery, and instruction-placement guidance.
