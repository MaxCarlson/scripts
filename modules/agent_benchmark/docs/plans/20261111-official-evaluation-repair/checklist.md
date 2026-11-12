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
- [x] Unit tests with upstream reference cases proving strict/loose parity on 541 tasks

## Stage 3: Authentic LiveCodeBench Evaluator & Isolated Supervisor
- [x] Implement test harness generator supporting `stdin` (I/O) problems
- [x] Implement test harness generator supporting `functional` (call-based / LeetCode) problems
- [x] Execute candidate code strictly in child subprocess (`solution.py`) with piped stdio
- [x] Generate ephemeral `receipt_nonce` trusted supervisor receipt preventing `sys.exit(0)` and marker forgery bypasses
- [x] Handle missing/corrupt test data by raising `infrastructure_invalid`
- [x] Implement accurate pass@1 scoring and error classification
- [x] Unit tests for wrong answer, correct answer, syntax error, premature exit, and marker forgery

## Stage 4: Dataset Materialization & Real Cohort Prompts
- [x] Implement Hugging Face file downloading in `external_sources/manager.py`
- [x] Implement Windows-safe sparse git checkout in `external_sources/manager.py`
- [x] Populate real task IDs in `catalog.py` for IFEval and LiveCodeBench
- [x] Wire real problem prompts and starter code in `suite.py` and direct chat dispatch
- [x] Decode both public and private test cases (supporting raw JSON and base64/zlib/pickle)
- [x] Reject empty or missing prompts before model dispatch
- [x] Enforce that full benchmarks (`lcb-v6-direct-100`, `lcb-v6-direct-full`) never silently fall back to smoke data

## Stage 5: External Setup Contract Hardening
- [x] Setup planning is strictly read-only (`get_store_layout` vs `ensure_store_layout`)
- [x] Resolve resources via verified installation receipts (`resolve_installed_path`)
- [x] Fail closed on container images when Docker image is unavailable without writing fake receipts
- [x] Declare `env_requirements=("numpy",)` for `lcb-scorer-env`
- [x] Setup verification detects stale, incomplete, and corrupt receipts

## Stage 6: Final Qualification & Regression
- [x] Run all 16 required qualification tests in `official_evaluation_repair_test.py`
- [x] Run full `agent_benchmark` (714 passed, 10 skipped) and `benchmark_core` (119 passed, 1 skipped) test suites
- [x] Verify 100% clean Ruff checks
- [x] Reconcile with latest origin/main
- [x] Commit and push to origin task branch
