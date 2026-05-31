# ytaedl Archive Validation Plan

## Goal

Add a ytaedl archive validation workflow that checks whether archive entries and
`domain_index.json` still match current downloader/local-file reality, then
optionally writes and applies a JSON repair plan.

## Scope

- Add `ytaedl archive validate` for validation.
- Add `ytaedl archive apply-plan` for applying JSON repair plans.
- Preserve the existing `ytaedl archive` rebuild behavior.
- Remove the user-facing `ytaedl run -f/--finished-log` option and always write
  `finished_urls.txt` inside `--log-dir`.
- Bump the module minor version because this adds user-facing CLI behavior.

## Validation Semantics

For each URL found in archive `*.txt` files:

1. Parse the archive status and URL from the current archive line format.
2. Check local download roots passed via repeated `-L/--download-root` only
   with URL-specific evidence. A URL-file folder containing any `.mp4` is not
   enough to mark every archive URL in that file as present.
3. If requested with `-p/--count-partials`, check matching `_partial` state.
4. For yt-dlp URLs, run the existing yt-dlp simulate duplicate check:
   - existing/predicted duplicate -> `preexisting`
   - simulate succeeds with no checked-root match -> `viable`
   - simulate fails/times out -> `bad-url`
5. For AEBN URLs, avoid downloading during validation:
   - URL-specific local filename evidence -> `preexisting`
   - matching `_partial` metadata when partial counting is enabled -> `partial`
   - with `-M/--aebn-metadata-check`, use aebndl metadata and existing-output
     naming logic against each `-L/<archive-stem>/` folder without downloading
     segments:
     - matching aebndl output name -> `preexisting`
     - metadata resolves and no matching output exists -> `viable`
     - metadata check fails -> `bad-url`
   - without metadata checking and no URL-specific local evidence -> `unknown`
6. Compare archive status class against actual status class and record every
   mismatch.

`viable` means the URL should not remain archived as already done or bad. The
repair plan removes those archive/domain-index terminal markers so normal
downloader runs can retry them. `unknown` means the validator did not gather
enough evidence to safely recommend an archive/domain-index change.

## Processing Controls

Support:

- `-t/--threads` (`-w/--workers` is retained as a hidden compatibility alias)
- `-O/--order`: `oldest`, `newest`, `url-file`, `random`
- `-T/--timer-seconds`
- `-c/--count`
- `-R/--ratio`
- multiple stop conditions, stopping on the first one reached
- repeated `-L/--download-root`
- URL-file exclusive scheduling: no two active workers should validate URLs
  from the same archive URL file at the same time.
- `-a/--archive`
- `-g/--log-dir`
- `-G/--validation-log-dir`
- `-s/--stars-dir`
- `-d/--aebn-dir`

## UI And Logs

The validation command should render an in-place worker view with:

- per-worker current URL
- processed count
- mismatch count
- last result
- `Up`/`Down` to select a worker
- `v` to show/hide the selected worker log
- `q` to stop after current work completes

Each worker keeps an in-memory log of URL attempts and results for the UI and
also writes `archive-validate-worker-XX.log` inside `--validation-log-dir`.
The mode also writes `archive-validate-master.log` in that folder. Summary
output prints after any completed or stopped run.

## Summary Output

After validation, print:

- total archive URLs
- processed count
- matched count
- mismatch count
- partial count when enabled
- stop reason
- elapsed time
- transition breakdown, such as `bad-url -> viable` or
  `downloaded -> bad-url`
- URL files with mismatches
- every mismatched URL with archive file, line, downloader, and reason

## JSON Repair Plan

When `-j/--json-plan` is passed, write a JSON file containing:

- plan version
- generated timestamp
- archive/log roots
- summary
- one change per mismatch

Repair actions:

- `viable` or `partial`: remove archive entry and remove finished state from
  `domain_index.json`
- `preexisting`: set archive/domain-index finished state
- `bad-url`: set archive/domain-index finished state as bad

## Apply Workflow

`ytaedl archive apply-plan -p plan.json` should:

1. Load the generated plan.
2. Rewrite affected archive files.
3. Update `logs/domain_index.json` when present.
4. Support `-n/--dry-run`.
5. Allow `-a/--archive` and `-g/--log-dir` overrides.

## Tests

Add focused tests for:

- archive validate/apply dispatch
- archive parsing and mismatch classification
- JSON plan generation
- dry-run/apply archive rewrites
- removal of run `-f/--finished-log`
- hardcoded `<log-dir>/finished_urls.txt` behavior

## Validation Commands

Run at least:

```powershell
python -m py_compile ytaedl/archive_validator.py ytaedl/archive_builder.py ytaedl/manager.py ytaedl/cli.py
pytest tests/test_archive_validator.py tests/test_cli_dispatch.py tests/test_manager.py -q
ruff check ytaedl/archive_validator.py ytaedl/archive_builder.py ytaedl/manager.py ytaedl/cli.py tests/test_archive_validator.py
```
