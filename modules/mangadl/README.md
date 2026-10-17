# mangadl

## Inventory without compression

```powershell
mangadl compress -d 'B:\Hent\hent1imageperpage' -l -I 'E:\Temp\mangadl-inventory.sqlite3' > 'E:\Temp\mangadl-inventory.json'
```

`-l` runs no encoders. The JSON report groups eligible pages by gallery, preserving
nested chapter ownership and cover/control/partial exclusions. Extension totals,
actual formats, image sizes/shares and scan-scope errors are separate. A header scan
is not an integrity audit. Normal compression automatically refreshes durable header
inventory too; use the same `-I` path to reuse this one. Without `-I`, explicit `-K`
gets a companion inventory file; otherwise a per-library user-cache path is selected.
Membership is checked each run and unchanged headers reused; sources are not changed.

Compression trials also persist automatically beside inventory. Use `-k use`
(default), `-k refresh` (ignore older trials, retain new ones), or `-k off` (in-run
memory only). `-K` still overrides the trial-cache file. Policies never delete
unrelated data or skip source/settings fingerprint checks. Inventory-only does not
open a trial cache, and disabling trials does not disable inventory persistence.

Larger samples now extend smaller ones for an unchanged inventory and seed.
For example, run -P 2 then -P 5 with the same -z value: existing selected images
remain included and matching trials can be reused. Selection plans/population
fingerprints are saved in the inventory SQLite file. Sampling revision2 changes
the old revision1 selection order; a seed alone does not identify a plan across
different revisions or changing libraries. This is not yet a statistical advisor.

## Representative compression comparison

```powershell
mangadl compress -d 'B:\Hent\hent1imageperpage' -b -q 80 -P 2 -z 42 -t 4 -B 1024 -K 'E:\Temp\compression-cache.sqlite3'
```

Read-only: inventory eligible pages once, then compare full lossless and lossy
strategy sets on the same random sample. `-P 2` selects 2% of images (rounded up
to cover every eligible gallery); alternatively `-s N` sets a total sample budget
which must be at least the gallery count. Quotas combine gallery image counts
and bytes; nested chapters stay with their parent manga. Same seed reproduces
selection. Inventorying all pages still takes time, but only sampled pages are
encoded. `-K` commits cache entries during analysis and reuses matching results.
Use the same cache, seed and settings on repeat checks. Completed trials survive
interruption; changing quality or effort invalidates their reuse.

The report separates measured savings from gallery-weighted projections and
approximate uncertainty. Failures block a full projection; one-image samples in
non-census galleries block an uncertainty interval. Increase sampling for rare
formats or heterogeneous galleries. Add `-J` to emit a JSON report (no live UI),
for example append `-J > .\compression-report.json` from outside the target tree.
See [compression details](../compresser/README.md) for limits. Do not add `-w`:
sampled comparisons are analysis-only.

`mangadl` is a concurrent, resumable manager for manga and image-gallery downloads. It uses gallery-dl as its broad backend, routes HDPornComics manhwa URLs to the dedicated downloader, provides a native Manga18FX series downloader, and can fall back to an installed native `nhentai` CLI.

The normal dashboard replaces line-per-image output. Each worker receives a fixed-width status row and a second progress/activity row. The header reports active/target workers, Manga18FX image threads per newly started worker, aggregate concurrency, and the logical-CPU budget.

Runtime keys:

- `+` / `-`: add a worker or retire the highest excess worker after its current download.
- `]` / `[`: change image threads for newly started Manga18FX workers.
- `j` / `k` or arrows: select a worker.
- `l`: selected worker's inline activity log.
- `f`: selected worker's fullscreen log.
- `r`: switch between activity and raw backend output.
- `p` / `P`: pause selected/all scheduling.
- `q`: stop assigning work, wait for active downloads to finish, then quit.
- `Ctrl+Q` or `Ctrl+C`: stop active workers immediately and retain resumable partials.

## Install

```powershell
python -m pip install -e .\modules\termdash
python -m pip install -e .\modules\kavita
python -m pip install -e .\modules\mangadl
```

## Concise normal run

```powershell
mangadl run -i .\urls.txt -d .\downloads -w 2 -I 4
```

The normal `run --help` surface contains only routine input, destination, and concurrency controls:

- `-i/--input-file`: repeatable UTF-8 URL file.
- `-u/--url`: repeatable direct URL or supported shorthand.
- `-d/--destination`: output library root.
- `-S/--scratch`: optional fast-drive staging root (`--scratch-dir` also works).
- `-G/--allow-collection`: explicitly permit broad feeds, searches, tags, or
  series collections that may expand into many galleries.
- `-a/--archive`: optional gallery-dl archive override.
- `-w/--workers`: initial simultaneous series workers.
- `-m/--max-workers`: runtime worker ceiling. If either destination or scratch
  is detected as an SSD, the ceiling follows the aggregate logical-CPU budget;
  otherwise it is capped at four. The aggregate CPU budget always remains active.
- `-I/--image-workers`: image transfers inside each newly started Manga18FX worker.

Run IDs are always generated automatically. Archive, state, and logs default to
`<destination>/.mangadl/archive.sqlite3`,
`<destination>/.mangadl/state.sqlite3`, and
`<destination>/.mangadl/logs`. Explicit `-a/--archive`, `-s/--state-db`, and
`-l/--log-dir` values still override those paths, but ordinary use needs no
PowerShell variables or manual control-directory setup.

### Kavita collection assignment

Use repeatable `-M/--collections` to associate each successfully downloaded
URL with one or more Kavita collections. The existing `-c/--config` option
keeps its current meaning, so `-M` is the collection short form. Supply the
Kavita server URL and put the Auth Key in the environment variable named by
`--kavita-api-key-env` (default `KAVITA_API_KEY`):

```powershell
mangadl run -i .\urls.txt -d .\downloads -M "New manga" --kavita-url http://192.168.50.100:5000
```

This saves URL-to-folder assignment records without writing to Kavita. To
apply immediately after successful downloads, add `-E/--apply-kavita`. If the
server has not scanned the folders yet, MangaDL leaves those records pending.
After the scan completes, review the pending work and explicitly apply it:

```powershell
mangadl kavita reconcile -d .\downloads --kavita-url http://192.168.50.100:5000
mangadl kavita reconcile -d .\downloads --kavita-url http://192.168.50.100:5000 -f
```

Reconciliation matches only a unique exact folder path. Use repeatable
`--kavita-path-map LOCAL=KAVITA` when Kavita sees a different path, such as a
container mount. Missing or ambiguous matches remain pending; title similarity
is never used. URL-file syntax remains unchanged.

For manga already downloaded and scanned by Kavita, `mangadl kavita assign-file`
resolves a processed URL file against the selected MangaDL library and previews
the exact series-to-collection assignment. `assign-name` selects an exact
case-insensitive series name. `assign-pattern` searches series names using a
bounded Python regular expression and prints the complete match list plus a
review token; applying requires both `-f/--apply` and that exact token.
Collections are repeatable with `-c/--collection`:

```powershell
mangadl kavita assign-file -i .\processed-urls.txt -d .\downloads -c "Summer" -c "Favorites" -Z http://kavita:5000
mangadl kavita assign-name -n "Exact Series Title" -c "Favorites" -Z http://kavita:5000 -f
mangadl kavita assign-pattern -p 'blahblah.*' -c "Favorites" -Z http://kavita:5000 -j
```

The pattern is a regular expression, not a shell glob: `blahblah*` repeats the
last `h`; use `blahblah.*` for a prefix match. Name and pattern selection use
Kavita's scanned series list. Duplicate exact names are excluded as ambiguous.
While `assign-file` resolves a processed URL file, it also adds a missing
per-folder source manifest for each unique, image-bearing match. This updates
local identity metadata only; Kavita collection writes still require
`-f/--apply`. Use `-x/--no-index-backfill` to suppress the metadata update.

### Optional SSD scratch staging

When the library is on a slow disk, explicitly place active payloads on a
different, fast volume. For example, with the library on B: and scratch on E:

```powershell
mangadl run -i .\urls.txt -d B:\Hent\hent1imageperpage -S E:\.tmp\mangadl -n
mangadl run -i .\one-known-small-url.txt -d B:\Hent\hent1imageperpage -S E:\.tmp\mangadl -w 1
```

Without `-S`, MangaDL retains its normal paths and behavior. The no-write
preview reports the exact per-library partial and control roots. For supported
backends, payloads, the active gallery-dl archive, state database, and run logs
are staged on scratch and resumable with the same scratch path. Existing
destination control databases are imported before the run. On success, one
worker at a time copies completed files to temporary
names on the destination, then makes each file visible with a same-volume
rename. A collision with different contents or an interrupted copy fails the
job and keeps the remaining scratch data. An SSD destination or scratch volume
removes the fixed four-worker ceiling while preserving the aggregate logical-
CPU budget; if neither is detected as SSD, the ceiling is four.

Gallery-dl's scratch subprocess checks the corresponding library filename
**before** each network download; the normal `gallery-dl.exe` installation is
unchanged. Manga18FX receives the real library as its existing-image root.
These small B: metadata reads, the initial control-database import, and final
promotion/sync cannot be avoided without losing duplicate protection or
archive continuity. The active bulk writes and progress scans stay on E:.
Automatic cover matching in scratch mode inspects only folders promoted by
the job, not the entire B: library.

At run end, state and logs sync back to the configured destination paths. The
archive syncs only when no scratch partial owners remain; otherwise new
archive entries stay on E: so a later non-scratch run cannot treat scratch-only
files as completed library files. Resume with the **same** scratch path.
Existing `B:\...\_partial` owners are not moved; MangaDL refuses to enable
scratch until they are finished or safely cleaned. Do not run two managers
against the same URL/library at once.

Scratch mode currently supports gallery-dl non-collection URLs and Manga18FX.
It refuses HDPornComics, explicit native-nhentai, and broad gallery-dl
collections because their destination-aware skip/layout rules are not yet
verified for this staging path. `optimize`/`benchmark` also reject scratch.
In `run config`, use `--scratch` or `-sd`; its existing `-S` remains the
Kavita API-key setting.

To preview or safely clean *scratch* partials, provide the same root:

```powershell
mangadl partials clean -d B:\Hent\hent1imageperpage -S E:\.tmp\mangadl -t <owner-key>
```

Cleanup is still dry-run-first and archive-aware; for tracked scratch partials
it reconciles both the working and canonical archives when present. Do not
manually delete the scratch tree while a run is active or if a promotion has
failed.

Blank lines and lines beginning with `#` or `;` are ignored. Duplicate and unsupported URLs are reported before workers start.

Broad collection URLs are refused before any worker starts unless
`-G/--allow-collection` is present. This specifically prevents a collection
such as `https://www.simply-hentai.com/series/8-original-work` from silently
expanding into hundreds of galleries. Use a no-write preview before opting in:

```powershell
mangadl run -u $collectionUrl -d .\downloads -n
mangadl run -u $collectionUrl -d .\downloads -G
```


## Favorites/listing URL export

`mangadl favorites` turns an authenticated favorites or listing page into a
normal MangaDL URL file. It reuses the managed per-domain cookie profile and
matching User-Agent when one is present, extracts same-site links, retains only
non-collection URLs recognized by MangaDL/gallery-dl, deduplicates them in page
order, and follows explicit next-page links up to a bounded maximum.

The command is dry-run-first. Preview the URLs without creating a file:

```powershell
mangadl favorites -u https://nhentai.net/favorites/ -o .\nhentai-favorites.txt
```

Write the file only after reviewing the preview:

```powershell
mangadl favorites -u https://nhentai.net/favorites/ -o .\nhentai-favorites.txt -f
```

Use `-P/--max-pages` to bound pagination (default 20), `-D/--page-delay` to
control the delay between listing pages, and `-t/--timeout` for each HTML
request. `-C/--cookies` accepts an explicit Netscape cookie file and takes
precedence over the managed cookie profile. `-B/--cookies-browser` loads cookies
directly from a browser using gallery-dl's browser syntax (for example,
`-B firefox`), matching the existing gallery-dl workflow. `-U/--user-agent`
overrides the stored User-Agent. The crawler does not visit the extracted gallery URLs, so it
avoids the request burst caused by simulating every favorite gallery merely to
discover its URL.

## Safe partial cleanup

Mangadl 1.16+ records ownership metadata and the exact gallery-dl archive key
for each successfully downloaded file retained under `<destination>/_partial`.
With no `-t/--target`, cleanup opens an interactive tree browser. It can
expand/collapse nested content, sort by name/size/created/modified/accessed
time, show the source URL and ownership details, and multi-select top-level
partial owners. Cleanup remains a dry run unless `-f/--apply` is supplied:

```powershell
mangadl partials clean -d .\downloads -a .\gallery-dl-archive.sqlite3
mangadl partials clean -d .\downloads -t fc7c3b753cc0
mangadl partials clean -d .\downloads -t fc7c3b753cc0\simplyhentai\354074 -f
```

In the browser, Space selects an owner, Enter expands/collapses it, `i` shows
details, `c/m/a/s/n` sort, and `D` continues. Interactive apply requires typing
`DELETE`; `-y/--yes` skips that confirmation for automation.

Tracked cleanup validates that the target remains inside `_partial`, refuses a
partial owned by a running worker, optionally verifies `-a/--archive`, backs up
the archive, removes only recorded matching keys, and then deletes the selected
files. Repeat `-t/--target` for multiple selections. `-B/--no-backup` disables
the archive backup only when explicitly requested.

Partials created before 1.16 have no ownership manifest. For a whole legacy
owner, mangadl recovers the source URL from destination-local state, or accepts
`-u PARTIAL_KEY=URL`, then uses gallery-dl metadata traversal with a temporary
empty archive to reconstruct the exact archive keys without downloading media.
Supplying `-a/--archive` is mandatory: matching rows are backed up and removed
before the folder is deleted. Repeat `-s/--state-db` to add state databases.
Missing/ambiguous URLs, nested legacy selections, extractor failures, empty
key sets, active gallery-dl processes, and recently changing large legacy
trees are refused. The tree is fingerprinted again immediately before archive
mutation so a target changed since preview is also refused.

```powershell
mangadl partials clean -d B:\Hent\tmphent3 -t fc7c3b753cc0 `
  -a B:\Hent\tmphent3\mangadl-archive.sqlite3
```

`-F/--files-only` remains an explicit escape hatch. It deletes files without
archive reconciliation and warns that stale archive entries remain.

## Advanced run configuration

Less common settings are organized under `run config`:

```powershell
mangadl run config -i .\urls.txt -d .\downloads -a .\gallery-dl-archive.sqlite3 -w 4 -I 4 -s .\mangadl-state.sqlite3 -r 3 -U 2
```

`run config --help` exposes backend forcing, state/log paths, retries, retry delay, worker ceiling/stagger, gallery-dl configuration and rate limiting, cookies, HDPornComics executable/threads, dry-run, no-UI, quiet, verbose, and log-anonymization compatibility settings.

Dry-run is a human-readable preflight and writes no archive, state, log, or
download files:

```powershell
mangadl run config -i .\urls.txt -d . -w 4 -n
```

Add `-J/--json` when structured dry-run output is required.

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
mangadl run -i .\urls.txt -d .\downloads
```

Each gallery-dl job resolves its own domain profile. Explicit
`-C/--cookies`, `-B/--cookies-browser`, `-g/--gallery-config`, and
`-k/--gallery-user-agent` settings take precedence. A recognized 401/403,
`ChallengeError`, or Cloudflare challenge makes the profile stale even when
its expiry is in the future and the UA is unchanged. The manager performs one
shared background refresh per domain and retries each affected job once; 404, rate-limit,
filesystem, and unrelated backend failures do not refresh credentials.
Refresh progress appears in the dashboard notice without blocking rendering or
keyboard controls. Jobs that report the same challenge wait for the single
domain refresh and restart with the replacement cookie/UA pair.

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

The default outer-worker safety ceiling is four on rotational or unknown storage.
If either destination or scratch is detected as an SSD, there is no additional
fixed worker cap: aggregate Manga18FX concurrency remains bounded below the
detected logical-processor count, with one logical processor reserved for the
manager, dashboard, OS, and filesystem work.

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

Image compression/analysis is available through the reusable compresser library:

```powershell
mangadl compress -d . -m lossless -s 60 -N
mangadl compress -d . -c -m lossless -s 60 -N
mangadl compress -d . -f webp -A pillow-webp -m perceptual -p 0.990 -s 60 -K E:\Temp\compression-cache.sqlite3 -N
```

These commands are read-only (except the explicitly separate cache). Reports
distinguish measured sample savings from coverage-aware projections. Both tools
default to lossless; writes require `-w`, with `-L` additionally for lossy/perceptual.
No larger replacement or output collision is accepted by default. Pending
compression transactions need explicit `compress -d GALLERY -R` recovery preview
and `-R -w -C TOKEN` apply. See [compresser usage](../compresser/README.md).
Production write acceptance and nested-gallery/download coordination are pending.

Audit all recognized manga folders without a URL file, or compare a URL file to
one or more destination roots. Folder-only audits do not change gallery contents. URL-file audits
also backfill a missing `.mangadl-source.json` for unique, image-bearing matches
established by exact source metadata or deterministic backend identity. They
never index ambiguous, conflicting, empty, or unresolved matches. The sidecar
does not alter images, archives, download state, or Kavita collections. Use
`-x/--no-index-backfill` for a strictly read-only URL-file audit.

```powershell
mangadl audit -u .\URLFILE.txt -d .\downloads -j
mangadl audit -i .\URLFILE.txt -d .\downloads -o .\missing.txt -p .\duplicates.json
mangadl audit -F .\url-lists -d .\downloads -r .\audit-report.json
mangadl audit -i .\urls-a.txt -i .\urls-b.txt -d .\downloads -r .\audit-report.json
mangadl audit -i .\urls32.txt -d . -x
mangadl audit -d .\downloads -j
mangadl audit -i .\urls.txt -d .\downloads -j -x
```

`-u/--url-file` is an audit-only alias; `run -u/--url` still takes a direct
URL. Audit checks numbered images for missing pages and undecodable or zero-byte
files. For nhentai URLs it also resolves expected page counts to detect missing
leading and trailing pages. If source metadata is unavailable, visible local
gaps are reported while completeness remains unknown when the total cannot be
proven. Folder-only audits use a MangaDL source manifest or existing gallery-dl
metadata where available; folders without proven identity or expected page
totals remain unknown. URL-file audits also report untracked populated folders.
Audit does not repair or download files. For original URL lists, pass each file
(or a file glob) with repeatable `-i` and the matching library root with
repeatable `-d`; JSON includes created, already-indexed, ambiguous, unresolved,
and conflicting index counts. `-F/--url-directory` loads every top-level
`url*.txt` file in a directory (case-insensitive). Inputs are canonicalized and
deduplicated across every selected file; the report retains the source file and
line for invalid and duplicate entries, including the first occurrence of each
duplicate. Loading progress and the final summary show separate duplicate and
rejected/invalid counts. The console also lists each URL requiring attention,
its matched folder, valid/expected image totals, and missing/corrupt/duplicate
page ranges. A found folder can still be incomplete; image integrity describes
the files present, while completeness checks whether expected pages are missing.
On a terminal, audit shows a transient three-row block: current URL/folder,
its real image-check progress (or indeterminate metadata activity), and overall
completion with elapsed/rolling15-second ETA. Both modes share this renderer.
The metadata spinner indicates activity while waiting for the source; it does
not imply a known metadata percentage. Audit and repair summaries use colored
statuses, separate URL/folder/page fields, and aligned wrapping for long names.
Redirected output stays plain, JSON remains machine-readable, `NO_COLOR`
disables summary colors, and `audit -q` suppresses progress.

Detailed output prioritizes missing/corrupt/duplicate/extra pages; defect-free
unknown/ambiguous entries are counted in the bottom summary. Add `-a/--all-findings`
to list them too. Identity ambiguity never hides image defects. Unknown-total
sequence gaps are explicitly inferred, not source-confirmed, and can't detect
trailing missing pages. Bottom summaries report associations present/creatable/
created/conflicting, including an inventory when `-x` disables index writes.
Source identity reads explicit metadata fields; cover/artist links aren't owners.

Every audit writes a complete versioned JSON report automatically. For a single
`urls32.txt` input and `-d .`, the default is
`mangadl-urls32-audit-report.json` in the destination folder. Existing reports
are preserved: later runs use `mangadl-urls32-audit-report-1.json`, `-2.json`,
and so on. Multiple input files use the first filename plus `-and-N-more`;
multiple destination roots place the report in the first root. Folder-only
audits use `mangadl-folder-audit-report.json`. `-r/--report-output` optionally
sets the filename base and directory; MangaDL appends the input label if absent
and still chooses an unused numbered filename. The actual report path is
printed to the console and included as `report_output` in JSON output.
`-x/--no-index-backfill` prevents source-manifest writes; the report is still
created.

Use the audit report with `repair`. A normal invocation always builds and
prints the current plan; no separate plan file is required. `-p/--plan-output`
only saves an optional machine-readable copy. Applying a plan requires both
`-f/--apply` and the exact confirmation token printed by a fresh preview:

```powershell
mangadl repair -r .\audit-report.json
mangadl repair -r .\audit-report.json -p .\repair-plan.json
mangadl repair -r .\audit-report.json -f -C <preview-token>
mangadl repair -r .\audit-report.json -S E:\Temp -w 3 -f -C <preview-token>
```

Batch repair currently performs the proven operations only: exact-page repair
for individual nhentai galleries and normal MangaDL downloads for wholly
missing, non-collection gallery URLs. It rechecks current folder/page identity,
refuses active MangaDL runs, quarantines corrupt files where applicable,
re-audits the result, and backfills `.mangadl-source.json` only for a unique,
populated match. Ambiguous matches, broad collection URLs, unknown exact page
identity, unsupported backends, and unverifiable results remain prominently
report-only and cause apply mode to return a nonzero status. If a folder has
appeared since the audit marked its URL missing, repair asks for a fresh audit
instead of scheduling another download. Unknown completion is shown as report
only, not silently treated as complete.

Applying a batch now opens the normal MangaDL download dashboard. Every action
for the same destination shares one manager queue, scratch/control setup, and
worker pool; page repair jobs carry separate exact page ranges. `-w/--workers`
sets the initial workers (default 2), `-m/--max-workers` sets the normal worker
ceiling, and the normal dashboard supports adding/retiring workers with `+/-`.
Page bars show the number of planned target pages. `-L/--worker-start-delay`
controls launch staggering (default 2 seconds). `-N/--no-ui` or `-j/--json`
disables the dashboard; JSON mode keeps manager output on stderr. Multiple
destination roots run as separate queues, one root at a time.
The batch acquires one repair lock and archive backup per destination, prepares
all manifests, then runs the queue. Each gallery is verified locally against
its reviewed expected page set and only its targeted archive keys are reconciled.

For supported individual nhentai galleries, `repair-pages` previews the exact
missing/corrupt pages, archive keys, and quarantine targets. Apply requires
`-f` plus the token printed by that exact preview with `-C`; the token is bound
to the reviewed target set. Apply backs up the archive, quarantines corrupt
images, uses a one-worker normal MangaDL job (optionally with `-S`), then
re-audits and reconciles only affected archive keys:

```powershell
mangadl repair-pages -u https://nhentai.net/g/633374/ -d .\downloads -j
mangadl repair-pages -u https://nhentai.net/g/633374/ -d .\downloads -f -C <preview-token> -j
```

Repair remains report-only for unknown folder identity, incomplete page or
archive-key mappings, custom gallery-dl configuration/archive layouts whose
key semantics cannot be proven, active MangaDL runs, and unsupported backends.
Metadata enumeration can request
source pages, but it does not fetch image payloads or mutate the archive.

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
