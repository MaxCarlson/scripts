# Final benchmark hardening

## Baseline and ownership

Worktree `.worktrees/benchmark-live-stats`, branch `agent/benchmark-live-stats`, baseline
52d4a0f9cae0c66ec48d0f190b8e17319ef9f678. Clean before work. Preserve 1.12.0 file-tools smoke
contract and historical artifacts. Current user plan is the scope authority.

## Stages

1. Profile hardening: ordered effective permission semantics, narrowly trusted output-directory
   exception, role/prompt identity, actionable rejection before session creation.
2. Additive judgments, timings, zero-denominator diagnostics, explicit comparison contract and
   consistent terminal/JSON/CSV/Markdown/HTML rendering. Preserve strict precedence and CLI unknowns.
3. Document and assess a real shell boundary. Never enable sandboxed-shell-v1 or downgrade it to
   host execution without demonstrated containment of worker AND verifier. No live inference authorized.
4. Retain existing memory admission. No unvalidated formula replacement or blind batch continuation.

## Validation and delivery

Add focused red/green regressions, run offline agent/core/report suites and lint. Independent verifier
reviews the resulting diff and representative raw evidence. Commit/push reviewed stages and merge
local main before user trials. Prepare one-model/one-submission live acceptance, do not execute it.

## Status

Stage 1 complete and independently reviewed. Permission semantics and role identity are validated;
output trust is correlated to the local server listener PID/executable/startup XDG_DATA_HOME (not
inferred from config/state siblings). Unsupported/uninspectable layouts fail closed. An absent
output leaf is allowed only under the verified existing app-data root with ordinary path ancestry.
Read-only installed OpenCode 1.19.3 probe accepted its exact generated exception; no session was
created. Focused profile/bridge/diagnostic checks: 69 passed. Broader in-progress agent changes:
349 passed, 3 skips. Stage 2 judgments, grouping and rendering are being validated separately.

Docker engine probe failed: dockerDesktopLinuxEngine named pipe absent. Stage 3 enforcement is
not available; document the full boundary and reject sandbox requests without host fallback.
