---
plan_index: 0005
origin: ai
status: implemented
source_file: user_request_20260509_plan_plus_1
---

# Plan +1: ytaedl Runtime Hardening

## Goals

- Add per-attempt event identity to downloader NDJSON for simulate, normal download, fallback discovery, fallback candidates, progress, terminal completion, and finish events.
- Track manager `active_attempt_id` separately from worker assignment generation.
- Clear stale progress on simulate/fallback phase transitions and ignore progress or terminal events whose `attempt_id` does not match the current active attempt.
- Keep fallback/simulate rows as phase text until fresh matching progress arrives.
- Preserve domain-index default behavior: `-H ./logs/domain_index.json`.
- Clarify help text that the default domain index path lives under the default log directory.
- Print the ytaedl version on all help surfaces.
- Add a read-only audit helper for copied run artifacts under `modules/ytaedl/logs/new_logs` and `new_archive`.

## Implementation Notes

- Implemented in `ytaedl/downloader.py`, `ytaedl/manager.py`, `ytaedl/log_audit.py`, and CLI parser modules.
- Added tests for versioned help output, attempt-id stale progress protection, and synthetic log-audit fixtures.
- Validation should include running the audit helper against copied logs and the ytaedl test suite.

