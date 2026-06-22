# Documentation and LLM Handoff System Summary

Last updated: 2026-06-22 06:44:27 -07:00

## Purpose of This Summary

This document is intended for an external LLM evaluating the documentation,
planning, implementation, testing, handoff, staging, and branch system being
developed here.

The evaluator should review this summary together with:

- `GLOBAL_LLM_DOCUMENTATION_INSTRUCTIONS.md`
- `README.md`
- `HANDOFF.md`
- `plans/HANDOFF.md`
- The most recent dated plan folder
- The project source, tests, worktree, and recent project-limited commits

The goal is to identify ambiguity, duplication, missing information, misplaced
content, excessive burden, weak handoff guarantees, or rules that should be
reworded or reorganized.

## Core Problem Being Solved

LLM coding work is frequently interrupted by:

- Context-window exhaustion.
- Token or usage limits.
- Switching between different LLM products.
- Starting a new conversation with the same LLM.
- A user choosing a different implementation agent.
- Work stopping midway through a feature or test cycle.

Without durable project-local records, the next LLM must reconstruct intent,
architecture, implementation state, and test state from source code, git diffs,
and user recollection. This is slow, error-prone, and places repeated context
burden on the user.

This documentation system aims to let an unfamiliar LLM resume work with close
to zero customized explanation. The user should be able to point the LLM at
`project_root` and say:

> Read the project instructions, documentation, handoffs, and active plan;
> compare them with the code and recent project commits; then continue.

The system should provide enough detail to resume accurately without forcing
the incoming LLM to consume an unnecessarily large historical narrative.

## Definition of `project_root`

`project_root` is the root directory of the specific project currently being
changed.

It may be:

- The root of a standalone git repository.
- A module/package inside a monorepo.
- A nested application inside a larger repository.

Documentation belongs in `project_root/docs/`, even when the git repository root
is higher. Git history and diffs should be limited to `project_root` when
determining project state.

## General-to-Specific Information Flow

The system deliberately moves from reusable rules to increasingly specific
state:

1. Repository-level instructions.
2. `project_root/docs/README.md`: project understanding and document map.
3. `project_root/docs/HANDOFF.md`: exact current project state.
4. `project_root/docs/plans/HANDOFF.md`: active/recent plan index.
5. Dated plan-folder `HANDOFF.md`: plan-specific resume state.
6. Plan `STATUS.md`: concise operational ledger.
7. Plan `checklist.md`: feature and stage completion truth.
8. Plan implementation and stage documents: requirements and decisions.
9. Source, tests, worktree, and project-limited commits: verification evidence.

No document should assume the reader already knows where the next layer lives.
Each layer links to the relevant more-specific documents.

## Expected Directory Structure

```text
project_root/
└── docs/
    ├── DOCUMENTATION_SYSTEM_SUMMARY.md
    ├── HANDOFF.md
    ├── README.md
    └── plans/
        ├── HANDOFF.md
        ├── master_plan.md
        ├── master_plan_checklist.md
        └── YYYYMMDD-HHMM_<descriptive-plan-name>/
            ├── 00_implementation-plan.md
            ├── 01_<stage-name>__planned.md
            ├── 02_<stage-name>__in_progress.md
            ├── HANDOFF.md
            ├── STATUS.md
            └── checklist.md
```

`master_plan.md` and `master_plan_checklist.md` are optional. The dated plan
folders are used for concrete feature implementation work.

Every created documentation directory has a `HANDOFF.md`, allowing an incoming
LLM to navigate correctly even when it begins inside a nested docs folder.

## Document Responsibilities

### Global/Repository LLM Instructions

Purpose:

- Define generic rules that can be reused across projects.
- Explain document creation, discovery, and navigation.
- Define implementation-plan, stage, checklist, testing, branch, approval, and
  commit lifecycle.
- Explain what to do when documentation conflicts with code or git evidence.

Must not contain:

- Project-specific architecture.
- Project commands.
- Current bugs.
- Active implementation details.
- Current test results.
- Project-specific constraints.

The proposed reusable text is preserved in
`GLOBAL_LLM_DOCUMENTATION_INSTRUCTIONS.md` for incorporation into global LLM
instruction files. Projects do not need a generic `docs/AGENTS.md`.

### `README.md`

Purpose:

- Give a new LLM a detailed understanding of the project without requiring it
  to infer everything from source code.
- Explain purpose, capabilities, architecture, components, data flow,
  persistence, public commands/interfaces, platform behavior, quirks, and
  aspirations.
- Explain the project documentation map and where to find current plans and
  state.
- Provide development, testing, and smoke-test commands.

Update frequency:

- Somewhat at every stage close when behavior or architecture changed.
- Thoroughly at completion of a full dated implementation plan.

### Project `HANDOFF.md`

Purpose:

- Record current project-specific resume state.
- Name the active plan, stage, and branch.
- Record staged, unstaged, uncommitted, and committed status.
- Summarize implemented and remaining work.
- Record exact automated and manual verification.
- Record known risks and next action.

This is the first project-specific document an incoming LLM reads.

### `plans/HANDOFF.md`

Purpose:

- Explain the plans directory.
- Identify the most recently active plan.
- Point to optional project-wide master planning.
- Explain how to identify an active plan when multiple plan folders exist.

### Optional `master_plan.md`

Purpose:

- Record the long-term future plan or broad roadmap for the entire project.
- This is the only document described as the project master plan.

It is optional. Its absence does not imply missing documentation.

### Optional `master_plan_checklist.md`

Purpose:

- Track entire dated folder-level implementation plans.
- Add an entry when implementation of a folder-level plan begins.
- Mark the entry complete only after that whole plan is implemented, tested,
  manually validated, committed, and merged.

It does not duplicate stage or feature details from a plan-folder checklist.

### Dated Plan Folder

Purpose:

- Contain one coherent set of feature implementations too large for one safe
  implementation/test/approval cycle.

Naming:

```text
YYYYMMDD-HHMM_<descriptive-plan-name>
```

The timestamp is local creation time and never changes.

### `00_implementation-plan.md`

Purpose:

- Define the complete intended result of one folder-level feature set.
- Specify goals, public behavior, decisions, architecture, migration,
  compatibility, failure handling, stages, and acceptance criteria.

It is not the permanent end goal of the whole program.

### Numbered Stage Plans

Purpose:

- Divide the implementation plan into cohesive execution and commit boundaries.
- State exact included features, tests, migration/version work, and acceptance
  checks for one stage.

States are represented in filenames:

- `__planned.md`
- `__in_progress.md`
- `__implemented.md`

Stage length is variable. The LLM should include as much cohesive work as it can
comfortably implement and verify without reducing quality. The user may request
larger or smaller stages after reviewing the proposal.

### Plan `checklist.md`

Purpose:

- Be the feature-level implementation and verification source of truth.
- Provide a top-level plan progress ledger.

Required top information:

- Plan creation time.
- Last update time.
- Branch name.
- Full-plan completion time or pending status.
- Merge status.
- Every stage's planned/in-progress/completed state.
- Exact completion time for completed stages.

Feature states:

```text
[ ] Feature
[x] Feature - implemented, not yet fully tested
[x] Feature - implemented and tested
```

The checklist is updated immediately after feature implementation, not only at
stage boundaries.

### Plan `STATUS.md`

Purpose:

- Provide a compact, operational summary of the plan.
- Record current stage, last completed commit, branch state, automated
  verification, manual approval, blockers, and next action.

### Plan `HANDOFF.md`

Purpose:

- Record plan-specific intricacies that are too narrow for the project handoff.
- Tell an incoming LLM exactly where this plan stopped and what to do next.

## Implementation and Verification Lifecycle

For each stage:

1. Refine the stage plan.
2. Mark it in progress.
3. Populate its checklist features.
4. Implement cohesive features.
5. Mark each implemented feature as not fully tested immediately.
6. Run the previously passing suite.
7. Investigate regressions.
8. Add focused new tests.
9. Run old and new tests together.
10. Promote checklist items to implemented and tested.
11. Run formatting, linting, compile/build checks, coverage, and smoke tests.
12. Review project-limited diffs.
13. Update README, handoffs, status, checklist, and timestamps.
14. Stage intended files.
15. By default, stop for user manual validation.
16. Commit the stage after required approval.

The user may explicitly authorize continuous stage execution. In that case the
LLM may skip waiting between stages, but must still plan, test, document, and
commit each stage separately.

## Branch Lifecycle

Each dated folder-level implementation plan has a branch:

```text
<descriptive-plan-name>-YYYYMMDD-HHMM
```

Rules:

- Create the branch when plan implementation begins.
- Record it in project and plan handoffs/checklists.
- Every stage is a commit.
- Keep unrelated plans off the branch.
- Merge only after the user validates the completed program and approves the
  merge.
- Record merge completion in the plan checklist and optional master-plan
  checklist.

Multiple partially implemented folder plans are allowed but discouraged.
Prefer finishing the active plan before starting another.

## Timestamp Requirements

- Plan folder: immutable creation timestamp in folder name.
- Implementation and stage documents: `Last edited` timestamp at the end.
- Handoffs/status/checklists/README: visible last-updated timestamps.
- Checklist: exact stage completion times and full-plan completion time.

## Verification Against Repository Evidence

Documentation is not trusted blindly.

An incoming LLM should:

- Inspect `git status`.
- Inspect recent commits limited to `project_root`.
- Compare changed files with checklist claims.
- Compare test evidence with current code.
- Resolve discrepancies and update handoffs before continuing.

This is especially important when `project_root` is nested inside a monorepo.

## Current Example State

The current runmux plan demonstrates the system:

- Plan folder:
  `plans/20260622-0551_runmux-multi-attach-input-lock-history/`
- Plan branch:
  `runmux-multi-attach-input-lock-history-20260622-0551`
- Stage 1: committed.
- Stage 2: implemented, automatically verified, staged, awaiting manual user
  approval.
- Stages 3 and 4: planned.

## Evaluation Questions

The reviewing LLM should assess:

1. Can an unfamiliar LLM reliably find the active plan?
2. Are generic and project-specific instructions separated correctly?
3. Are document responsibilities clear and non-overlapping?
4. Is any important state recorded in only one fragile location?
5. Are there contradictory rules around approval, commits, and branches?
6. Is the system too burdensome for small tasks?
7. Is stage sizing sufficiently flexible?
8. Are timestamps and completion criteria unambiguous?
9. Does the optional project master-plan system coexist cleanly with dated
   implementation plans?
10. Can the user switch LLMs midway through a stage with minimal explanation?
11. Are README, HANDOFF, STATUS, and checklist updates appropriately scoped?
12. Should any documents be merged, renamed, moved, shortened, or expanded?

The evaluator should propose concrete edits rather than only assigning a score.
