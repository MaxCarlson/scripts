# mangadl

`mangadl` is a concurrent, resumable manager for manga and image-gallery downloads. It uses gallery-dl as its broad backend, routes HDPornComics manhwa URLs to the dedicated downloader, provides a native Manga18FX series downloader, and can fall back to an installed native `nhentai` CLI.

The normal dashboard replaces line-per-image output. Each worker receives a fixed-width status row and a second progress/activity row. The header reports active/target workers, Manga18FX image threads per newly started worker, aggregate concurrency, and the logical-CPU budget.

Runtime keys:

- `+` / `-`: increase or reduce the target outer-worker count.
- `]` / `[`: change image threads for newly started Manga18FX workers.
- `j` / `k` or arrows: select a worker.
- `l`: selected worker's inline activity log.
- `f`: selected worker's fullscreen log.
- `r`: switch between activity and raw backend output.
- `p` / `P`: pause selected/all scheduling.
- `q`: stop immediately through the same cleanup path as Ctrl+C.

## Install

```powershell
python -m pip install -e .\modules\termdash
python -m pip install -e .\modules\mangadl
```

## Concise normal run

```powershell
mangadl run -i .\urls.txt -d .\downloads -a .\gallery-dl-archive.sqlite3 -w 2 -I 4
```

The normal `run --help` surface contains only routine input, destination/archive, and concurrency controls:

- `-i/--input-file`: repeatable UTF-8 URL file.
- `-u/--url`: repeatable direct URL or supported shorthand.
- `-d/--destination`: output library root.
- `-a/--archive`: gallery-dl archive database.
- `-w/--workers`: initial simultaneous series workers.
- `-I/--image-workers`: image transfers inside each newly started Manga18FX worker.

Run IDs are always generated automatically. Manager state defaults to `mangadl-state.sqlite3`, and logs default to `mangadl-logs`.

Blank lines and lines beginning with `#` or `;` are ignored. Duplicate and unsupported URLs are reported before workers start.

## Advanced run configuration

Less common settings are organized under `run config`:

```powershell
mangadl run config -i .\urls.txt -d .\downloads -a .\gallery-dl-archive.sqlite3 -w 4 -I 4 -s .\mangadl-state.sqlite3 -r 3 -U 2
```

`run config --help` exposes backend forcing, state/log paths, retries, retry delay, worker ceiling/stagger, gallery-dl configuration and rate limiting, cookies, HDPornComics executable/threads, dry-run, no-UI, quiet, verbose, and log-anonymization compatibility settings.

For one transition release, the former flat advanced flags remain accepted directly under `run`, but they are hidden from normal help.

## Managed gallery-dl browser authentication

`mangadl` asks the installed gallery-dl extractor registry whether a URL is
supported. It does not maintain a separate site list, so supported URLs such as
Mangakakalot series pages continue to route automatically to gallery-dl.

Manganelo/Mangakakalot has a built-in validated target, so the normal first-use
command needs no URL:

```powershell
mangadl auth refresh
mangadl auth status -d mangakakalot.gg
```

Chrome is the default. Refresh opens or reuses an isolated Chrome debug
session, opens the exact target URL, waits for any interactive challenge,
captures all matching-domain cookies plus Chrome's exact User-Agent, writes a
Netscape cookie file, and validates the same URL with gallery-dl simulation.
It reports every phase plus periodic remaining-time messages, so a browser wait
or gallery-dl probe is visibly active. Cookie values are never printed.

The cookie file defaults to `<domain>-cookies.txt` in the directory where the
command was invoked. For example, running from `B:\Hent\tmphent3` creates:

```text
B:\Hent\tmphent3\mangakakalot.gg-cookies.txt
```

Mangadl stores only non-secret profile metadata and saved target URLs under its
application auth directory. A new valid `-u/--url` value replaces the saved
target for the gallery-dl site that recognizes it:

```powershell
mangadl auth refresh -u https://www.mangakakalot.gg/manga/like-no-other
```

Discover and select sites from the installed gallery-dl version at runtime:

```powershell
mangadl auth sites
mangadl auth sites -f manga
mangadl auth refresh -s manganelo
mangadl auth refresh -S -q manga
```

`auth sites` uses gallery-dl's extractor registry rather than a copied support
list. If a selected site has no saved actual target, mangadl asks for a real
gallery/series URL, verifies that the selected gallery-dl extractor accepts it,
and saves it for later no-URL refreshes. Placeholder examples, homepages, and
search pages are not assumed to be download targets.

Other browser sources and a custom cookie-file destination are explicit:

```powershell
mangadl auth refresh -u $url -b edge
mangadl auth refresh -u $url -b firefox -U $firefoxUserAgent
mangadl auth refresh -u $url -c D:\private\gallery-cookies.txt
mangadl auth refresh -u $url -b chrome -p 9222 -n
mangadl auth clear -d mangakakalot.gg
```

Chrome and Edge use the browser's DevTools protocol. Firefox is opened at the
exact target and uses gallery-dl's Firefox cookie export; `-U/--user-agent` can
supply its exact matching UA. `-n/--no-launch-browser` explicitly opts into an
already-running browser instead of having mangadl open one.
Profiles default to `%APPDATA%\mangadl\auth\<domain>` on Windows,
`~/.config/mangadl/auth/<domain>` on Linux, and
`~/Library/Application Support/mangadl/auth/<domain>` on macOS. Override the
root with `-A/--auth-dir` or `MANGADL_AUTH_DIR`.

After a profile is created, the ordinary command is sufficient:

```powershell
mangadl run -i .\urls.txt -d .\downloads -a .\gallery-dl-archive.sqlite3
```

Each gallery-dl job resolves its own domain profile. Explicit
`-C/--cookies`, `-B/--cookies-browser`, `-g/--gallery-config`, and
`-k/--gallery-user-agent` settings take precedence. A recognized 401/403,
`ChallengeError`, or Cloudflare challenge makes the profile stale even when
its expiry is in the future and the UA is unchanged. The manager performs one
shared refresh per domain and retries each affected job once; 404, rate-limit,
filesystem, and unrelated backend failures do not refresh credentials.

For a Windows simulation-only live check from the desired output folder:

```powershell
Set-Location B:\Hent\tmphent3
mangadl auth refresh
mangadl auth status -d mangakakalot.gg
```

Do not commit the auth directory or share its cookie file. A URL such as
`/search/story/like_no_other` remains unsupported when gallery-dl's extractor
registry rejects it.

## Manga18FX concurrency and resume behavior

Manga18FX series URLs automatically use the native backend. It creates one series folder, naturally ordered chapter folders, and zero-padded images. Downloads use `.part` files followed by atomic completion. Failed jobs remain under `_partial/<job-id>/`; successful jobs merge into the destination.

Reruns inspect the final library and skip valid existing images. Live progress counts both newly downloaded and already-existing images as processed, while byte totals and MiB/s represent only newly transferred data.

`-w/--workers` controls simultaneous series jobs. `-I/--image-workers` controls simultaneous image transfers within each newly started Manga18FX series. Existing workers keep the `-I` value with which they started.

The default outer-worker safety ceiling is four because a fifth worker saturated the current destination disk during live validation. Aggregate Manga18FX image concurrency is also kept below the detected logical-processor count, with one logical processor reserved for the manager, dashboard, OS, and filesystem work.

## Adaptive online optimization

```powershell
mangadl run optimize -i .\manga18fx-urls.txt -d .\downloads -a .\gallery-dl-archive.sqlite3 -p 1 -m 4 -P 1 -M 8
```

`run optimize` measures real Manga18FX traffic and adaptively searches the bounded `(workers, image-workers)` state space. It begins with low-to-high coverage, then favors neighboring and upper-confidence states around the best observed result. Deliberate exploration decays exponentially as more trials complete.

The optimization dashboard shows:

- valid states and unique states tried;
- completed and planned trials;
- current state and selection reason;
- best state and measured average throughput;
- exploration percentage;
- convergence estimate;
- current trial bytes, speed, elapsed time, and active workers.

Bounds:

- `-p/--min-workers`
- `-m/--max-workers`
- `-P/--min-image-workers`
- `-M/--max-image-workers`

Evaluation modes:

- `-E complete`: each worker keeps its launch settings until its representative series finishes. This is the optimization default.
- `-E timed -D SECONDS`: each state runs for a bounded interval, then its subprocesses are terminated and the next state starts.

`-Q/--trials` sets the adaptive trial count. `-O/--optimization-report` selects the durable JSON report. `-o/--report-only` stops after selecting a state rather than starting the real resumable run.

Advanced optimization settings use:

```powershell
mangadl run optimize config -i .\manga18fx-urls.txt -d .\downloads -a .\gallery-dl-archive.sqlite3 -p 1 -m 4 -P 1 -M 8 -E timed -D 30 -Q 16 -U 2
```

After optimization, the selected `-w` and `-I` values are applied to the normal resumable run unless `--report-only` is used.

## Systematic online benchmark

```powershell
mangadl run benchmark -i .\manga18fx-urls.txt -d .\downloads -a .\gallery-dl-archive.sqlite3 -p 1 -m 4 -P 1 -M 8 -E timed -D 30 -Q 2
```

`run benchmark` tests every valid bounded state systematically. The first round moves upward through aggregate concurrency; subsequent rounds alternate direction to reduce ordering bias. `-Q/--trials` is the number of complete matrix rounds.

Benchmark and optimization both include worker-stagger startup time in throughput measurements, rotate representative series order between trials, persist every result, prefer lower aggregate concurrency within two percent of peak throughput, and then prefer fewer outer workers within that near-tie.

The old `-T/-W/-Y/-D/-Q/-K/-O` auto-tune interface remains as a hidden compatibility alias for one transition release and normalizes to `run benchmark`.

## Interactive archive browser

```powershell
mangadl archive -a .\gallery-dl-archive.sqlite3
```

The default archive command opens an interactive browser instead of printing only a record count. It introspects the archive schema, displays a paged table, shows selected-record details, and supports:

- `j` / `k` or arrows: move.
- Page Up / Page Down, Home / End: navigate.
- `/`: filter all record values.
- `c`: clear the filter.
- `e`: export the filtered view to JSON.
- `q`: quit.

Machine-readable and non-interactive controls are under `archive config`:

```powershell
mangadl archive config -a .\gallery-dl-archive.sqlite3 -f manga18fx -e .\filtered-archive.json
mangadl archive config -a .\gallery-dl-archive.sqlite3 -j
mangadl archive config -a .\gallery-dl-archive.sqlite3 -N
```

## Other operations

```powershell
mangadl inspect -u https://manga18fx.com/manga/example/
mangadl status -s .\mangadl-state.sqlite3
mangadl retry -s .\mangadl-state.sqlite3 -f
mangadl patch-hdporncomics
mangadl patch-hdporncomics -f
mangadl repair-loose -d .\downloads
mangadl repair-loose -d .\downloads -f
```

`repair-loose` remains dry-run-first and refuses apply mode when expected pages are missing or destinations collide. `patch-hdporncomics` checks or applies the known Windows filename/path compatibility patch.

## State, archives, and partial data

Manager state and gallery-dl's archive are distinct:

- the manager database owns runs, URL jobs, attempts, leases, outcomes, and restart recovery;
- the gallery-dl archive owns gallery-dl deduplication;
- the native Manga18FX backend deduplicates against valid images in the final destination and active partial job.

Each run writes manager logs, structured events, summaries, worker activity logs, and raw backend logs under `<log-dir>/<run-id>/`.

## Limitations

- Image and byte totals remain unknown until a backend exposes them or the job completes; unknown totals use an activity bar rather than a fabricated percentage.
- Runtime image-thread changes apply only to newly started Manga18FX jobs.
- Reducing the outer-worker target drains active excess workers instead of killing their current series.
- Pause affects scheduling and does not suspend an in-progress HTTP request.
- `--config` and `--anonymize-logs` remain reserved compatibility settings.
- Native Manga18FX uses explicit Netscape/Mozilla cookie files; managed browser
  profiles apply only to gallery-dl-routed jobs.
- Manga18FX HTML, CDN, or anti-bot changes may require backend maintenance.
