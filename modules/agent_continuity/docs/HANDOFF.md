# Module Handoff — `agent_continuity`

- **Updated:** 2026-11-19
- **Repository:** `scripts`
- **Worktree:** `../scripts-agent-continuity-m2`
- **Branch:** `feature/agent-continuity-m2`
- **Base Commit:** `59e124f4ff570f30d53c36267e2871862b690e42` (descends from M1 `ab9195acbfe0093e6a6683a723495b0347b7c718`)

## Current State

- **Phase 0 & Phase 1 (M1):** Complete and integrated into `main`.
- **Phase 2 (M2):** Implemented in isolated worktree (`0.2.0`):
  - Verified Codex `0.170.0` and AGY `1.5.12` / `1.2.11` hook contracts ([ADR-002](./adr/ADR-002-phase2-hook-contracts.md))
  - `markers.py`: deterministic `Workflow-ID:` / `[wf:...]` parser ignoring code fences, blockquotes, and inline examples, with conflict detection
  - `hooks.py` & `shim.py`: normalized hook events and fail-open `agents hook-shim` writing only to durable atomic spools
  - `materializer.py`: automatic `strong` association, untagged lineage inheritance, session repurposing, manual-confirmation conflict preservation, and `turns` tracking
  - `providers/`: read-only bounded `discover_sessions()` for Codex `state_5.sqlite` and AGY `conversation_summaries.db` + `agents discover`
  - `installer.py` & `agents hooks status|install|uninstall|rollback`: dry-run-first, backup/rollback-safe hook management (not activated against live user config)

## Next Action (Phase 3 / Live Activation)

1. Upon explicit user approval, run `agents hooks install -p codex -a` and `agents hooks install -p agy -a` to activate live hook capture.
2. Implement Phase 3 historical recovery scanners, handoff fingerprinting, summary previews, and validated checkpoints.
