# Status

2026-10-19: post-smoke analysis and scoring/reporting redesign implemented on independent branch `agent/scoring-redesign-20261019` in worktree `C:/Users/mcarls/src/scripts-agent-scoring`.
First live Qwen integration smoke test completed successfully at `integration-acceptance/smoke-20261019T154712Z-e5afebaf` with all infrastructure, project isolation, prompt attribution, scratch policy, temp-probe execution, and 22/22 hidden verification checks passing.
Task budget expired at 60.28s during final response generation; cancellation confirmed in 0.266s.

Key empirical findings & scoring improvements:
1. Token Telemetry: 112,871 input tokens verified as exact cumulative sum across all 10 assistant turns. Peak context window reached was 13,791 tokens; initial prompt was 8,192 tokens; output tokens 2,477 (including 1,368 reasoning tokens, 55.2%). Populated in `results.py` as measured/derived metrics.
2. Shell Classification: Added `classify_shell_command` distinguishing `trusted_probe`, `read_only_inspection`, and `arbitrary_execution`. Preserves strict `uncertain` compliance while providing rich diagnostics.
3. Multi-Dimensional Scoring: Emitted `agent.functional_pass` (1), `agent.budget_pass` (0), `agent.clean_termination` (1), and `details.turn_completion` ("aborted_at_budget") without altering canonical `agent.worker_first_pass` or status logic.
4. Experimental Budget Matrix: Added `BUDGET_PROFILES` ("canonical-60s", "extended-90s", "extended-120s", "extended-180s") with explicit `comparison_eligible` gating.

Validation: 243 agent tests passed, 3 Windows symlink skips; 82 core tests passed, 1 skip; Ruff clean; Core Mypy clean. 7 new focused regression tests in `scoring_redesign_test.py` pass.
Historical evidence remains immutable. Ready for Sol review.

