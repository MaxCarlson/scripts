# Phase 3C Checklist

## Shared API

- [x] Add versioned live/persisted snapshot and detail types.
- [x] Reuse one collector and existing event/analysis models.
- [x] Expose connectivity, freshness, and coverage explicitly.

## Alerts

- [x] Add shared rule evaluation with evidence classifications and minimum evidence thresholds.
- [x] Add cooldown/dedupe/ack/resolution state transitions.
- [x] Migrate telemetry schema v1 to v2 without breaking read-only v1 access.
- [x] Add offline alerts list/rules/test/acknowledge CLI.

## TUI

- [x] Add interactive overview, detail, timeline, history, hardware, and alert sections.
- [x] Add navigation, search, refresh, pause, resize, and clean terminal restoration.
- [x] Preserve watch behavior and avoid implicit telemetry recording.

## Integration contract

- [x] Document Runmux read-only API contract and authentication requirements.
- [x] Keep direct Runmux changes deferred while its implementation is active.

## Delivery

- [x] Run module and registry tests, packaging, compile, help, and diff checks.
- [x] Measure synthetic concurrent-session performance.
- [x] Review protected scope, commit, push, and verify remote SHA.
