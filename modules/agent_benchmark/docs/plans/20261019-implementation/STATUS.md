# Status

2026-10-19: Phase 1c pipeline implementation complete and tested offline. Live acceptance pending existing runtime/model ID and explicit execution authorization. No real worker run claimed.

Workspace C:/Users/mcarls/src/scripts-agent-benchmark; branch agent/agent-benchmark.
- 072683f1: non-fast-forward merge of full core history through EXACT a185621552368e7ed4442659750a64ae7986ecda.
- f973ee67: reproduced/fixed outer core wrapper shadowing; canonical class identity retained.
- 5d9637b0: canonical results, strict scoring, persistence/core reports, guarded CLI, persistent dispatch blocking, packaged task and terminal semantics.
- 2cfd66fd: required narrow help-catalog registration and scripts_help metadata version bump.

Preserved c299e1b2 corrective behavior. Source-checked terminal StructuredOutput semantics at OpenCode v1.19.3; tightened ambiguous structured/tool-call and multi-assistant ordering cases. Native read-only review found preparation-before-journal failure could leave an unrecoverable receipt; reproduced/fixed before commit. Cleanup checks exact recorded handle/workspace ownership. Runtime imports work normally and with modules/ first for both packages.

Verification:
- Agent pytest -q -rs: 104 passed, 2 skipped (Windows symlink privilege), no warnings after explicitly asserting the expected unresolved-worker warning.
- Core pytest -q -rs: 80 passed; Ruff clean; Mypy clean (9 source files).
- Narrow help registry structure: 2 passed, 40 deselected.
- Built both wheels, extracted to isolated module-local directory, imported both canonical packages and ran read-only plan against bundled fixture from an unrelated cwd: passed. Installed agent-bench --version: 1.0.0.
- Actual virtualenv uses editable packages from this worktree: agent-benchmark 1.0.0, benchmark-core 0.1.1.

No shared service started/reconfigured. The user explained the prior timeout was expected with OpenCode stopped. Live benchmark authorization/model-ID request is pending. Once supplied and server running: execute one py-grep-smoke, verify S1, confirm one canonical result and reports; record actual evidence and telemetry limitations. No need to rerun broad unrelated tests.

Routine fixture expansion can be handed to Gemini Flash using the existing task/verifier boundary, preserving all lifecycle and scoring rules. Real runtime integration failures return to Sol Medium. M1 repeated-model acceptance and M2 coordinator comparisons remain unimplemented.
