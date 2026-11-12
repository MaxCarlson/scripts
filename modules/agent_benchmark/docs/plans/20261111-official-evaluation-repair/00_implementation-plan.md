# Extensible Benchmark Platform — Official Evaluation Validity & Security Repair Plan

## 1. Objective

Correct critical benchmark-validity, installation, and security defects identified during independent review of the extensible benchmark implementation:
1. **Defect A (IFEval Scoring):** Replace heuristic instruction approximations with the official Google Research reference scoring implementation (strict and loose prompt/instruction accuracy). Reject unsupported instruction IDs.
2. **Defect B (LiveCodeBench Verification):** Replace dummy `pass` loop with authentic code-generation evaluation supporting standard input/output (`stdin`) and function-call (`functional`) problems. Prevent premature `sys.exit(0)` bypass and classify missing test data as infrastructure-invalid.
3. **Defect C (Source Revisions):** Replace 422-failing commit hashes with verified upstream commits for Google Research, LiveCodeBench, and Hugging Face datasets.
4. **Defect D (Dataset Acquisition & Cohort Identity):** Implement real dataset file downloading and caching for Hugging Face and Git sparse resources. Enumerate real task IDs (`ifeval-1000`..`ifeval-1540`, LCB problem IDs). Supply authentic benchmark prompts and starter code to inference models instead of placeholder strings.
5. **Defect E (Container Security Controls):** Enforce `--read-only`, tmpfs mounts, unprivileged user, and container cleanup on timeout in `execution/container_verify.py`.

---

## 2. Worktree & Branch

- **Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\agent-benchmark-official-evaluation-20261111`
- **Branch:** `fix/agent-benchmark-official-evaluation-20261111`
- **Base Commit:** `8bfd06a0` (Phase 08 delivery head)
- **Tracking:** `origin/fix/agent-benchmark-official-evaluation-20261111`

---

## 3. Repair Stages

### Stage 1: Verified Upstream Commit Pinning & Container Security Enforcement
- Update `catalog.py` with verified upstream commits:
  - `google-research`: `f8d6d14a1fc6eaef606d7d1e1fa4e96ee09afb81`
  - `LiveCodeBench`: `28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24`
  - Hugging Face `code_generation_lite`: `0fe84c3912ea0c4d4a78037083943e8f0c4dd505`
- Update `execution/container_verify.py` to enforce `--read-only`, `--tmpfs`, user limits, and timeout cleanup.

### Stage 2: Official Google IFEval Scorer Integration
- Implement the complete official instruction library and scoring logic in `benchmarks/adapters/ifeval.py`.
- Strict evaluation and 8-variant loose evaluation matching `evaluation_lib.py`.
- Explicit rejection of unsupported or malformed instruction IDs (fails, never returns `True`).
- Parity tests against upstream reference samples.

### Stage 3: Authentic LiveCodeBench Evaluator & Harness Generator
- Implement authentic problem evaluation in `benchmarks/adapters/livecodebench.py`:
  - `stdin` mode (stdin feeding + stdout capture + decimal/stripped line comparisons).
  - `functional` mode (compiled module + class `Solution` / function lookup + JSON args).
  - Anti-bypass canary verifying all test cases executed even if solution calls `sys.exit(0)`.
  - Infrastructure error classification for missing/corrupt test data.

### Stage 4: Dataset Materialization & Real Cohort Prompts
- Implement real dataset acquisition in `external_sources/manager.py` for Hugging Face and Git sparse resources.
- Populate real cohorts in `catalog.py` with verified task IDs and metadata.
- Connect real task prompts and starter code in `suite.py` and direct chat dispatch. Reject empty prompts before model dispatch.

### Stage 5: Acceptance Qualification & Delivery Report
- Add all 12 required test cases proving previous failure modes are closed.
- Verify 100% of existing regression tests pass.
- Update module documentation, plan files, and handoff.
