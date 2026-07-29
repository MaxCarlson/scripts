# mangadl

`mangadl` is a concurrent, resumable manager for manga and image-gallery downloads. It uses gallery-dl as its broad primary backend, routes HDPornComics manhwa URLs to its dedicated downloader, provides a native Manga18FX series downloader, and can fall back to an installed native `nhentai` CLI for nhentai URLs.

The dashboard replaces gallery-dl's line-per-image transcript. Each worker reports a compact site/URL identifier, image and byte counts, current and per-URL average rates, elapsed time, retries, and failures. Statuses, site tags, progress, rates, and log outcomes use semantic colors. Press `l` for the selected worker's inline activity log, `f` for its fullscreen log, and `r` to switch between concise activity records and raw backend output.

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

`https://hdporncomics.com/manhwa/...` and `https://www.hdporncomics.com/manhwa/...` URLs automatically use `hdporncomics --directory <destination> --threads 8 --force --manhwa <url>`. Their title directories are created directly under the destination; mangadl does not add another title layer. Use `-e/--hdporncomics-executable` to override executable discovery and `-H/--hdporncomics-threads` to change only the downloader's internal concurrency.

`https://manga18fx.com/manga/...` and `https://www.manga18fx.com/manga/...` URLs automatically use mangadl's native Manga18FX backend. It creates one top-level folder per series, stable naturally ordered chapter folders, and zero-padded image files. Failed jobs remain under `_partial/<job-id>/`; successful jobs merge into the destination. Reruns inspect the final library and skip images already present. Use `-C/--cookies` with a Netscape/Mozilla cookies export if anonymous requests are blocked.

## Operations

```powershell
mangadl inspect -u https://nhentai.net/g/123456/
mangadl inspect -u https://manga18fx.com/manga/example/
mangadl status -s .\mangadl-state.sqlite3
mangadl retry -s .\mangadl-state.sqlite3 -f
mangadl archive -a .\gallery-dl-archive.sqlite3
mangadl patch-hdporncomics
mangadl patch-hdporncomics -f
mangadl repair-loose -d .\downloads
mangadl repair-loose -d .\downloads -n
mangadl repair-loose -d .\downloads -f
mangadl repair-loose -d .\downloads -N
```

`repair-loose` is dry-run-first; `-n/--dry-run` makes that mode explicit and `-f/--apply` authorizes moves. Its in-place dashboard shows colored metadata, move, and verification progress bars; gallery/file counts; expected, present, missing, and conflict totals; the current nhentai ID/title; and elapsed time. Use `-N/--no-ui` for plain output or `-j/--json` for machine-readable output.

The command extracts each nhentai ID from loose filenames, performs a metadata-only gallery-dl lookup, uses the exact same shared folder and filename templates as normal downloads, verifies that every expected page is present or planned, and only moves files in apply mode. Apply is refused for missing pages or target collisions, and page completeness is checked again after moving.

`patch-hdporncomics` reports whether the installed HDPornComics package has the Windows filename compatibility patch. `-f/--apply` saves a one-time `.bak` copy of its CLI module and applies a safe filename sanitizer (invalid characters, reserved names, and long paths). This is intentionally explicit: package updates can replace the patched file. A known Windows path error from the backend reports the recovery command in the failed job message.

Worker rows show a compact colored backend badge: `GD` for gallery-dl, `NH` for native nhentai, and `HD` for HDPornComics. Unknown or newly added backends use the neutral fallback badge until explicitly styled.

## Audit destination roots

Use `audit` to check URL files against one or more existing download roots without downloading or changing those roots. `audit-destinations` remains a compatibility alias. Audit progress is shown on stderr during input loading, destination scanning, matching, and report writing; `-j/--json` therefore keeps stdout machine-readable. Add `-q/--quiet` to suppress progress.

```powershell
mangadl audit -i .\urls*.txt `
  -d D:\Manga -d E:\Archive\Manga `
  -o .\missing-urls.txt -p .\duplicate-folders.json -j
```

`missing-urls.txt` receives URLs not identified in any root. `duplicate-folders.json` records identical populated top-level folder names and every location. Matching uses URL metadata where available, stable nhentai gallery IDs, and normalized HDPornComics manhwa title slugs; it does not guess for unrelated folders with similar names.

Manager state and gallery-dl's archive are separate. The manager database owns URL jobs, attempts, leases, outcomes, and restart recovery. The gallery-dl archive owns per-image deduplication; the Manga18FX backend deduplicates against existing image files in the destination and current partial job.

Each run writes `manager.log`, `events.jsonl`, `summary.json`, structured per-worker logs, and raw backend logs under `<log-dir>/<run-id>/`. Partial downloads remain under `<destination>/_partial/<job-id>/` after failure and are merged into the destination after success.

## Limitations

- Image and byte totals remain unknown until exposed by the backend or completion; the dashboard does not fabricate percentages.
- Pause is a scheduling/drain pause and does not suspend an in-progress HTTP request.
- `--config` and `--anonymize-logs` are reserved compatibility options in 1.7.0.
- Browser-cookie extraction is passed through to gallery-dl only. The native Manga18FX backend supports `-C/--cookies` Netscape/Mozilla files.
- Manga18FX HTML or anti-bot changes may require backend maintenance.
- No legacy downloader is migrated, modified, or deleted.
