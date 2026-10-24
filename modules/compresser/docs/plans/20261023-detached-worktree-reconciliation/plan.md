# Detached Compression Worktree Reconciliation Plan

> **For agentic workers:** Use `superpowers:executing-plans` when carrying out this plan. This is a review and selective-reconciliation plan; it does not authorize implementation, staging, committing, pushing, or deleting the detached worktree.

**Goal:** Determine whether any behavior or regression coverage in the detached compression worktree is missing from current `main`, and transfer only verified gaps onto a fresh worktree based on `main`.

**Architecture:** Treat `main` as the delivered source of truth and the detached worktree as read-only historical evidence. Compare its tracked, untracked, and deleted files against `main`; import no branch or whole-file snapshots. If a concrete gap is found, express it as a focused test and implement it in a new worktree created from current `main`.

**Tech Stack:** Git worktrees, PowerShell, Python, pytest, Ruff, Black.

**Scope:** `modules/compresser`, the compression adapter in `modules/mangadl`, and their plan/handoff documentation. The detached worktree is `C:\Users\mcarls\src\scripts\.worktrees\compression-inventory-estimation-20261017`.

## Current Evidence

- Canonical checkout: `main` at `a0ff1778`, clean and synchronized with `origin/main` at review time.
- Detached worktree HEAD: `b20a4292`, an ancestor of `main`; `main` is 151 commits ahead.
- Detached worktree has 49 local paths: 24 contents hash identically to `main`; 25 differ. Git reports access-denied warnings for old pytest temp directories there.
- The detached CLI rejects `estimate` with “The estimate workflow is not available yet”; current `main` dispatches to `execute_estimate_operation` in both Compresser and MangaDL.
- Current `main` already contains plan reporting, saved-plan execution, and explicit multi-format preview support. MangaDL tests include `test_preview_accepts_multiple_explicit_formats`.
- No unique runtime behavior has been confirmed in the detached changes. The remaining differing files still need a path-by-path test and documentation comparison before declaring the reconciliation complete.

## Approaches Considered

1. **Merge the detached worktree or copy its files wholesale.** Reject: it is based on an old ancestor, has uncommitted and untracked files, and its CLI disables estimate execution that exists on `main`.
2. **Cherry-pick its local work.** Reject: the local changes are not commits, and cherry-picking cannot safely preserve or distinguish the untracked files.
3. **Compare each delta and port only a proven gap.** Recommended: keeps current `main` behavior authoritative and makes any retained change independently reviewable and testable.

## Global Constraints

- Do not edit, reset, stash, stage, or delete files in the detached worktree during review.
- Do not restore old package versions, legacy flat CLI behavior, or the unavailable-estimate guard over current `main`.
- Do not run inventory or estimate operations against a production image collection as part of reconciliation.
- If code transfer is warranted, create a new isolated worktree from current `main`; preserve unrelated changes and stage only reviewed paths.
- Do not commit, push, merge, or remove the detached worktree without separate explicit authorization.

## Review Focus

- An old or untracked implementation may differ in a safety invariant even when names match; compare behavior and current tests, not just symbols.
- A regression test may be useful even when its implementation is already present; compare test cases and assertions against current module suites.
- Version, registry, and README edits may predate later API changes; keep only documentation that accurately describes current `main`.
- Workspace and saved-plan behavior must remain bounded, resumable, and read-only during plan creation; do not infer runtime readiness from old plan files.
- Windows path, hardlink, and atomic-write protections must remain covered by current tests if any underlying implementation is touched.

## File Map

- `modules/compresser/compresser/arguments.py`, `sampling_plan.py`, `plan_store.py`, `estimation_models.py`: detached operation parsing and persisted-plan code to compare with the current implementation.
- `modules/compresser/compresser/cli.py`, `estimation.py`, `measurement.py`, and `mangadl/mangadl/compress.py`: current command and execution paths; preserve the working `estimate` dispatch.
- `modules/compresser/tests/` and `modules/mangadl/tests/compress_test.py`: compare regression coverage; add tests only for a demonstrated gap.
- `modules/compresser/README.md`, `modules/mangadl/README.md`, package metadata, and help registry: documentation/metadata candidates; do not copy old version numbers.
- This plan's `STATUS.md` and `checklist.md`, plus `modules/compresser/docs/plans/HANDOFF.md`: record review and any approved follow-up.

## Tasks

### Task 1: Freeze and index the detached state

**Files:** No product files. Record findings in this plan's `STATUS.md`.

- [x] Record `main` and detached HEAD identifiers, branch state, local path count, and per-path content comparison.
- [x] Keep tracked modifications and untracked files distinguishable; no deletions were present.
- [x] Confirm the worktree remains unchanged after read-only inspection.

**Expected result:** A reproducible index of the 49 local paths without altering the detached checkout.

### Task 2: Classify the 25 differing paths

**Files:** This plan's `STATUS.md` and `checklist.md` only.

- [x] Mark the 24 content-identical paths as duplicates of `main` and leave them behind.
- [x] Compare the remaining implementation files against current signatures, invariants, and callers.
- [x] Compare detached test names and assertion counts with current Compresser and MangaDL tests; no detached-only test names or higher assertion counts were found in the five compared suites.
- [x] Classify README, package versions, and help registry differences as stale/superseded.
- [x] Record every differing path's disposition and evidence in `STATUS.md`.

**Expected result:** A path-level keep/leave-behind decision. The initial review found no confirmed unique runtime behavior; tests or docs remain candidates only if the full comparison demonstrates a gap.

### Task 3: Define a bounded transfer only if a gap exists

**Files:** New current-`main` worktree only, if needed; exact paths selected in Task 2.

- [x] No unique behavior, test scenario, or documentation needed for current `main` was found; no code transfer is required.
- [x] No implementation or new test was needed; do not create an implementation worktree for this reconciliation.
- [x] Update the current plan handoff to point to this review and the existing Task 6/7 completion evidence.

**Expected result:** Either no transfer, or a focused patch based on current `main` with an explicit test proving the gap.

### Task 4: Validate and close the reconciliation record

**Files:** Selected current-`main` paths and this plan's status/checklist/handoff.

- [x] No product code changed, so focused tests and Ruff/Black were not run.
- [x] Review confirms no files were transferred, no estimate-disable path was added to `main`, and no package version was changed.
- [x] Record exact review findings, tested commit, remaining visual checks, and detached worktree disposition in `STATUS.md`.
- [x] Leave worktree cleanup outside this plan; the original worktree remains preserved.

**Expected result:** A reviewable reconciliation report that identifies what was retained, what was left behind, and why.

## Execution Boundary

This plan authorizes review and planning only. Implementation, package installation, commits, pushes, merges, destructive cleanup, and production inventory/estimate runs require separate authorization. The detached worktree is preserved until its owner chooses what to do with it.
