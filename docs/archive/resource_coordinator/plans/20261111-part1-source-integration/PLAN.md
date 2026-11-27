# RC and Mining Part 1 Integration Plan

**Goal:** Produce separate, published integration candidates for the validated RC v0.14 maintenance/restoration source and Mining H3 client, with a clear operational acceptance ledger.

**Architecture:** Create isolated branches from freshly fetched mainline refs, merge the published feature histories without rewriting them, validate the combined packages with explicit source imports, and record cross-repository and operational evidence. Production acceptance remains separate.

**Scope:** Part 1 only. No CLI compaction, recovery redesign, deployment, production service operation, GPU access, or optimizer algorithm changes.

## Checklist

- [x] Inspect current refs, worktrees, dirty checkouts, and published candidates.
- [x] Preserve the original RC worktree and roadmap documents.
- [x] Merge the RC v0.14 feature into an isolated branch based on current `origin/main`.
- [ ] Run focused RC integration regressions and static checks.
- [ ] Create the Mining integration branch based on current `origin/master` and preserve the H3 history.
- [ ] Run targeted Mining regressions and cross-repository candidate compatibility checks.
- [ ] Record operational acceptance gates and exact evidence.
- [ ] Review candidate diffs, commit evidence, push both integration branches, and verify remote refs.

## Review Focus

- Durable maintenance/recovery state remains fail-closed across mainline integration.
- H3 client release and registration contracts remain compatible with integrated RC handlers.
- Untracked roadmap documents and unrelated dirty work remain untouched.
- No production service, miner, GPU, LM Studio, WSL, credentials, or Scheduled Tasks are accessed or changed.
