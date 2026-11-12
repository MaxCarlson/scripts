# Part 1 Integration Checklist

- [x] Refresh remotes and verify candidate ancestry.
- [x] Compare changed paths between current `origin/main` and RC candidate; no overlap at the common ancestor.
- [x] Create isolated RC integration worktree from `origin/main`.
- [x] Merge the published RC candidate without changing main or its source branch.
- [x] Validate maintenance/restoration, durable state, admission, gateway, supervision, CLI, installation, and lifecycle suites; reproduce/classify the known baseline failure.
- [x] Integrate Mining H3 and validate package/client compatibility against this exact RC candidate.
- [x] Complete operational readiness ledger.
- [x] Commit and push only integration branches; verify clean state and remote SHAs.
