# Post-Migration Linux Qualification Repair Plan

> **For agentic workers:** Use focused test-first changes and track each validation gate below.

**Goal:** Make the Linux shared-package qualification workflow validate the checked-out Gitlinks and prove migrated private commands plus the public procparsers package work after bootstrap.

**Architecture:** Add a small standard-library helper that reads expected commit IDs from Gitlink entries in parent trees and compares them with checked-out repositories. Cover matching, mismatch, and missing-Gitlink cases using disposable local Git repositories, then call the helper and exercise installation/import/CLI behavior in the workflow.

**Tech Stack:** GitHub Actions YAML, Python 3.12, pytest, Git CLI, Bash.

**Spec:** User assignment dated 2026-11-24, “Linux qualification repair” and “Windows root-setup gate.”

## Global constraints

- Keep scripts/main and primary-checkout untracked data unchanged.
- Preserve scoped SSH authentication, host-key verification, and fail-closed private-submodule behavior.
- Do not merge, publish packages, change credentials/profile/system configuration, delete worktrees, or run real downloads.
- Leave PRs #31 and #32 untouched.

## Tasks

- [ ] Add Gitlink validation regression tests and observe them fail before implementation.
- [ ] Implement the Gitlink helper and replace both workflow hardcoded commits with parent-tree-derived checks.
- [ ] Extend Linux post-bootstrap checks for procparsers and private CLI launchers from an unrelated directory with PYTHONPATH cleared.
- [ ] Run focused static/regression checks, push the feature branch, and dispatch Linux qualification if authorized connectivity permits.
- [ ] Inspect safe Windows root-setup isolation and record the blocker/recommendation without changing the profile or system settings.
