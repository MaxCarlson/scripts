# Status

2026-10-17 execution update: Tasks 1 and 2 are complete in the isolated worktree
`.worktrees/compression-inventory-estimation-20261017` on branch
`compression-inventory-estimation-20261017`. Local main was fast-forwarded to 8cdc7fe
before this branch was created. User authorized a first-stage commit and push.
No installs or production operations occurred.

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

Next: commit and push this authorized first stage. Then continue Tasks 3 and 4 on Luna
High and stop before Task 5 for Sol Medium review, as specified in execution-review.md.
Task 7 resume behavior, the manual Windows visual acceptance, and final whole-change
review also remain stronger-model/manual gates.

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
