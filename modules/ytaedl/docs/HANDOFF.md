# ytaedl Immediate Project Handoff

## Current Branch

`codex/ytaedl-priority-file-queue-20261106` in `.worktrees/ytaedl-priority-file-queue-20261106`

## Active Stage / Plan

Implementing thread-capped and rotating priority URL-file scheduling.

* Plan: [00-implementation-plan.md](plans/20261106-priority-file-scheduling/00-implementation-plan.md)
* Status: [STATUS.md](plans/20261106-priority-file-scheduling/STATUS.md)

## Verification and Commands

* Focused tests: `pytest tests/test_manager.py -q` and
  `pytest tests/test_domain_index_priority.py tests/runtime_submissions_test.py tests/test_manager_pause.py -q`
  (run from `modules/ytaedl`).
* No media downloads or live services are used by these scheduling tests.
