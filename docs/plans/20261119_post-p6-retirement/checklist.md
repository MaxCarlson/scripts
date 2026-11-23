# Source-retirement checklist

- [x] Start a fresh branch/worktree from current scripts `main` (`c87db5b`).
- [x] Inspect historical retirement evidence without changing its branch, quarantines, manifests, raw evidence, or archive.
- [x] Reconcile all 25 unique transferred/shared directory candidates and retain the data, Gitlink, benchmark, H4, and active-consumer holds.
- [x] Verify canonical toolkit paths and source-relative file coverage for the nine toolkit-only removals.
- [x] Inventory complete selected source directories, including ignored/untracked status and links/reparse points.
- [x] Remove only the nine toolkit-only candidates with no active source consumers; preserve optional consumer and ownership/data holds.
- [x] Update Scripts Help registries and ownership tests for absent toolkit-owned source directories.
- [x] Update setup guidance that claimed all historical sources remain on disk.
- [x] Run the transferred ownership and Scripts Help tests (49 passed).
- [ ] Run broader installer/discovery/launcher and toolkit CLI ownership regressions on this branch.
- [ ] Create dependent PR B from PR #22; verify all five mxc wheels, import origins, `pip check`, and shared consumers after source removal.
- [ ] Create/push PR A and PR B after final state and tests are reviewed.
- [ ] Keep both PRs unmerged pending separate approval; preserve publication and clean-index constraints.
