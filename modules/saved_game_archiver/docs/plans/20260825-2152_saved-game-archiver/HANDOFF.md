# Handoff

Feature branch: `agent/add-saved-game-archiver`

The implementation uses the module-local plan in this folder as canonical project state. The core package is ready for repository publication. After publication, the next local step is the root validation target, not independent implementation on the same branch.

Important archive invariants are documented in `00_implementation-plan.md` and `README.md`. Preserve them when diagnosing platform-specific failures.
