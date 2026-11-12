# Official Evaluation Validity & Security Repair Status

## 1. Environment & Baseline Status
- **Date:** 2026-11-11
- **Branch:** `fix/agent-benchmark-official-evaluation-20261111`
- **Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\agent-benchmark-official-evaluation-20261111`
- **Base Commit:** `8bfd06a0`
- **Remote:** `origin/fix/agent-benchmark-official-evaluation-20261111`

## 2. Defect Status
- [x] **Defect A (IFEval Scoring):** Replace approximate rules with official Google IFEval instruction suite; reject unknown IDs; strict/loose parity.
- [x] **Defect B (LiveCodeBench Verification):** Replace dummy harness with real `stdin` / `functional` tester; prevent `sys.exit(0)` bypass; error on missing test data.
- [x] **Defect C (Source Revisions):** Pin verified upstream commits for Google Research, LiveCodeBench, and Hugging Face dataset.
- [x] **Defect D (Dataset Materialization & Real Prompts):** Materialize real datasets, populate verified task IDs, feed authentic prompts.
- [x] **Defect E (Container Security):** Enforce `--read-only`, tmpfs, unprivileged user, and orphaned container cleanup.

## 3. Required Verification Matrix
- [x] Unsupported IFEval instruction does not silently pass.
- [x] Real IFEval reference results match adapter outputs.
- [x] Incorrect, syntactically valid LiveCodeBench solution fails.
- [x] Correct LiveCodeBench solution passes.
- [x] Premature clean process exit cannot bypass verification.
- [x] Missing benchmark test data blocks scoring.
- [x] Invalid Git revision fails setup without an installed receipt.
- [x] Hugging Face installation actually materializes and verifies the requested data.
- [x] Every frozen cohort ID resolves to exactly one verified task.
- [x] Direct-model prompts exactly match the intended benchmark inputs.
- [x] Docker invocation enforces declared isolation flags.
- [x] All prior CLI, Harbor, persistent-suite, and benchmark_core regression tests remain passing (710 passed in `agent_benchmark`, 120 passed in `benchmark_core`).
