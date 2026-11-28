# Status

- Branch: `fix/llmd-252-mixed-schema-recovery`
- Base: `5bff63a704b4fe9ea2eefcb87df85868a35fab26` (`origin/main` at start)
- Worktree: `C:\Users\mcarls\src\scripts\.worktree\llmd-252-mixed-schema-recovery`
- State: Implementation and offline qualification complete; task-branch publication is pending.
- Safety: Production registry/install and live providers untouched.
- Historical reproduction: actual 2.1.2 source `4ad834c3233f348b443fe14d377a908b2d95a90f` prepared a schema-3 pending Claude launch, ran a harmless Python provider stand-in, then actual 2.5.0 source `4dcfd482d35102815c3eb89802fc697e620a71e3` migrated the disposable registry to schema 4. The old writer failed in `record_process_observation` with `registry_rebuild_required` before exit bookkeeping completed.
- Implemented: runtime schema-transition guards on SQLite write and rebuild paths; read-only package/PATH/schema preflight in `agents doctor`; exact pending recovery in `llmd continue` with stopped-session and reservation revalidation; exact interrupted terminal-launch reconciliation; profile/workflow/cwd preservation.
- Final focused verification: `python -m pytest tests\mixed_version_recovery_test.py -q --basetemp=C:\llmd57\v252-validation\agent-focused-final2` — **16 passed**.
- Final full verification: `python -m pytest tests -q -n 8 --basetemp=C:\llmd57\v252-validation\agent-xdist-final` with `LLMD_TEST_TMP_ROOT` set to that disposable path — **600 tests passed** (xdist reached 100%, exit 0).
- `scripts_help`: `python -m pytest tests -q --basetemp=C:\llmd57\v252-validation\help` — **72 passed, 1 skipped**. Registry validation: **87/90 entries OK**; `diff`, `func_replacer`, and `rgcodeblock` have import errors because their modules are absent from this environment.
- Static/CLI checks: Ruff passed; `git diff --check` passed; package, module, and scripts_help registry versions all report **2.5.2**; `agents doctor --help` exposes read-only package/schema preflight options. Full `llmd --help` succeeded.
- The schema-3 to schema-4 historical reproduction used actual v2.1.2 and v2.5.0 source with a harmless subprocess; it left only disposable test data.
- Remaining: final task-only diff review, commit, and push. No merge, install, production registry access, or provider execution is authorized.
