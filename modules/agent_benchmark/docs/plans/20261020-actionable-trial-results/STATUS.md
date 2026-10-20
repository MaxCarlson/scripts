# Actionable trial results (1.10.0)

## Goal

Make successful code, scope violations/uncertainty, timeout, and infrastructure failures independently understandable in normal/quiet terminal output and persistent evidence.

## Evidence and decisions

- `EXP_20261020_025803` passed functional verification in 37.156s, within its 120-second budget. The only snapshot violation was `__pycache__/grep.cpython-312.pyc`; six transcript operations also left compliance uncertain. This is functional success and strict failure, not a model crash or wrong solution.
- Keep historical evidence and strict scoring intact. Do not hide ignored/cache files from snapshots or treat arbitrary shell commands as safe based on superficial command matching.
- Add worker guidance for `python -B`, scratch-only temporary files, optional worker testing, and read/edit tools for simple tasks. This is cooperative guidance, not runtime enforcement or a guarantee of a strict pass.

## Changes

- Every trial prints independent code/scope/budget/termination checks, exact violation paths, scope uncertainty reasons, verifier/provider errors, timeout explanation, and relative evidence location. The same explanations are logged under `TRIAL_DIAGNOSTIC`.
- Model/final summaries display functional pass counts with measured denominators and unavailable counts, alongside canonical strict rankings.
- Trial JSON retains bounded verifier output and exit code. Provider diagnostics retain available HTTP status/response body and retryability; generation-limit and content-filter finish reasons are distinct from context rejection. Do not infer a native crash or context overflow when the provider does not expose it.
- Scheduler aborts persist `experiment-failure.json` with model, stage, exception type/message, and log reference, including model-load failures before trial allocation.

## Verification and status

Implementation complete. Full offline suite with short module-owned scratch path `r10`: 311 passed, 3 skipped (Windows symlink privileges). Focused output/bridge/scheduler/scratch/scoring checks: 89 passed, 1 skipped. After retaining transport exception messages separately from stable error codes, attempt/scoring/diagnostics checks: 28 passed. Ruff and `git diff --check` passed. The new renderer was also run against the saved `025803` trial without modifying or rescoring it. No inference, model load/unload, shared configuration changes, imported benchmark tasks, or scope relaxation.

An initial full run used an excessively long temporary workspace path and failed Git seed setup in several pipeline checks; rerunning existing tests with short module-owned scratch paths passed. No production Git configuration was changed.
