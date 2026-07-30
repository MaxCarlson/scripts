# Manual Validation: Unified Hybrid Workflow and Validation Ledger

> Generated. Complete only checks whose safety and environment requirements are understood.

## `MC-S1-001` — Run the repository-workflow target through the Windows root dispatcher

- **Status:** `pending`
- **Platform:** `windows`
- **Safety:** `non_destructive`
- **Plan items:** `AC-S1-003`

### Instructions

1. Switch to agent/unified-workflow-ledger and pull.
2. Run ./Invoke-Tests.ps1 -Target repository-workflow.
3. Confirm the target passes and generates raw validation plus ledger projections.
4. Commit and push generated evidence.

### Expected Result

One immutable validation event is recorded without hiding the root target result.

### Notes

This is the first repository-wide self-hosting cycle.
