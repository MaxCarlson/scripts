# Official Evaluation Validity & Security Repair Status

## 1. Environment & Baseline Status
- **Date:** 2026-11-11
- **Branch:** `fix/agent-benchmark-official-evaluation-20261111`
- **Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\agent-benchmark-official-evaluation-20261111`
- **Base Commit:** `8bfd06a0`
- **Remote:** `origin/fix/agent-benchmark-official-evaluation-20261111`

## 2. Defect Status
- [x] **Defect A (IFEval Scoring):** Replace approximate rules with official Google IFEval instruction suite; reject unknown IDs; strict/loose parity on 541 reference responses.
- [x] **Defect B (LiveCodeBench Verification):** Replace dummy harness with real `stdin` / `functional` tester; separate contestant stdio in child subprocess; enforce ephemeral trusted supervisor receipt; prevent `sys.exit(0)` bypass; error on missing test data.
- [x] **Defect C (Source Revisions):** Pin verified upstream commits for Google Research, LiveCodeBench, and Hugging Face dataset.
- [x] **Defect D (Dataset Materialization & Real Prompts):** Materialize real datasets, populate verified task IDs, feed authentic prompts.
- [x] **Defect E (Container Security):** Enforce `--read-only`, tmpfs, unprivileged user, and orphaned container cleanup.
- [x] **Defect F (External Setup Contract & Resolution):** Strictly read-only setup planning (zero dir creation); verified installation receipts via `resolve_installed_path`; detect stale/corrupt receipts; fail-closed on missing container images.
- [x] **Defect G (Test Case Decoding):** Decode both public and private test cases supporting raw JSON and base64/zlib/pickle formats.

## 3. Required Verification Matrix
- [x] Unsupported IFEval instruction does not silently pass (`test_req1`).
- [x] Real IFEval reference results match adapter outputs on 541 tasks (`test_req2`).
- [x] Incorrect, syntactically valid LiveCodeBench solution fails (`test_req3`).
- [x] Correct LiveCodeBench solution passes with verified receipt (`test_req4`).
- [x] Premature clean process exit cannot bypass verification (`test_req5`).
- [x] Missing benchmark test data blocks scoring as `infrastructure_invalid` (`test_req6`).
- [x] Invalid Git revision fails setup without an installed receipt (`test_req7`).
- [x] Hugging Face installation actually materializes and verifies the requested data (`test_req8`).
- [x] Every frozen cohort ID resolves to exactly one verified task (`test_req9`).
- [x] Direct-model prompts exactly match the intended benchmark inputs (`test_req10`).
- [x] Docker invocation enforces declared isolation flags (`test_req11`).
- [x] All prior CLI, Harbor, persistent-suite regression tests pass (`test_req12`).
- [x] Setup planning is strictly read-only with zero directory creation (`test_req13`).
- [x] Full LiveCodeBench cohorts block without silent smoke fallback (`test_req14`).
- [x] Setup verification detects stale, incomplete, and corrupt receipts (`test_req15`).
- [x] Dataset loader decodes both public and private test cases (`test_req16`).

## 4. Full Regression Verification
- **`agent_benchmark`:** 714 passed, 10 skipped in 172.35s.
- **`benchmark_core`:** 119 passed, 1 skipped.
- **Ruff Linting:** 100% clean across all modified files.
