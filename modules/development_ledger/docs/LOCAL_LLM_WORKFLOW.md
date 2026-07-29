# Local LLM Workflow

## Entry conditions

Local Codex should be used when:

- the generated routing decision is `handoff_local`,
- a failure depends on the real OS, installed tools, services, credentials, hardware, networking, storage, GUI/TUI behavior, or local-only state,
- an interactive debug loop is materially more efficient than another remote pass.

Routine validation should remain deterministic and non-LLM.

## Required reading order

1. Repository and project agent instructions
2. Active project handoff
3. Active plan
4. Generated `ledger/PROGRESS.md`
5. Generated `ledger/LOCAL_HANDOFF.md`
6. `ledger/LATEST.json`
7. Raw artifacts identified by the handoff
8. Relevant source and tests

## Scope

The local agent should diagnose and fix the generated blocker only. It must not take ownership of unrelated plan stages.

When source changes are needed:

1. Create a separate local patch branch.
2. Reproduce the failure before editing.
3. Add or improve the narrowest regression test or diagnostic check.
4. Make the smallest compatible fix.
5. Update the active plan state block with the local objective, hypothesis, target IDs, and implementation state.
6. Run the full root validator.
7. Leave changes for user inspection, staging, commit, and push unless explicitly authorized.

## Model routing

- Mechanical environment inventory: GPT-5.6 Luna, medium
- Normal platform-specific diagnosis: GPT-5.6 Terra, medium
- Multi-component ambiguous failure: GPT-5.6 Terra, high
- Subtle process/filesystem/encoding/native issue: GPT-5.6 Sol, medium
- Security, corruption, or data-loss risk: GPT-5.6 Sol, high
- Rare blocker after strong failed attempts: GPT-5.6 Sol, extra-high

## Required final report

The local agent reports:

1. Root cause
2. Environment-specific evidence
3. Files changed
4. Tests added or modified
5. Exact validation commands and exit codes
6. Remaining uncertainty
7. Whether the patch is ready for user inspection
