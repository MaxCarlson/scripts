# Cycle 02: Multi-Attach and Input Lock

Status: in progress

## Implementation

- Register concurrent view and interact sessions with heartbeat leases.
- Track current and lifetime view/interact counts.
- Replace exclusive interaction with a FIFO input-owner queue.
- First interact client receives ownership.
- Transfer ownership after configurable minimum tenure, holder input idle time,
  and completion of prior PTY writes.
- Remove disconnected or expired clients and hand off ownership safely.
- Expose attachment and lock state through status, list, and JSON output.

## Tests

- Multiple concurrent interact clients.
- FIFO ordering and idempotent requests.
- Minimum tenure and idle transfer.
- Holder disconnect and lease expiry.
- Rejected input from non-holders.
- Current/lifetime list counts.
