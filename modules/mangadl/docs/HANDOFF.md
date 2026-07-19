# mangadl Immediate Project Handoff

Initial implementation is in progress. The user explicitly requested continuous implementation, so per-stage manual pauses are waived. Testing, documentation, and final manual production approval remain required.

No commits, merges, migrations, relocations, or legacy deletions are authorized.

Active files: [plan](plans/20260712-1540_mangadl-initial-implementation/00_implementation-plan.md), [status](plans/20260712-1540_mangadl-initial-implementation/STATUS.md), and [checklist](plans/20260712-1540_mangadl-initial-implementation/checklist.md).

Default tests use no live websites. First manual validation must use copied inputs, a new state database/archive, and a test destination.

`repair-loose` is now safe-by-default dry-run with colored in-place scanning, metadata, move, and verification progress. Apply still requires explicit `-f/--apply`.
