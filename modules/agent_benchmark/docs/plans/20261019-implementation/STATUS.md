# Status

2026-10-19: post-smoke analysis and scoring/reporting redesign implemented and hardened on branch `agent/scoring-redesign-20261019` in worktree `C:/Users/mcarls/src/scripts-agent-scoring`.
First live Qwen integration smoke test completed successfully at `integration-acceptance/smoke-20261019T154712Z-e5afebaf` with all infrastructure, project isolation, prompt attribution, scratch policy, temp-probe execution, and 22/22 hidden verification checks passing.
Task budget expired at 60.28s during final response generation; cancellation confirmed in 0.266s.

Key empirical findings & scoring improvements:
1. Token Telemetry: 112,871 input tokens verified as exact cumulative sum across all 10 assistant turns. Peak context window reached was 13,791 tokens; initial prompt was 8,192 tokens. Total generated output was 3,845 tokens (2,477 visible completion tokens, 1,368 reasoning tokens; 35.58% reasoning share of generated tokens). Emitted as measured/derived metrics.
2. Conservative Shell Classification: Hardened `classify_shell_command` with statement normalization across separators (`;`, `\n`, `&&`), single-pipeline read-only checks, and strict scratch-env probe validation. Preserves strict `uncertain` compliance while providing rich diagnostics.
3. Multi-Dimensional Scoring & Guardrails: Emitted `agent.functional_pass`, `agent.budget_pass`, `agent.clean_termination`, and `details.turn_completion`. Guardrails fail closed to `unavailable` on `infrastructure_error` to prevent false passes. Canonical `agent.worker_first_pass` and status logic remain 100% unchanged.
4. Experimental Budget Matrix & Comparison Gap: Added `BUDGET_PROFILES` ("canonical-60s", "extended-90s", "extended-120s", "extended-180s") recording `comparison_eligible: False` for non-canonical profiles. Documented cross-run comparison pipeline enforcement as an architectural gap for future multi-run tooling.

Validation: 244 agent tests passed, 3 Windows symlink skips; 82 core tests passed, 1 skip (83 in worktree with historical runs); Ruff clean; Core Mypy clean. 8 focused regression tests in `scoring_redesign_test.py` pass.
Historical evidence remains immutable. Ready for integration into `agent/agent-benchmark`.


