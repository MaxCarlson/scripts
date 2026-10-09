# Scheduler Plans Handoff

## Active Plan

```text
20261008-2132_windows-runner-and-elevation/
```

## Scope

The active plan adds Windows Task Scheduler runners through CLI and TUI, gates scheduler use until setup is complete, adds a delayed visible-window runner test, preserves per-schedule task attachment order, and isolates execution privileges by each task's Admin flag. Linux setup remains out of scope pending user approval. The original module implementation is documented at `20260926-1545_scheduler-module/`.
