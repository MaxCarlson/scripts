# mangadl

`mangadl` is a concurrent, resumable manager for manga and image-gallery downloads. It uses gallery-dl as its broad primary backend, routes HDPornComics manhwa URLs to its dedicated downloader, provides a native Manga18FX series downloader, and can fall back to an installed native `nhentai` CLI for nhentai URLs.

The dashboard replaces gallery-dl's line-per-image transcript. Each worker gets a fixed-width status row plus a second progress/activity-bar row. The header reports active/target workers, Manga18FX image threads per worker, aggregate active concurrency, and the logical-CPU budget. Press `+` or `-` to raise or lower the outer-worker target, `]` or `[` to change image threads for newly started Manga18FX jobs, `l` for the selected worker's inline activity log, `f` for its fullscreen log, `r` to switch between concise activity records and raw backend output, and `q` to stop immediately through the same cleanup path as Ctrl+C.

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

Manga18FX downloads use two concurrency levels. `-w/--workers` controls simultaneous series jobs, while `-I/--image-workers` controls simultaneous image transfers inside each Manga18FX series. Image workers default to `4` and accept `1` through `8`.

```powershell
mangadl run -i .\manga18fx-urls.txt -d .\downloads -a .\gallery-dl-archive.sqlite3 -s .\mangadl-state.sqlite3 -w 4 -I 4
```

The observed safe outer-worker ceiling for the current disk workload is four. `-m/--max-workers` therefore defaults to `4`; a requested `-w` above that ceiling is reduced before workers start. Experimental values up to eight require an explicit override such as `-m 5 -w 5`. `-U/--worker-start-delay` staggers worker process launches and defaults to two seconds. Use `-U 0` only when simultaneous startup is known to be safe.

Aggregate Manga18FX image concurrency is bounded below the detected logical processor count, with one logical processor reserved for the manager, dashboard, OS, and filesystem work. Increasing `-I` is generally cheaper than adding outer workers because each outer worker also performs chapter discovery, directory work, logging, and progress sampling.

## Automatic Manga18FX tuning

`-T/--auto-tune` runs a bounded preflight benchmark, records every tested combination, selects the highest aggregate throughput, and then starts the normal resumable run with the selected `-w` and `-I` values. Candidate startup and stagger time are included in the score, so combinations that take too long to become productive rank poorly.

```powershell
mangadl run -i .\manga18fx-urls.txt -d .\downloads -a .\gallery-dl-archive.sqlite3 -s .\mangadl-state.sqlite3 -T -W 1:4 -Y 1:8 -D 8 -Q 2 -K 24
```

- `-W/--tune-workers MIN:MAX` sets the inclusive outer-worker range. It defaults to `1:<max-workers>` and cannot exceed `-m/--max-workers`.
- `-Y/--tune-image-workers MIN:MAX` sets the inclusive inner image-thread range.
- `-D/--tune-seconds` sets the target sample duration per combination.
- `-Q/--tune-rounds` controls repeated measurements; rates are averaged.
- `-K/--tune-sample-images` limits representative image transfers per active series and candidate.
- `-O/--tune-report` selects the JSON report path. The default is timestamped under the log root.

The tuner uses temporary probe downloads and deletes them after each candidate. The report preserves raw samples, averages, medians, variance, errors, throughput per aggregate thread, and the selected combination. Near-ties within two percent prefer the lower-concurrency option.

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

Worker rows show compact colored backend badges: `GD` for gallery-dl, `NH` for native nhentai, `HD` for HDPornComics, and `M18` for Manga18FX.

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

- Image and byte totals remain unknown until exposed by the backend or completion. When totals are unavailable, the second worker row shows an activity bar rather than fabricating a percentage.
- Runtime `[` and `]` changes apply to newly started Manga18FX jobs; an already-running series retains the thread pool created at launch.
- Lowering the outer-worker target drains excess active workers instead of terminating their current series.
- Pause is a scheduling/drain pause and does not suspend an in-progress HTTP request.
- `--config` and `--anonymize-logs` are reserved compatibility options.
- Browser-cookie extraction is passed through to gallery-dl only. The native Manga18FX backend supports `-C/--cookies` Netscape/Mozilla files.
- Manga18FX HTML or anti-bot changes may require backend maintenance.
- No legacy downloader is migrated, modified, or deleted.
