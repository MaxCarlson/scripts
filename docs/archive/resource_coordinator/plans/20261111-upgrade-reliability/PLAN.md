# Resource Coordinator Upgrade Reliability

## Scope

Complete the isolated follow-up to v0.12.0: investigate the historical WinError 206 upgrade interruption, safely classify definitive model-load failures, avoid redundant cold loads when a compatible instance is positively identified, prevent repeated uncertain retries, and define stable recovery events for the separate Notifications project.

## Checkpoint

- Base: `b75cf86e102e43e1ea3ca17b1f3422b4201291e8`.
- Branch: `agent/resource-coordinator-upgrade-reliability-20261111`.
- Worktree: `.worktrees/resource-coordinator-upgrade-reliability-20261111`.
- Code checkpoint: `e10ce1b55ed12874cf4f403f48a4e5303e28dbb2`.
- No merge, push, or production deployment is authorized.

## Stages

1. Upgrade transport: localize WinError 206 evidence, improve durable failure attribution, and preserve rollback behavior.
2. Model-load outcomes: release only on documented authoritative completion; preserve fail-closed behavior otherwise.
3. Loaded-model reuse: use bounded read-only inventory and exact compatibility checks; otherwise use protected load path.
4. Retry protection: prevent new GPU requests while an unresolved restart inhibition exists; do not bypass uncertainty holds.
5. Recovery events: reuse the existing event dispatcher and document its safe envelope without implementing notification transport.
6. Focused regression validation, semantic/security review, status documentation, and local checkpoint commits.

## Safety boundary

No live Coordinator/KRig/LM Studio changes, model loads, Scheduled Task mutations, credential changes, WSL changes, deployment, merge, push, or production GPU work. Production deployment remains gated on isolated Windows Scheduled Task acceptance and better diagnosis of the historical task-install failure.
