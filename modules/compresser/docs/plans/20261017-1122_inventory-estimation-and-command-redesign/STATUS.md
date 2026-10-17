# Status

2026-10-17 execution update: Tasks 1 through 4 are implemented on branch
`compression-inventory-estimation-20261017`. The original checkout at
`C:\Users\mcarls\src\scripts` now has this branch checked out and contains the current
Tasks 3/4 changes. A detached copy remains at
`.worktrees/compression-inventory-estimation-20261017` as a safety copy. Earlier local
planning edits are preserved in the named Git stash
`preserve pre-feature planning edits before feature checkout`. The first stage was
already pushed; Tasks 3/4 are authorized for commit and push after verification. No
production operations occurred.

User requested a stronger-model design pass before switching to Luna Medium/High.
That pass is recorded in [execution-review.md](execution-review.md), including exact
sampling/arithmetic/budget/resume rules and mandatory escalation checkpoints. Recommended
continuation is Luna High; stop before Tasks5/8 and request stronger model. Task7
crash/resume review and final review also need stronger-model signoff.

Stronger-model independent work: hardened artifact-container ownership with Windows
reparse, hardlink, malformed identity and concurrent-control tests; uses the existing
Python>=3.10 link primitive. Added independent Fraction/Decimal numerical oracles for
Tasks5/8 (5 tests pass). They do not deliver the production estimator. Combined focused
ownership/reference tests29 pass.

Stage validation: full compresser356 passed/1 skipped; MangaDL317 passed; the focused
UI fixture suite12 passed. Ruff check passed for all 14 changed/new Python paths and
`git diff --check` passed. Black formatting was applied to those Python paths; a later
Black check stalled in its Windows worker process and was interrupted. Earlier stronger
pass had Black120 passing before the final test-only fixture addition. The README now
documents target-named workspaces and rejects file-valued `-I`; old SQLite-path examples
were corrected. The Windows resize/color/manual reader gate remains pending.

Task 3 replaces the public flat CLI with shared operation subcommands, frozen normalized
options, clean-break argument rejection, MangaDL adapter routing and updated help/docs.
Task 4 removes profile-driven sampling advice and adds deterministic bounded plans,
immutable recipe/population identities, atomic plan persistence, mismatch checks, and
shared text/Markdown/JSON plan reporting. Plan creation reads existing inventory only;
it does not open source images, codecs or the trial database.

Validation: compresser402 passed/1 skipped; MangaDL full suite passed; scripts-help55
passed; Ruff and `git diff --check` passed. Focused persistent-plan checks12 passed,
including atomic interruption, serialized updates, hardlink rejection, recipe/seed/budget/
runtime mismatch and changed-population refusal. Windows resize/color and reader review
remain pending.

Next: commit and push Tasks 3/4 as authorized. Then stop before Task 5 and ask the user
to switch back to Sol Medium for the fixed-design numerical estimator. Task 7 resume/crash
review, Task 8 sequential certification, the Windows visual gate and final whole-change
review remain stronger-model/manual gates.

Historical planning status follows; superseded by the update above.

2026-10-17: Planning documents created against 8cdc7fe on
compression-ui-color-and-stats-20261017. Design/CLI/implementation plan self-reviewed;
awaiting user written review and choice of native versus subagent-driven execution.
User requests a clean breaking replacement, no compatibility layer, and explicitly
requires preserving the polished real-time/report UI. No implementation or tests run.

Decisions: separate inventory from plan; new .mangadl/<target> workspace; operation CLI;
bounded exact-recipe estimator first; certified adaptive accuracy and quality curves
separate checkpoints. No automatic migration/deletion or production operations.

Supersedes unimplemented historical Plan03 P8 and repair Task6 design for this scope;
historical completed work remains evidence, not permission to execute old tasks.
Previous workspace/report delivery is complete; its manual terminal/reader checks
remain outstanding and are not cleared by this planning task.

Next: user reviews design.md, cli.md and plan.md; amend decisions, then execute only
after review/authorization. First implementation checkpoint is workspace layout plus
UI baseline, followed by shared CLI replacement. Do not start estimator code prematurely.
