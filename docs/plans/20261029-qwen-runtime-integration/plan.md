# Qwen Runtime Investigation Integration Plan

**Goal:** Curate reusable Qwen runtime and Agent Benchmark improvements onto current `main`, excluding generated and sensitive experiment evidence.

**Architecture:** Build a clean integration branch from `origin/main`, apply the investigation's reusable source and sanitized documentation selectively, then validate the final tree before an authorized non-destructive merge and push.

**Global constraints:** Preserve the dirty main checkout, source investigation worktree, source branch, raw evidence and unrelated OpenCode 4096 runtime. Do not run model inference or new B1 trials. Exclude generated run artifacts, SQLite/WAL/SHM, session snapshots, raw prompts and runtime caches.

## Work plan

- [x] Audit all source-branch changed paths and inspect committed experiment records for sensitive payloads.
- [x] Port and review Agent Benchmark implementation, tests and reusable Qwen fixtures against current main.
- [x] Port runtime operations guidance, optional loopback capture tooling and concise sanitized research findings.
- [x] Add ignore rules for generated evidence while keeping small reproducibility fixtures trackable.
- [x] Run focused unit, fixture, proxy, lint/type and diff checks from the integration worktree.
- [x] Review the exact integration diff and verify excluded artifacts are absent.
- [x] Merge into and push `main` only after all gates pass; verify final local and remote state.
