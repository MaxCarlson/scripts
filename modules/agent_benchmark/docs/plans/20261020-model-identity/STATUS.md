# Model identity resolution status

Worktree: `C:/Users/mcarls/src/scripts-agent-benchmark/.worktrees/benchmark-live-stats`
Branch: `agent/benchmark-live-stats`

## Goal

Make LM Studio discovery, planning, lifecycle loading, OpenCode selection, and run metadata use one exact model key. Register missing exact IDs only in the isolated trial project's OpenCode config.

## Constraints

- Never infer aliases from OpenCode display names or fuzzy model names.
- Never modify shared OpenCode or LM Studio configuration or load/unload models in this task.
- Planning reports readiness; execution resolves all exact IDs and checks provider connectivity before writing run artifacts or changing model state.
- Do not run live inference.

## Status

- Implementation and focused offline verification are complete on this branch.
- Direct evidence confirms LM Studio model keys are the runtime IDs and the OpenCode display `name` is descriptive only.
- The six affected test modules plus the new identity tests passed (81 tests); the added distinct-quantization regression passed in a follow-up run (10 identity tests total). Ruff and `git diff --check` passed.
- No live inference, model load/unload, or shared configuration change was performed. Live OpenCode project-config discovery remains to be confirmed during the user's next authorized benchmark run.
- Next: commit/push, then merge into `main` under the user's standing authorization.
