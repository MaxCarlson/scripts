# Official Evaluation Validity & Security Checklist

## Stage 1: Commit Pinning & Container Security
- [x] Replace IFEval source revision in `catalog.py` with `f8d6d14a1fc6eaef606d7d1e1fa4e96ee09afb81`
- [x] Replace LiveCodeBench repo revision in `catalog.py` with `28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24`
- [x] Pin Hugging Face `code_generation_lite` revision to `0fe84c3912ea0c4d4a78037083943e8f0c4dd505`
- [x] Record content hashes for `input_data.jsonl` and `test6.jsonl`
- [x] Enforce `--read-only` in `execution/container_verify.py`
- [x] Add `--tmpfs /tmp:rw,noexec,nosuid,size=64m` in `execution/container_verify.py`
- [x] Add unprivileged user enforcement (`--user 65534:65534`)
- [x] Add container name tracking and cleanup on timeout

## Stage 2: Official Google IFEval Scorer Integration
- [x] Port/integrate full Google Research IFEval instruction library (`instructions.py`, `instructions_registry.py`, `instructions_util.py`)
- [x] Implement strict instruction checking (`instruction.check_following(response)`)
- [x] Implement official 8-variant loose response checking
- [x] Reject unknown instruction IDs with `False` / validation error; never return `True`
- [x] Maintain separate strict/loose prompt and instruction metrics
- [x] Unit tests with upstream reference cases proving strict/loose parity

## Stage 3: Authentic LiveCodeBench Evaluator
- [x] Implement test harness generator supporting `stdin` (I/O) problems
- [x] Implement test harness generator supporting `functional` (call-based / LeetCode) problems
- [x] Implement canary / test count verification preventing `sys.exit(0)` bypass
- [x] Handle missing/corrupt test data by raising `infrastructure_invalid`
- [x] Implement accurate pass@1 scoring and error classification
- [x] Unit tests for wrong answer, correct answer, syntax error, and premature exit

## Stage 4: Dataset Materialization & Real Cohort Prompts
- [x] Implement Hugging Face file downloading in `external_sources/manager.py`
- [x] Implement Windows-safe sparse git checkout in `external_sources/manager.py`
- [x] Populate real task IDs in `catalog.py` for IFEval and LiveCodeBench
- [x] Wire real problem prompts and starter code in `suite.py` and direct chat dispatch
- [x] Reject empty or missing prompts before model dispatch

## Stage 5: Final Qualification & Regression
- [x] Run all 12 required tests
- [x] Run full `agent_benchmark` and `benchmark_core` test suites
- [x] Verify 100% clean Ruff checks
- [x] Commit and push to origin
