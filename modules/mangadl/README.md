# mangadl

`mangadl` is a concurrent, resumable manager for manga and image-gallery downloads. It uses gallery-dl as its broad primary backend and can fall back to an installed native `nhentai` CLI for nhentai URLs.

The dashboard replaces gallery-dl's line-per-image transcript. Each worker reports a compact site/URL identifier, image and byte counts, current and per-URL average rates, elapsed time, retries, and failures. Statuses, site tags, progress, rates, and log outcomes use semantic colors. Press `l` for the selected worker's inline activity log, `f` for its fullscreen log, and `r` to switch between concise activity records and raw gallery-dl output.

## Install

```powershell
python -m pip install -e .\modules\termdash
python -m pip install -e .\modules\mangadl
```

## Download a URL file

```powershell
mangadl run -i .\urls.txt -d .\downloads -a .\gallery-dl-archive.sqlite3 -s .\mangadl-state.sqlite3 -w 2
```

Multiple `-i/--input-file` and `-u/--url` options are accepted. Blank lines and comment lines beginning with `#` or `;` are ignored. Duplicate URLs are reported before workers start. Use `-n/--dry-run` to parse and route without downloading and `-N/--no-ui` for a non-interactive run.

## Operations

```powershell
mangadl inspect -u https://nhentai.net/g/123456/
mangadl status -s .\mangadl-state.sqlite3
mangadl retry -s .\mangadl-state.sqlite3 -f
mangadl archive -a .\gallery-dl-archive.sqlite3
mangadl repair-loose -d .\downloads
mangadl repair-loose -d .\downloads -n
mangadl repair-loose -d .\downloads -f
mangadl repair-loose -d .\downloads -N
```

`repair-loose` is dry-run-first; `-n/--dry-run` makes that mode explicit and `-f/--apply` authorizes moves. Its in-place dashboard shows colored metadata, move, and verification progress bars; gallery/file counts; expected, present, missing, and conflict totals; the current nhentai ID/title; and elapsed time. Use `-N/--no-ui` for plain output or `-j/--json` for machine-readable output.

The command extracts each nhentai ID from loose filenames, performs a metadata-only gallery-dl lookup, uses the exact same shared folder and filename templates as normal downloads, verifies that every expected page is present or planned, and only moves files in apply mode. Apply is refused for missing pages or target collisions, and page completeness is checked again after moving.

Manager state and gallery-dl's archive are separate. The manager database owns URL jobs, attempts, leases, outcomes, and restart recovery. The gallery-dl archive owns per-image deduplication.

Each run writes `manager.log`, `events.jsonl`, `summary.json`, structured per-worker logs, and raw backend logs under `<log-dir>/<run-id>/`. Partial downloads remain under `<destination>/_partial/<job-id>/` after failure and are merged into the destination after success.

## Limitations

- Image and byte totals remain unknown until exposed by the backend or completion; the dashboard does not fabricate percentages.
- Pause is a scheduling/drain pause and does not suspend an in-progress HTTP request.
- `--config` and `--anonymize-logs` are reserved compatibility options in 1.3.0. Cookies files and browser cookie sources are passed through to gallery-dl.
- No legacy downloader is migrated, modified, or deleted.
