# Manual Validation: Development Ledger Self-Hosting

> Generated. Complete only checks whose safety and environment requirements are understood.

## `MC-S1-001` — Run and inspect the first Windows self-host validation

- **Status:** `pending`
- **Platform:** `windows`
- **Safety:** `non_destructive`
- **Plan items:** `AC-S1-002`

### Instructions

1. Run ./Invoke-Tests.ps1 -Target development-ledger from the repository root.
2. Confirm the dispatcher preserves its exact overall result.
3. Confirm one run event and all generated projections are written.

### Expected Result

The target records complete evidence and the dispatcher result still reflects the validation sections.
