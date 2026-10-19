# Status

2026-10-19: Phase 1d project isolation implemented offline; stop at review/non-inference API verification gate. Worktree C:/Users/mcarls/src/scripts-agent-benchmark, branch agent/agent-benchmark.

Commits: 8a94f580 (committed independent Git workspaces) and 15efb1dc (project/session gate, header routing, project-bound ownership/provenance and Windows Git cleanup). Package 1.1.0, isolation policy isolated-git-project-v1; task suite remains 0.1.1. User's corrected Phase 1d handoff takes precedence over supporting Gemini snippets.

Validation: agent 175 passed/2 Windows symlink skips; core 83 passed; Ruff clean; core Mypy and new Git helper Mypy clean. Optional broad agent Mypy retains 22 legacy diagnostics versus 27 in a baseline shadow-file check; not a clean agent-wide typing claim.

Both pre-isolation live runs and all 59 retained files are unchanged. No live model dispatch, shared-service interaction/reconfiguration, scratch policy, scoring redesign or suite expansion in this phase. Global OpenCode configuration remains; logical isolation is not OS-enforced sandboxing.

Next: separate authorization for header-routed /path and /project/current probes on fresh committed/control repositories, plus empty-session creation/lookup only if explicitly included. No inference permitted in that probe. Later live-worker acceptance is a separate gate. See phase1d.md and docs/HANDOFF.md for exact interfaces, validation commands, limitations and handoff.
