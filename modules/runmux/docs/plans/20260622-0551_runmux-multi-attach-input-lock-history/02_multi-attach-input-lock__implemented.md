# Stage 02: Multi-Attach and Input Lock

Status: implemented, committed, and manually approved

## Implementation

- Register concurrent view and interact sessions with heartbeat leases.
- Track current and lifetime view/interact counts.
- Replace exclusive interaction with a FIFO input-owner queue.
- Give the first interact client initial ownership.
- Transfer ownership after minimum tenure, holder input idle time, and prior PTY
  writes complete.
- Remove disconnected or expired clients and hand off ownership safely.
- Expose attachment and lock state through status, list, and JSON output.

## Verification

- 72 automated tests passed.
- Ruff, Black check, compileall, and coverage passed.
- Real supervisor IPC smoke confirmed two interactors, one viewer, a held lock,
  one queued requester, and matching list/JSON counts.
- User manually confirmed on 2026-07-19 that multiple terminals can both
  interact with or view the same managed run.

## Commit

Implemented in commit `1cb73e4` (`runmux`).

Last edited: 2026-07-19 07:04:35 -07:00
