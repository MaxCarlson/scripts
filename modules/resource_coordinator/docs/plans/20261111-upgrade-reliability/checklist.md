# Checklist

- [x] Confirm isolated branch/worktree and preserve dirty primary checkout.
- [x] Verify package imports from candidate-local venv.
- [x] Resolve pytest setup errors with isolated single-suite rerun.
- [x] Localize historical WinError 206 to the task-install interval; exact call is unproven and recorded as a deployment gate.
- [x] Add durable `TASK_INSTALLING` receipt phase and recovery/reconcile/health eligibility, with rollback regression coverage.
- [x] Keep unclassified post-dispatch load errors uncertain and inhibit restart.
- [x] Block new inference/model-load admissions until explicit recovery clears an unresolved hold.
- [x] Add bounded compatible-loaded-instance preflight and fake-miner regression coverage.
- [x] Define safe event envelope and recovery integration contract without adding notification transport.
- [x] Run gateway, installation, arbitration, durable-state, credential, config, lease, and policy suites.
- [x] Run Ruff, compilation, and diff-integrity checks.
- [x] Final review and local checkpoint commit `e10ce1b55ed12874cf4f403f48a4e5303e28dbb2`.
- [ ] Isolated Windows Scheduler/UAC acceptance before production deployment.
