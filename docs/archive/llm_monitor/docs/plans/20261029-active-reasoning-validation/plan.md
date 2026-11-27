# Active Reasoning Validation Plan

**Goal:** Validate `llm-monitor live` against an authorized active OpenCode worker, correlate evidence without conflating configuration and outcome, and correct only reproducible monitor defects.

**Architecture:** Keep the runtime investigator in control of trials and provider instrumentation. Attach the standalone observer to the exact supplied OpenCode project/session, reconcile SSE with stored history, and consume only sanitized request evidence with exact identities. If no active session is supplied, finish offline/runtime-contract validation and report streaming as unverified.

**Tech Stack:** Python 3.11+, pytest fixtures, OpenCode 1.19.3 read-only HTTP/SSE, isolated package build/test environment.

**Spec:** User assignment, “LLM Monitor — Active Reasoning Validation and Runtime Evidence Correlation”.

## Constraints

- Base branch: `codex/llm-monitor-live-reasoning-20261029` at `88a50d9b81fbb210ffb5192d6f0c373da39509d5`.
- Writable source scope: `modules/llm_monitor/` only.
- Do not dispatch inference, alter models/configuration/services, terminate work, touch another worktree/evidence/database, or modify other modules.
- Reasoning capture stays bounded, memory-only, hidden by default; request evidence stays sanitized and exact-match only.
- Keep model configuration, session variant, provider request, stream, completion, tool/file effects, and independent verifier outcomes as distinct evidence.
- Commit and push this isolated branch only; do not merge.

## Review Focus

- SSE/global envelope and project/session identity mismatches are discarded before content accumulation.
- Delta-before-update, duplicate frames, and completed-part replacement do not lose or double-count content.
- Reconnects preserve partial state while marking the missing interval incomplete.
- Reasoning character counts never become token counts; unavailable current tokens remain `null`.
- A quiet or disconnected stream does not by itself establish an inference stall or unsupported streaming.
- Request evidence requires exact session, message, and creation timestamp; conflicting configuration is preserved, not reconciled silently.
- Worker/session completion, tool success, file modification, and independent task acceptance remain separate.

## Tasks

1. Verify branch ancestry/clean state, baseline suite, installed CLI behavior, OpenCode 1.19.3 `/doc`, and existing tests/code for identity, framing, bounded state, provenance, and classifications.
2. Attach read-only to an exact session supplied by the runtime investigator before or during a controlled trial. Record connection/coverage timeline and metadata-only SSE observations; do not start or control inference.
3. Reconcile sanitized request evidence, session/config metadata, completed messages, tool records, MCP state, and independent verifier results only when those artifacts are supplied. Document unsupported conclusions explicitly.
4. For each reproducible monitor defect, add a failing deterministic regression test first, fix the smallest relevant code in `modules/llm_monitor/`, and rerun the complete suite.
5. Verify isolated package CLI, compile, Ruff, diff/status, update compatibility/evidence reports, then commit and push without merging.
