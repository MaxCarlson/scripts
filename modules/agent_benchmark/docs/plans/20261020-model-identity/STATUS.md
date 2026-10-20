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
- The seven affected test modules passed (92 tests). Ruff and `git diff --check` passed.
- Read-only plan execution found `asyncio.create_subprocess_exec` was denied for `lms` on this Windows environment; switching the default CLI runner to `asyncio.to_thread(subprocess.run, ...)` restored full quantization/variant discovery. The four-model plan then reported GPT-OSS `runnable` and Muse, Ornith, and Devstral `registration_required`, with Q4_K_M/MXFP4 metadata.
- No live inference, model load/unload, or shared configuration change was performed. Live OpenCode project-config discovery remains to be confirmed during the user's next authorized benchmark run.
- Integration complete: feature commits `8ac2e414` and `d0e9e78c` are pushed; merged main is `281ca2ce`.
