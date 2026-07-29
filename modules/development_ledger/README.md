# Development Ledger

`development_ledger` turns plan intent, Git state, normalized automated-test results, and manual checks into a compact append-only history designed for remote and local LLM handoff.

The module is repository-agnostic and dependency-light. It is intended to run as the final phase of a repository validation dispatcher such as `Invoke-Tests.ps1`.

## Core outputs

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

## Quick start

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
python -m development_ledger manual -p path/to/plan.md -o path/to/ledger -i MC-001 -s passed -n "Verified on Windows 11" -w
```

See `docs/` for the plan syntax, dispatcher integration, architecture, and instruction-placement guidance.
