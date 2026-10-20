# EXP_20261020_061135 forensic fixes

## Goal and baseline

Fix final report regeneration, remove false condition splits from semantically irrelevant permissions,
make only runtime-proven pre-mutation edit failures non-uncertain, and improve the model-neutral smoke
prompt. Preserve every artifact and trial verdict from EXP_20261020_061135. No inference.

Baseline was latest pushed origin/main `cb82930cde91c9c20645bacc29337110f84c5bcb`, isolated at
`agent/benchmark-exp-061135`. The branch was advanced from `27e85852` to `cb82930c` with the
documentation-only TermDash commit. Older checkout `agent/agent-benchmark` has unrelated untracked
evidence; it remains untouched.

## Confirmed investigation

- `render_experiment_comparison_csv` calls `ExperimentComparison.from_dict` while that name is imported
  only under TYPE_CHECKING. This is the NameError recorded in experiment-failure.json.
- All five saved condition contracts agree except `environment.runtime.permissions_sha256`. The
  benchmark's identical permission suffix after the last global `*/* deny` is byte-for-byte the same;
  inherited pre-deny entries vary in order and irrelevant paths. Canonicalize only by discarding that
  overridden prefix; preserve the ordered effective suffix and all other runtime identity fields.
- Muse's failed edit input is `/C:/.../grep.py`; its exact tool error is `File /C:/.../grep.py not found`.
  OpenCode v1.19.3 checks `afs.stat` and returns this error before its read, approval, or write path.
  Permit this single version/tool/error combination as proven pre-mutation, retain it in event evidence,
  and stay uncertain for other errors/versions. This is verified against the pinned upstream
  [`edit.ts` implementation](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/tool/edit.ts).
  Never rewrite the saved audit/trial.
- Devstral completed a `write` call to `implementation_complete.txt` containing its completion summary.
  This is an actual unauthorized file and remains a strict scope violation.
- GPT-OSS's edit replacement contains literal `+` prefixes; verifier has no completion receipt and its
  saved worker code fails syntax. Keep it failed; make tool/prompt instructions clearer for all providers.
- Saved outcomes remain Ornith/Qwen strict pass, Muse unscored, Devstral scope failure, and GPT-OSS
  functional failure. The only cross-run condition divergence is the raw permission hash; all five
  effective suffixes contain eight identical ordered rules and now fingerprint to `a370e1fe...`.

## Work sequence

1. Add regression for nonempty condition-group CSV/Markdown/HTML generation; fix runtime import locally.
2. Add regression for equal effective permission fingerprints across varying overridden prefixes; emit
   only the ordered effective rules in runtime identity and verify conditions group together.
3. Add tests for the exact OpenCode v1.19.3 edit not-found failure and adjacent unknown failures; retain
   explicit outcome evidence. Pass recorded runtime version to scoring/audit and re-audit paths.
4. Add a common prompt rule that status/completion reports belong in the final response or
   StructuredOutput, never extra files; explain that `edit.newString` is literal replacement content and
   `+` diff lines become source characters. Bump agent version for the prompt/scoring contract change.
5. Offline report regeneration of a copy of the saved experiment; all focused module/core tests and lint;
   independent diff/evidence review. No model calls or writes to historical evidence.

No model outcome, verifier, denominator or saved trial artifact is changed. Document and retain the
experiment-specific forensic conclusions. Commit/push feature and merge local main under standing
user authorization after checks.

## Status

## Validation and review

- Benchmark Core full suite: 114 passed, 1 skipped. New nonempty condition-group test renders CSV,
  Markdown and HTML.
- Agent Benchmark full suite: 360 passed, 3 skipped. Focused evidence/condition/prompt set: 56 passed,
  1 skipped.
- Interactive Reports full suite: 18 passed. `ruff check modules/agent_benchmark modules/benchmark_core
  modules/interactive_reports` and `git diff --check` pass.
- Re-rendered the saved experiment through `agent_benchmark experiment report` from a temporary copy.
  CSV, Markdown and HTML were produced; SHA-256 checks confirmed the source `experiment.json`,
  `comparison.json` and `run-references.json` stayed unchanged. No inference was run.
- Read-only independent review found no blocking issues. The reviewer verified the strict permission
  suffix handling, narrow versioned edit error predicate, runtime version plumbing, and version bumps.

## Current status

Implementation and offline verification are complete. Commit `fc4374f3938a529de3e55ab7e8723f5d41cb30cc`
is pushed to `origin/agent/benchmark-exp-061135` and local `main` was fast-forwarded to it. Remote
`origin/main` remains at `cb82930c`; no remote-main merge or push was performed.
