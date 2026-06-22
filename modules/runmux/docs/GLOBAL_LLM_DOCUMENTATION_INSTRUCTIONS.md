# Proposed Global Documentation, Planning, and Handoff Instructions

Last edited: 2026-06-22 06:44:27 -07:00

This project-agnostic instruction source is intended to be merged into global
or repository-level `AGENTS.md`, `CLAUDE.md`, Gemini instructions, Copilot
instructions, or equivalent LLM configuration.

## Project Root

`project_root` is the root of the project being changed. It may be a repository
root or a nested project inside a monorepo.

For substantial work, project documentation belongs under:

```text
project_root/docs/
```

## First-Time Entry

1. Read applicable global and repository instructions.
2. Identify `project_root`.
3. Read `project_root/docs/README.md`.
4. Read `project_root/docs/HANDOFF.md`.
5. Read `project_root/docs/plans/HANDOFF.md`.
6. Find the active dated implementation-plan folder.
7. Read its `HANDOFF.md`, `STATUS.md`, `checklist.md`,
   `00_implementation-plan.md`, and current stage plan.
8. Run `git status`.
9. Inspect recent commits limited to `project_root`.
10. Compare documentation claims with code, tests, staged changes, and commits.

Resolve discrepancies from evidence rather than guessing.

## Documentation Structure

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

Every created documentation directory has a `HANDOFF.md`.

`master_plan.md` and `master_plan_checklist.md` are optional.

## Document Responsibilities

### Project README

`project_root/docs/README.md` explains:

- Project purpose, audience, capabilities, and aspirations.
- Architecture, components, and data flow.
- State/configuration locations.
- Public interfaces and commands.
- Platform behavior and quirks.
- Development and test commands.
- Documentation map.
- Active and recent plans.

Update it at relevant stage closes and review it thoroughly when a full
folder-level plan completes.

### Project Handoff

`project_root/docs/HANDOFF.md` records:

- Active plan, stage, and branch.
- Last completed stage and commit.
- Staged, unstaged, and uncommitted state.
- Implemented and remaining work.
- Test and manual-validation evidence.
- Known risks and exact next action.

### Plans Handoff

`project_root/docs/plans/HANDOFF.md` identifies active and recent plans and
explains how to navigate them.

Do not assume the lexically newest folder is active. Confirm using handoffs,
status, checklist state, timestamps, staged changes, and project-limited commits.

### Optional Project Master Plan

`project_root/docs/plans/master_plan.md` is the long-term future plan for the
whole project.

`master_plan_checklist.md` tracks entire dated folder-level plans:

- Add an entry when a folder-level plan begins.
- Record folder, branch, and start time.
- Mark complete only after the whole plan is implemented, tested, validated,
  committed, and merged.
- Record completion time and merge commit.
- Do not duplicate stage or feature details.

Multiple partial folder plans are permitted but discouraged. Prefer finishing
the active plan first.

### Folder-Level Implementation Plan

Large feature sets receive:

```text
project_root/docs/plans/YYYYMMDD-HHMM_<descriptive-plan-name>/
```

The timestamp is local creation time and never changes.

`00_implementation-plan.md` defines one coherent feature set, not the project's
permanent end goal. It includes:

- Goals and success criteria.
- Included/excluded behavior.
- Public interface and data changes.
- Decisions, defaults, architecture, and data flow.
- Compatibility and migration.
- Failure handling.
- Ordered stages.
- Automated/manual acceptance.
- Version and commit boundaries.

### Plan Checklist

The top of `checklist.md` records:

```text
Plan created: YYYY-MM-DD HH:MM:SS UTC_OFFSET
Last updated: YYYY-MM-DD HH:MM:SS UTC_OFFSET
Full plan completed: pending
Plan branch: <branch>
Plan branch merged: pending

- [x] Stage 1 - completed YYYY-MM-DD HH:MM:SS UTC_OFFSET
- [ ] Stage 2 - in progress
```

Feature states:

```text
[ ] Feature
[x] Feature - implemented, not yet fully tested
[x] Feature - implemented and tested
```

Populate stage features before implementation. Update each feature immediately
after coding. Promote to tested only after old and new tests pass together.

### Status and Plan Handoff

`STATUS.md` is the compact operational ledger. The plan `HANDOFF.md` records
plan-specific decisions, current resume state, blockers, and next action.

## Stage Sizing

Stage length is variable.

- The LLM selects the largest cohesive scope it can comfortably implement,
  review, test, document, and validate without reducing quality.
- Split when risk, migrations, concurrency, terminal behavior, public
  interfaces, or testing complexity becomes difficult to reason about.
- The user may request longer or shorter stages after reviewing a proposed
  stage plan.

## Stage Lifecycle

1. Refine and mark the stage plan in progress.
2. Populate its checklist section.
3. Update handoff/status documents.
4. Implement cohesive features.
5. Mark each as implemented but untested immediately.
6. Run the previously passing suite.
7. Investigate regressions.
8. Add focused tests.
9. Run old and new tests together.
10. Promote checklist states.
11. Run formatting, linting, build/compile, coverage, and smoke checks.
12. Review the project-limited diff.
13. Update README, handoffs, status, checklist, and timestamps.
14. Stage intended files.
15. By default, stop for user manual validation.
16. Commit the stage after required approval.

The user may explicitly authorize continuous execution. This skips only the
pause between stages; planning, tests, documentation, and per-stage commits
remain required.

## Plan Branch Lifecycle

Each folder-level plan uses:

```text
<descriptive-plan-name>-YYYYMMDD-HHMM
```

- Create/switch to it when plan implementation begins.
- Record it in handoffs and checklist.
- Every stage is one commit.
- Keep unrelated plans off the branch.
- Merge only after the user validates the completed program and approves merge.
- Record merge state in the plan checklist and optional master-plan checklist.

## Timestamps

- Plan folder: immutable creation timestamp.
- Implementation/stage plans: `Last edited` at the end.
- README/handoffs/status/checklist: visible last-updated timestamps.
- Checklist: exact stage and full-plan completion times.

## Default Manual Approval

By default, verified stage changes are staged but uncommitted while waiting for
user manual testing. Silence is not approval.

The user may explicitly waive per-stage pauses. Final branch merge still
requires user program validation unless explicitly overridden.

## Before Any Stop

Update:

1. Project handoff.
2. Plan handoff.
3. Plan status.
4. Plan checklist.
5. Edited timestamps.
6. Test evidence.
7. Git/staging state.
8. Risks and exact next action.

The goal is for a new LLM to resume from `project_root` without customized
history from the user.
