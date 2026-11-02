# Phase 06 — Agent Policy, Documentation, Rollout and Integration

## Recommended model: GPT-6 Luna — High

**Priority:** P2 • **Depends on:** Phase 05 validation and approved integration checkpoint • **Owner:** Single release/integration agent; no competing edits to shared files • **Non-goals:** new observability features or broad prompts as a substitute for CLI fixes

### Objective

Ship concise instructions that direct Codex, AGY and other agents toward the now self-managing CLIs; document credentials, lifecycle and recovering blockers, preserve compatibility and safely integrate reviewed branches. Do not initiate ChatGPT Work mode or a remote deployment without explicit permission.

### Documentation deliverables

1. `llm-monitor web` reference with start/status/stop/restart/old compatibility, default port, hosted-vs-container URL, config mismatch, safe shutdown, owner descriptors, ready-vs-provider availability, TTY browser code exposure and exit codes.
2. `agent-bench suite doctor` reference with short/long options, exact diagnostics schema, exit/status policy, examples of denied context, stopped service, missing model, unhealthy recorder and operator actions; explain that doctor does not mutate Docker/WSL/LM Studio or dispatch inference.
3. `suite plan/run/resume` preflight flow: `-r/--recover-local` vs `-x/--execute`, check preserved `-F/--llm-friendly`, `-U` container gateway vs `-H` host monitor, OpenCode v2 model selector and Chat Completions constraint, persisted run artifacts and safe resume.
4. `security.md` / README threat model: same-user trust, Windows SID ACLs and remote deny, WSL limitations, browser code/cookie separation, capability TTL/scopes/revocation, secrets redaction, migration/deprecation for manual session-cookie env files. User-owned recording DB and WAL safe handling.
5. Troubleshooting playbook indexed by stable error code with no copy-paste commands that loosen ACLs or disable authentication. Include single approved host-context validation instructions for Windows and pointers to test evidence.
6. Operator release notes, migration fallback, rollback switches and known limitations, avoiding claims of integration environments not tested.

### Proposed concise agent instruction text

> Prefer `agent-bench suite doctor -F -f json` and managed `llm-monitor web status` over ad hoc WSL, Docker, port, PID and login troubleshooting. Treat an access failure *in the agent execution context* as distinct from a host service failure. Do not repeat the same denied operation without an observed change in context or permissions. Reuse verified running services, attempt at most the documented bounded local recovery when explicitly authorized, and preserve recordings, processes and run checkpoints. Never bypass browser authentication or expose login codes/cookies, never terminate an unidentified process, and never dispatch benchmark inference without `-x/--execute`.

Adapt this into the repository's actual agent instructions without overriding unrelated policies or duplicating existing guidelines. Do not put full-phase procedures in persistent agent prompts; link to CLI docs/error catalog.

### Git release and integration sequence

1. Check active agents/worktrees and latest validated commits again; preserve dirty work and any unmerged checkpoints. No new branch based blindly on main. Compare cumulative phased diff against contracts and security obligations.
2. Run targeted and full affected tests, review logs and benchmark evidence. Perform an independent security review focused on Windows named pipes, HTTP capability scoping, browser session middleware and HMAC identity; fix blockers on owning phase branch before integration.
3. Choose merge path based on actual branch topology: if phases are checkpoint commits on one branch, prefer one integration PR; if multiple isolated branches, use validated dependent order and test after each merge. No force pushes or deletion of active worktrees.
4. Request merge authorization if not already granted; do not assume instructions to write a *plan* authorize repository integration. Produce rollback steps without actually rolling back a user's live services.
5. After merge, smoke non-mutating `doctor` and status in approved host context; inspect docs/help alignment. Leave running Monitor/LM Studio/Docker and unrelated processes as they were unless specifically authorized.
6. Publish final `STATUS.md` and validation receipt with release SHA, PRs, tests, failures, platform coverage and an operator-first next step. Clean old branches/worktrees only when fully merged, clean and inactive, after verifying they contain no unique evidence.

### Exit criteria

Documentation matches actual help/behavior; no unbacked support claims; existing CLI and manifest compatibility verified; agent instructions are concise and security-preserving; all phase checkpoints and reports trace to commits and test logs; merge authorization recorded. The final report clearly separates **implemented**, **validated**, **merged**, **unverified**, and **not authorized**.
