# Stage 1 — storage-aware worker budget

## Scope

Remove the fixed eight-worker maximum when either the destination or selected
scratch volume is detected as SSD. The aggregate CPU budget remains enforced.
When neither is SSD, the maximum remains four. Detect both paths rather than
assuming any configured scratch path is fast.

## Files

- `mangadl/concurrency.py`
- `mangadl/cli_core.py`
- `mangadl/cli_structure.py`
- `mangadl/manager.py`
- related CLI/concurrency tests and user docs.

## Verification

- Test all destination/scratch media combinations and CPU counts.
- Test explicit `--max-workers`, default previews, and runtime `+` limits.
- Run focused tests, the complete MangaDL suite, Ruff, compileall, and the
  MangaDL repository dispatcher target.
- Do not start a live download as part of this stage.
