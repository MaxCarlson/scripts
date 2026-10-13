# Codex Agent Instructions and Handoff Cleanup

## Goal

Make the instructions used by Codex in `scripts/` accurate, inexpensive to load, and easy to resume from another Codex session. Keep safety and approval boundaries explicit.

## Stages

1. **Repository routing:** shorten the always-loaded root `AGENTS.md`; make other documents conditional on the task; resolve conflicting commit and validation directions in the repo guide; establish one current handoff pointer. Verify links, Git state, and Codex instruction discovery. User reviewed the work and authorized publishing it.
2. **PC-wide Codex policy:** verify the global Codex source and home-directory symlink after the user's dotfiles update. Confirm its policy is concise and compatible with Claude and Gemini. Run fresh Codex checks inside and outside `scripts/` when the runtime can access its config and state directories.
3. **Nested guidance and handoff:** audit module `AGENTS.md` placement and stale instructions, especially runmux and aebndl; reduce duplication; verify Codex from representative module paths. Reconcile plan handoffs against branch, commits, code, and tests.
4. **Other agents:** align Claude and Gemini loading paths and remove duplicate or stale policy, with their own loading checks. Claude policy and its symlink are now verified; Gemini repository routing is implemented, while global Gemini and runtime loading checks remain.

## Longer-term investigation: local GPU helper

Evaluate a model hosted on the RTX 5090 as an opt-in helper for narrow tasks. Compare available models and serving tools at the time of implementation, confirm memory and throughput on this PC, and run representative quality tests before routing work to it. Prefer an explicit tool or skill that gives the parent agent a bounded task, result, and verification evidence. Do not silently delegate edits, approvals, secrets, or high-risk decisions. Assess whether any saved tokens exceed orchestration and review costs. This investigation does not block the Codex instruction cleanup.

Codex CLI already supports a whole local-model session through `--oss` with Ollama or LM Studio. That is distinct from automatically handing a subtask to a local model while the parent Codex session stays on its normal model. Evaluate a bounded MCP/tool or explicit skill for the latter only after local-model quality is measured.

## Success criteria

- A fresh Codex run identifies the correct global and repo instruction sources, and a run from a nested module identifies the applicable nested file.
- A small repo task does not require reading every planning and standards document.
- Approval to commit and push has one consistent meaning across active instruction files.
- One root handoff points to the current work without conflicting descriptions of other plans.
- Git changes stay isolated on the plan branch; PC-wide changes have a separate backup before application.

The user explicitly authorized committing, pushing, and merging this repository instruction work into `main` on 2026-10-12.
