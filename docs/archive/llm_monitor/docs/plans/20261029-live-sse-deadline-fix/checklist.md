# Checklist

- [x] Inspect source and confirm blocking-iterator defect with reproduction evidence.
- [x] Add regression tests for idle streams, periodic comments, intermittent events, disconnections, and deadline exit.
- [x] Implement interruptible stream reading bounded by monotonic deadline.
- [x] Ensure immediate clean socket closure upon deadline expiration.
- [x] Return partial observations with accurate coverage and completeness metadata without inventing reasoning tokens.
- [x] Document reasons for version mismatch between source (0.6.0) and installed `.venv` editable metadata (0.1.0).
- [x] Verify on running OpenCode instance without triggering inference or service restart.
- [x] Full module regression tests pass; ruff and compileall clean.
