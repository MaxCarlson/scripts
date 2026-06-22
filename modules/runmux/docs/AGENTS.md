# Runmux Agent Entry Point and Temporary Global-Policy Review Copy

Last updated: 2026-06-22 06:44:27 -07:00

This project-local file exists as a runmux-specific agent entrypoint. Generic
rules are expected to come from global/repository `AGENTS.md`, `CLAUDE.md`, or
equivalent LLM instructions.

Before changing runmux:

1. Read repository root instructions and `MODULE_STANDARDS.md`.
2. Read `README.md`.
3. Read `HANDOFF.md`.
4. Read `plans/HANDOFF.md`.
5. Read the active plan's handoff, status, checklist, implementation plan, and
   current stage plan.
6. Inspect `git status` and recent commits limited to `modules/runmux/`.

The reusable policy below is retained temporarily for evaluation. The
authoritative export intended for global instruction files is:

`GLOBAL_LLM_DOCUMENTATION_INSTRUCTIONS.md`

Once the global instructions incorporate that export, this project-local file
should be reduced to only the runmux-specific entrypoint above.

## Temporary Embedded Global Policy Review Copy

The remainder of this document is a review copy and must not be treated as a
requirement that every project keep a generic `docs/AGENTS.md`.

## Required Reading Order

When entering a project with no conversation context:

1. Read all applicable repository-level instructions.
2. Identify `project_root`: the root directory of the project being changed. It
   may be the repository root or a nested project inside a larger repository.
3. Create `project_root/docs/` for substantial work if it does not exist.
4. Read `project_root/docs/README.md`.
5. Read `project_root/docs/HANDOFF.md`.
6. Inspect `project_root/docs/plans/` and identify the most recently active
   folder-level implementation plan.
7. Read that plan's `HANDOFF.md`, `STATUS.md`, `checklist.md`, implementation
   plan, and current stage plan.
8. Run `git status`.
9. Inspect recent commits limited to `project_root`, especially when it is
    nested inside a larger repository.
10. Compare documentation claims with the worktree, source, tests, and commits.

Resolve documentation/repository disagreements from evidence instead of
guessing.

## Finding the Active Plan

Do not assume the lexically newest plan folder is active.

1. Read `project_root/docs/plans/HANDOFF.md`.
2. Compare dated plan folders.
3. Inspect each likely plan's `HANDOFF.md`, `STATUS.md`, and checklist progress
   ledger.
4. Inspect file modification timestamps.
5. Inspect recent commits limited to the project path.
6. Compare implemented files and commits against checked checklist features.
7. Select the plan with current in-progress or manual-approval state.

If no plan is active, use completed plans only as historical context. If
substantial new work has no suitable active plan, create a new dated folder.

## Plan Locations

- Each feature implementation set too large for one safe cycle gets its own
  dated folder under `project_root/docs/plans/`.
- The folder contains the complete implementation plan, ordered stage plans,
  and live status information.
- The project-local plan is the implementation-facing handoff source.
- If repository policy requires canonical plans elsewhere, maintain that
  canonical index/copy and link it to the implementation-facing project
  documents. Do not omit either location.
- Do not scatter one implementation plan across unrelated documentation
  directories.

Required layout:

```text
project_root/
└── docs/
    ├── HANDOFF.md
    ├── README.md
    └── plans/
        ├── HANDOFF.md
        ├── master_plan.md
        ├── master_plan_checklist.md
        └── YYYYMMDD-HHMM_<descriptive-plan-name>/
            ├── 00_implementation-plan.md
            ├── 01_<stage-name>__planned.md
            ├── 02_<stage-name>__planned.md
            ├── HANDOFF.md
            ├── STATUS.md
            └── checklist.md
```

`master_plan.md` and `master_plan_checklist.md` are optional. Their absence is
not an error.

Every created `docs/` directory and nested planning/documentation directory must
contain a `HANDOFF.md`. It may be concise when it points to authoritative parent
documents, but it must identify the folder's purpose, current state, required
reading, and next action.

Plan folder names preserve their local creation time:

```text
YYYYMMDD-HHMM_<descriptive-plan-name>
```

Never replace the creation timestamp later.

## Plan Naming and Timestamps

- Use `00_implementation-plan.md` for a folder-level implementation plan.
- Number implementation stages in execution order with two digits.
- End stage filenames with exactly one status:
  - `__planned.md`
  - `__in_progress.md`
  - `__implemented.md`
- Every implementation plan and numbered stage plan must end with:

```text
Last edited: YYYY-MM-DD HH:MM:SS UTC_OFFSET
```

- Update that timestamp whenever the plan's content or status changes.
- Use the local timezone of the active development environment.
- `STATUS.md` must also identify when it was last updated.

## Optional Project Master Plan

`project_root/docs/plans/master_plan.md`, when present, is the long-term future
plan for the entire project. Pair it with
`project_root/docs/plans/master_plan_checklist.md`.

The master-plan checklist tracks folder-level implementation plans:

- Add a folder-level plan entry when implementation begins.
- Mark it complete only after the entire folder-level plan is implemented,
  tested, manually approved, committed, and merged.
- Record its folder path, branch, start time, completion time, and merge commit
  when available.
- Do not duplicate the folder plan's feature/stage checklist.

Multiple folder-level plans may be partially complete concurrently, but this is
non-ideal. Direct work toward finishing the active folder-level plan so only one
is partially complete whenever practical.

## Folder-Level Implementation Plan

A folder-level implementation plan is one coherent feature set. It is not the
project master plan or permanent end goal. Independent feature sets receive
independent dated folders.

## Folder-Level Implementation Plan Requirements

`00_implementation-plan.md` must define:

- User-visible goals and success criteria.
- Public CLI/API/data-format changes.
- Important behavior and defaults.
- Architecture and data-flow decisions.
- Compatibility and migration requirements.
- Failure modes and recovery expectations.
- Ordered implementation stages.
- Automated and manual acceptance criteria.
- Version and commit boundaries when the repository uses versioning.

The implementation plan is the intended result of this feature set only.
Do not silently remove or redefine requirements in a stage plan. Record any
approved change explicitly.

## Stage Planning

Before implementing a stage:

1. Create or refine its numbered plan document.
2. Mark its filename and internal status `in progress`.
3. Identify the exact features implemented in this stage.
4. Add those features to the active plan folder's `checklist.md`.
5. Include expected tests, version changes, migration work, and acceptance
   checks.
6. Update `STATUS.md` with the current stage and first concrete action.
7. Update all edited plan timestamps.

Do not begin implementation until the stage checklist exists.

## Stage Sizing

Stage length is intentionally variable.

- By default, the LLM chooses stage scope while writing the stage plan.
- Include as many related features as can be comfortably implemented, reviewed,
  tested, documented, and manually validated without compromising quality.
- Prefer cohesive behavior slices over arbitrary line-count or time limits.
- Split work when concurrency, migrations, terminal behavior, public interfaces,
  or testing risk would make one cycle difficult to reason about.
- The user may request longer or shorter stages after reviewing a proposed stage
  plan; update the stage plan and checklist before implementation.

## Checklist Rules

The active plan folder's `checklist.md` is its feature-level source of truth.

Its top section must contain:

```text
Plan created: YYYY-MM-DD HH:MM:SS UTC_OFFSET
Full plan completed: pending

- [x] Stage 1 - completed YYYY-MM-DD HH:MM:SS UTC_OFFSET
- [ ] Stage 2 - in progress
- [ ] Stage 3 - planned
```

Record each stage's exact completion time. Record the full plan completion time
after all stages are approved and committed.

Use these states:

```text
[ ] Feature
[x] Feature - implemented, not yet fully tested
[x] Feature - implemented and tested
```

Rules:

- Separate checklist sections by numbered stage.
- Add all known stage features during stage planning.
- Immediately after implementing each feature, mark it implemented but not yet
  fully tested.
- Do not mark a feature tested based only on a targeted test.
- After all previously passing tests and all new stage tests pass together, add
  an `Implemented and tested` heading above that stage and promote completed
  features to implemented and tested.
- Keep manual approval and commit state as separate unchecked items.
- If a feature is partial or failing, leave it unchecked or describe the exact
  incomplete state.

Update the checklist more frequently than once per stage. It should remain
accurate if the active LLM disappears immediately after any code edit.

## Implementation Cycle

For each stage:

1. Plan the stage and populate its checklist.
2. Implement one cohesive feature.
3. Immediately update the checklist to implemented, not fully tested.
4. Continue until the planned stage features are implemented.
5. Run the previously passing tests before changing test expectations.
6. Investigate regressions; do not dismiss them as expected without evidence.
7. Add focused tests for new behavior, edge cases, and failure paths.
8. Run old and new tests together.
9. Promote checklist items only after the complete test gate passes.
10. Run formatter check, linter, compile/build check, and coverage.
11. Review the complete diff for unintended behavior and unrelated files.
12. Perform safe automated smoke tests where practical.
13. Update stage, status, checklist, verification evidence, risks, and next
    action.
14. Stage only the intended files.
15. Do not commit yet.
16. Stop and give the user precise manual test instructions.
17. Wait for explicit user approval.
18. If the user reports a problem, fix the current stage, rerun verification,
    restage, update docs, and request another manual test.
19. After explicit approval, mark the stage implemented, update timestamps and
    status files, commit, and confirm a clean worktree.
20. Only then plan and begin the next stage.

The stop-and-request-approval behavior is the default. If the user explicitly
instructs the LLM not to stop between stages, the LLM may continuously implement
stages. Automated verification, per-stage commits, documentation updates, and
all other gates still apply. Record the user's continuous-execution instruction
in project and plan handoffs.

## Automated Verification

Each stage must preserve all tests that passed before the stage began and add
reasonable coverage for new code.

Record:

- Exact commands run.
- Pass/fail counts.
- Coverage result.
- Relevant platform and smoke-test result.
- Any test that could not be run and why.

Do not report a stage complete when required checks are still failing.

## Manual Approval Gate

By default, every stage ends at a user-controlled gate:

- Code and documentation are staged but uncommitted.
- The assistant reports what changed and how to test it manually.
- The assistant waits for explicit approval.
- Approval is required before committing.
- Approval is required before beginning the next stage.

Never treat silence, automated tests, or an ambiguous response as approval.

The user may explicitly waive per-stage pauses and authorize continuous stage
execution. This waives only the wait between stages, not testing, documentation,
stage commits, final program validation, or branch merge approval.

## Plan Branch Lifecycle

Each folder-level implementation plan uses its own branch.

- Create the branch when implementation of the plan begins.
- Name it from the plan name with its creation timestamp as suffix:

```text
<descriptive-plan-name>-YYYYMMDD-HHMM
```

- Record the branch in the plan checklist, plan handoff, and project handoff.
- Every stage is one commit after its required verification and approval rules.
- Do not mix unrelated folder-level plans on the branch.
- Do not merge the plan branch until the user validates the completed program
  or explicitly approves the merge.
- Record the merge result in the plan checklist and optional
  `master_plan_checklist.md`.
- If a plan was already started on another branch before this rule existed,
  create/switch to the required plan branch before the next commit and document
  the exception.

## Status and Handoff Document

Every active planning folder must contain `STATUS.md`.

Keep it concise and operational:

- Last-updated timestamp.
- Current stage.
- Commit hash of the last completed stage.
- Implemented features.
- Unimplemented or partially implemented features.
- Automated verification results.
- Manual approval state.
- Staged/uncommitted file state.
- Known bugs, risks, and assumptions.
- Exact next action.

An unchecked item must clearly mean unfinished. Do not rely on prose elsewhere
to explain that a checked item is actually partial.

Before pausing or yielding to another LLM:

1. Update `STATUS.md`.
2. Update the active plan folder's `checklist.md`.
3. Update timestamps in edited plan files.
4. Record the latest tests and results.
5. Record whether files are unstaged, staged, or committed.
6. Record the next command or code action.

The desired handoff experience is that the user only needs to say: read the
repository instructions and the planning/checklist documents, then continue.

## README, AGENTS, and HANDOFF Roles

- `README.md` is the detailed project introduction. It explains the program's
  purpose, features, architecture, data locations, lifecycle, platform quirks,
  aspirations, active and recent implementation plans, and verification
  commands.
- Global/repository LLM instructions contain generalized operating rules:
  planning, checklist transitions, testing, approval gates, commits, timestamps,
  and handoffs.
- `HANDOFF.md` contains current project-specific resume information that cannot
  be generalized: active stage, exact implementation state, staged files,
  test evidence, known risks, and next action.
- `STATUS.md` is one implementation plan's compact progress ledger.
- A plan folder's `checklist.md` is that plan's feature-level
  implementation/test ledger.

Update policy:

- Update `HANDOFF.md`, `STATUS.md`, and the checklist throughout active work.
- Update `README.md` at every cycle close with relevant behavior/architecture
  changes.
- Perform a detailed README review at completion of every folder-level
  implementation plan.
- Update global/repository LLM instructions only when reusable workflow policy
  changes.
- Preserve concise links between documents so incoming LLMs can choose depth
  without reading irrelevant history.

## Git Discipline

- Preserve unrelated user changes.
- Stage only files belonging to the current stage.
- Never commit before user manual approval.
- Use the repository's required version bump and commit format.
- After an approved commit, verify the worktree state before starting another
  stage.
- If unrelated changes prevent an isolated commit, document them and ask the
  user rather than reverting them.

## Documentation Maintenance

- Keep `README.md` focused on project-specific understanding and documentation
  navigation.
- Keep global/repository LLM instructions authoritative for generic behavior.
- Keep `STATUS.md` focused on immediate resume state.
- Keep each plan folder's `checklist.md` focused on that plan's feature
  implementation/test state.
- Keep project master plans, folder-level implementation plans, and stage plans
  focused on their respective requirements and decisions.
- Update links whenever plan files are renamed for status transitions.

Last edited: 2026-06-22 06:44:27 -07:00
