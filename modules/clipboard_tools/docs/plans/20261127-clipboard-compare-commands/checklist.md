# Clipboard compare commands checklist

- [x] Confirm the old `cld` implementation, snapshot behavior, and comparison semantics.
- [x] Add regression coverage for concise summaries, pairwise comparisons, `fd` expansion, and dispatch.
- [x] Preserve the existing full diff implementation under `cldd`.
- [x] Register `cld`, `cldd`, `comp`, and `compd`; bump `clipboard_tools` to 2.0.0.
- [x] Document command syntax and character-count semantics.
- [x] Run clipboard tests and verify generated wrappers in an isolated environment.
- [x] Run Ruff and Black checks on changed Python files.
- [ ] Commit and push the feature branch.
- [ ] Merge only if the user explicitly authorizes merging this feature.

## Verification notes

- All 46 clipboard module tests passed.
- The four new command executables and generated `bin/comp.cmd` proxy were verified in the isolated worktree.
- Real `comp fd AGENTS.md` resolved four files and compared all six pairs.
