# Status

2026-10-19: revised diagnostic smoke implemented/tested offline after Gemini REVISE; ready for one separately authorized Qwen diagnostic on the existing runtime. No live execution authorized or performed. Worktree C:/Users/mcarls/src/scripts-agent-benchmark, branch agent/agent-benchmark; implementation 6e319c8af78cde38458e40163c762dac5ff5b866; documentation follows.

Source 1.3.0; suite/verifier 0.1.1 and scope policy trial-local-scratch-v1 unchanged. smoke requires explicit -x, one model, fixed 60-second budget/10-second confirmation grace, and existing services. Intended configuration is validated pre-dispatch; saved UTF-8 prompt is attributed to stored user turn post-dispatch. Provider-bound payload remains optional/unverified and is not a pre-turn prerequisite.

state.reserved_trial is shared by diagnostics/scored runs; existing attempt/cancel/reconcile/cleanup algorithms remain authoritative. Ambiguous submission persists and blocks restart; diagnostic output failure cannot release an active worker. Outputs are isolated integration-acceptance evidence with no canonical TrialResult or report generation. Protected temp probe and frozen scratch-excluded hidden verification are separate observations.

Validation: 236 agent passed/3 Windows symlink skips; 83 core passed; Ruff/core Mypy clean; focused diagnostic/probe Mypy clean. Agent-wide Mypy retains the established 22 legacy diagnostics. All 114 historical/acceptance files unchanged. No benchmark_core edits or service/model interaction.

Next: use the exact command in integration-smoke-proposal.md only after separate execution authorization; existing runtime must already be operational. No mandatory full-payload tracing or claim of full prompt inheritance verification. No suite expansion, retry, repair or scored comparison.
