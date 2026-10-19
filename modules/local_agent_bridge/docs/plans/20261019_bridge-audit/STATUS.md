# Bridge audit

Goal: independently review the 2.0.0 installer, runtime management, bootstrap hooks
and benchmark claims, and implement confirmed fixes plus requested CLI naming/help.

Workspace: scripts, branch main (initially clean; pscripts excluded from status).
No delegation, host installation, commits or external writes are authorized here.

- [x] Read module instructions, handoffs, source and existing tests.
- [x] Baseline: 26 passed, 1 skipped outside sandbox; sandbox temp ACLs block pytest.
- [x] Read-only host check: approval_policy conflict, two pending skill updates.
- [x] Read-only readiness: LM Studio HTTP 200; OpenCode 4096 connection refused.
- [x] Reproduce confirmed defects with isolated regression tests.
- [x] Fix CLI naming/help, alias/config preservation and bootstrap argument/dry-run handling.
- [x] Validate receipt/runtime interaction, backup integrity, packaging and documented permissions.
- [x] Run focused tests and read-only host/bootstrap checks: 47 passed, 1 privilege skip;
  wheel hashes/assets/entry points and extracted-wheel lifecycle passed.
- [x] Correct benchmark completion claims and record current host state in ../../AUDIT.md.
- [x] Final diff/status review; no whitespace errors, no staged changes.
  Live Codex config and receipt SHA-256 fingerprints match the initial audit.

Next: final report. Host apply and live worker trials remain separate actions.
Preserve host on-request policy and all legacy dotfiles links. Saved host plan
has no conflicts and three pending updates. No commit, push, merge or delegation.
