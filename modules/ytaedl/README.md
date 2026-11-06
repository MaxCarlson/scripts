<!-- version: 2.18.2 -->
# ytaedl

`ytaedl` is a batch download manager for URL text files. It coordinates multiple worker processes, tracks progress from `yt-dlp` and AEBN downloaders, and can optionally move completed MP4 files from a staging/proxy disk to the final media destination.

## Commands

```bash
ytaedl run      [options]            # Interactive download manager
ytaedl worker   [options]            # Single URL-file downloader
ytaedl cleanup  partial [options]    # Delete stale _partial/ dirs
ytaedl cleanup  index   [options]    # Rebuild domain URL index
ytaedl urls     [options]            # URL file scanning and stats
ytaedl archive  [options]            # Archive file management
ytaedl summary  [options]            # Display active instance stats and locks
ytaedl reconcile-aebn [stage]         # Replace historical full movies with verified scenes
```

Run `ytaedl <subcommand> --help` for the full option list of each subcommand.
Run `ytaedl cleanup <operation> --help` for cleanup-specific options.

The `ytaedl run` command is the interactive manager. It scans URL files, starts workers, renders the downloads dashboard, and can enable the MP4 watcher.

## Common Manager Options

```bash
ytaedl -t 12 -L /media/stars -s ./files/downloads/stars -d ./files/downloads/ae-stars
```

Important options:

- `-t/--threads`: number of concurrent workers.
- `-H/--max-workers`: cap for worker slots, including workers added during runtime (default 16).
- `-b/--stay-open`: keep the manager running after its queue drains so more work can be submitted.
- `-i/--priority-files-only`: process only explicitly supplied
  `-p/--priority-files` values. `-t/--threads` requests initial workers and
  `-H/--max-workers` is the upper bound; actual initial workers are clamped to
  both limits. Excess files remain queued and are assigned as workers become free.
- `-pf/--priority-file-scheduling`: in exact mode, choose `file` (finish one
  URL file before taking another; default) or `url` (assign one URL at a time
  and rotate across the selected files, subject to domain limits).
- `-L/--download-root`: final destination root for per-URL-file folders.
- `-P/--proxy-dl-location`: staging root for worker downloads.
- `-w/--enable-mp4-watcher`: enable the MP4 watcher panel and automatic sync.
- `-o/--mp4-operation`: watcher operation, `move` or `copy`.
- `-k/--mp4-max-files`: maximum MP4 files per watcher run.
- `-F/--mp4-trigger-free-gb`: trigger watcher when staging free space drops below this GiB value.
- `-G/--mp4-trigger-total-gb`: trigger watcher when staged MP4 size exceeds this GiB value.
- `-m/--space-remaining`: final destination free-space reserve, such as `1024MB`, `100GB`, `1TB`, or `unlimited`.
- `-x/--max-process-dl-speed`: per-worker download speed cap in MiB/s.
- `-z/--max-total-dl-speed`: global download speed cap in MiB/s.
- `-v/--max-resolution`: highest video resolution requested from workers.
- `-O/--url-order-key`: URL-file priority metric. The manager defaults to `ratio`.
- `-C/--url-order-ascending`: sort URL-file priority ascending instead of descending.
- `-Q/--url-pick-temperature`: add weighted randomness to URL-file selection. `0` is deterministic.
- `-Z/--url-random-order`: ignore URL priority metrics and pick URL files fully at random.

All CLI arguments have short and long forms.

## Exact URL-File Mode

Use exact mode when multiple `ytaedl` manager instances should process
different, manually selected URL files concurrently:

```bash
ytaedl run -i \
  -p ./files/downloads/stars/channel-a.txt \
  -p ./files/downloads/stars/channel-b.txt
```

`-i/--priority-files-only` changes the existing repeatable
`-p/--priority-files` option from a priority hint into the complete workload.
By default (`--priority-file-scheduling file`) the manager:

- creates at most `min(-t, unique URL files)` initial workers;
- queues extra URL files until a worker becomes available;
- does not scan the normal URL roots or use domain-index scheduling;
- keeps each worker on its assigned file until that file is complete.

Use `-pf url` (or `--priority-file-scheduling url`) to assign a single URL per worker task.
The manager rotates file priority after each assignment and uses the existing
domain-index scheduler, domain concurrency limits, URL-file locks, and archive
statuses. This mode builds a private in-memory index from only the selected
files, so it does not rewrite the shared persistent domain index.
Each source URL file is assigned exclusively to one worker at a time. This
prevents duplicate URL assignment and preserves URL-file lock safety, but caps
simultaneous URL-mode assignments at the number of currently eligible source
files (for example, two files can use at most two workers even with `-t 8`).
Workers that have no eligible URL wait and periodically retry, so they resume
when a source-file lock or domain concurrency slot becomes available.

In exact whole-file mode, a failed or timed-out file receives one immediate
retry. If it still fails, or the manager is deliberately stopped, the file is
saved in the durable manual-submission queue for restart recovery. Completed
URL archive progress remains available to skip already completed URLs on retry.
The manager logs unresolved files when it exits with work retained.

In whole-file mode, each worker takes an operating-system lock before reading
or downloading URLs. Rotating URL mode checks the same lock sidecars before
assigning a URL from a source file. Lock sidecars are stored under:

```text
<archive>/locks/<url-file-name>.<canonical-path-hash>.ytaedl.lock
```

The canonical full-path hash makes identically named files in different
directories distinct. For example, `f1/urlfile.txt` and `f2/urlfile.txt`
produce different lock filenames even though both retain the readable
`urlfile.txt` prefix.

If another worker owns the same canonical URL file, the downloads panel shows
`WAITING: URL FILE LOCK` until the owner exits. Other requested files continue
running normally.

The sidecar file remains on disk, but its existence does not mean the URL file
is locked. The held OS lock is authoritative and is automatically released
when the worker exits, receives Ctrl+C, or is forcibly terminated. Standalone
`ytaedl worker` commands use the same lock and refuse to process an already
locked URL file.

## Real-Time Summary Mode

Use `ytaedl summary` to see real-time statistics and active locks across all currently running `ytaedl` manager instances:

```bash
ytaedl summary
```

Each manager instance periodically writes its runtime, active workers count, completed downloads count, average and current speeds, and held locks to `archive/instance_stats/active_manager_<pid>.json`. On normal or abnormal exit, the file is archived to `archive/instance_stats/stats_archive/` and renamed to include start and end times.

The `summary` command reads these files, automatically archives any stale files from dead or unresponsive managers, and displays a color-coded, aligned grid showing each active manager instance and its held locks grouped by parent directory.

Total stats files (active + archived) are capped at 50, automatically deleting the oldest archived files on startup.

## AEBN Historical Scene Reconciliation

Use reconciliation when an AEBN scene URL was historically marked complete even
though ytaedl saved the full movie. The workflow reads ordinary scene URL files
with their original `#scene-<id>` fragments, resolves IDs from AEBN movie
metadata, inventories only the roots you specify, downloads missing scenes into
a separate replacement directory, and verifies each output before any original
can be approved.

Start with a read-only scan (metadata requests are made unless `--offline` is
used):

The Python environment that runs `ytaedl` must also be able to import the
repository's `aebn_dl` package, because scene replacement runs
`python -m aebn_dl.cli` in that same environment. From the repository root,
install both packages into the active environment when needed:

```powershell
python -m pip install -e modules/ytaedl -e modules/aebndl_module
```

```powershell
ytaedl reconcile-aebn scan `
  -f 'C:\downloads\aebn-scenes.txt' `
  -L 'B:\stars' `
  -a 'C:\downloads\archive' `
  -p 'C:\downloads\reconcile\state.sqlite'
```

Each stage is explicit and resumable:

```powershell
ytaedl reconcile-aebn status -p 'C:\downloads\reconcile\state.sqlite'
ytaedl reconcile-aebn download -p 'C:\downloads\reconcile\state.sqlite' -n
ytaedl reconcile-aebn download -p 'C:\downloads\reconcile\state.sqlite' --apply -t 2
ytaedl reconcile-aebn verify -p 'C:\downloads\reconcile\state.sqlite'
ytaedl reconcile-aebn review -p 'C:\downloads\reconcile\state.sqlite'
ytaedl reconcile-aebn archive-sync -p 'C:\downloads\reconcile\state.sqlite' -n
ytaedl reconcile-aebn delete -p 'C:\downloads\reconcile\state.sqlite'
```

Replacement downloads use the installed `aebn_dl` downloader with an explicit
`-I <scene-id>` argument. They are isolated under
`<download-root>/AEBN Scene Replacements/<movie-id>` and are not suppressed by
old ytaedl archive entries. The SQLite database uses schema version 1 and WAL;
it stores metadata, source lines, file identities, download/verification state,
approvals, and an append-only event journal. `export -f csv` or `export -j`
produces reviewable reports.

Full-movie matching requires title/studio token evidence and a plausible
movie-length probe. Weaker or colliding matches remain ambiguous and require
manual identity confirmation. A historical archive status is never verification
evidence. Every requested scene linked to an original must verify before that
original can be approved. Approval is bound to the original file identity and
replacement evidence; changed or missing evidence makes it stale.

Removal is a separate operation. It defaults to a dry-run and, after recorded
per-file approval, `--apply --confirm 'DELETE N'` moves originals into a
same-volume `.ytaedl-reconcile-quarantine` directory. Quarantine is reversible
and does not itself free disk space. Permanent deletion requires both
`--permanent` and `--confirm-permanent 'PERMANENTLY DELETE N'`. The tool never
falls back from quarantine to permanent removal. Archive sync is separate and
uses the existing source-file and domain-index locks; it defers when a lock is
held. Scans do not modify archives, indexes, or media.

## yt-dlp Worker Defaults

For yt-dlp URLs, the manager-launched worker defaults to Firefox cookies,
Chrome impersonation, and the `aria2c` external downloader. The direct worker
command exposes controls for these defaults:

- `-b/--ytdlp-cookies-from-browser`: browser profile used for cookies; use
  `none` to disable cookie extraction.
- `-i/--ytdlp-impersonate`: browser TLS/user-agent impersonation target; use
  `none` to disable it.
- `-d/--ytdlp-downloader`: external downloader; use `native` to use yt-dlp's
  built-in downloader.

```bash
ytaedl worker -b none -i none -d native <url-file>
```

## Interactive Panels

Downloads panel hotkeys:

- `w`: watcher panel.
- `u`: URL stats panel.
- `d`: downloads panel.
- `Up/Down`: select worker.
- `j` / `k`: scroll the worker list when it extends beyond the visible screen.
- `1` through `9`: select workers 1 through 9 directly.
- `P`: pause or resume the selected worker.
- `p`: pause or resume all workers.
- `x`: toggle controlled quit, which finishes active URLs and starts no new downloads.
- `i`: open a multiline URL and URL-file submission dialog; press Ctrl+S to validate, then choose queue or additional workers.
- `h`: toggle the normal top status bars while keeping workers and verbose output visible.
- `v`: cycle verbose pane between off, NDJSON, and worker program log.
- `q`: quit with confirmation.

Watcher panel hotkeys:

- `d`: downloads panel.
- `u`: URL stats panel.
- `c`: start a watcher run.
- `s`: scan with dry-run.
- `o`: toggle copy/move mode.
- `k`: set max files per watcher run.
- `f`: set staging free-space trigger in GiB.
- `m`: set final destination space reserve, using values like `1024MB` or `100GB`.
- `[` and `]`: scroll watcher logs.
- `q`: quit with confirmation.

URL stats panel hotkeys:

- `d`: downloads panel.
- `w`: watcher panel.
- `r`: rescan URL stats.
- `a`: toggle URL-panel auto refresh.
- `s`: cycle display sort through `ratio desc`, `ratio asc`, `stars desc`, `remaining desc`, `GB desc`, and `unique desc`.
- `/`: search by name. Plain text matches substrings; glob patterns like `mary_*` or `*rock` are supported.
- `Esc`: clear the active search filter.
- `j` and `k`: scroll vertically.
- `h` and `l`: scroll horizontally.
- `q`: quit with confirmation.

## Partial Download System

When a download is interrupted (killed, stalled, or crashed), ytaedl leaves a
per-URL working directory under the staging channel folder:

```text
B:\stars\<channel>\
├── completed_video.mp4
└── _partial\
    ├── a1b2c3d4e5f6\       <- sha256(url)[:12] -- deterministic per URL
    │   ├── meta.json        <- {"url": "...", "file_path": "...", "started_at": ...}
    │   └── Title.mp4.part   <- yt-dlp in-progress fragment (resumable)
    └── 9f8e7d6c5b4a\
        └── ...
```

On the next run, ytaedl detects these directories and prioritizes those URLs
ahead of all others (within domain capacity limits).  yt-dlp finds the `.part`
file and resumes the download automatically.

### Partial-priority flags (manager)

- `-A/--prioritize-partial` *(on by default)*: scan `_partial/` at startup and
  move resumable URLs to the front of their domain queues.  Use
  `--no-prioritize-partial` to disable.
- `-c/--cleanup-partial-on-start`: before launching any workers, scan for stale
  `_partial/` directories, show a deletion summary in red, require you to type
  `DELETE` to confirm, delete them, and remove the corresponding archive
  entries.  Combine with `--dry-run` to preview without deleting.

### Standalone cleanup (single-worker CLI)

```bash
ytaedl-download -K --cleanup-partial -P B:\stars\ --dry-run   # preview
ytaedl-download -K --cleanup-partial -P B:\stars\             # delete with confirmation
```

### Safety rules

- Finished `.mp4` files are **never** deleted by any cleanup command.
- Only files inside `_partial/<hash>/` subdirectories are removed.
- Any bulk deletion outside normal per-URL success cleanup prints a red summary
  and requires the user to type `DELETE` interactively.

### Partial Download System Version History

| Version | Description                                                          |
|---------|----------------------------------------------------------------------|
| v2.0.0  | Per-URL `_partial/<hash>/` dirs with `meta.json` sentinels. Current. |
| v1.x    | Shared `_tmp/` dir (deleted; not used by this codebase).             |

#### How to bump the major version

When the `_partial/` directory format changes in an incompatible way:

1. Increment `PARTIAL_SYSTEM_VERSION` in
   [`_partial_utils.py`](ytaedl/_partial_utils.py) (e.g. `"2.0.0"` → `"3.0.0"`).
2. Add an entry to `PARTIAL_SYSTEM_CHANGELOG` keyed by the new major integer.
3. Update the table above.
4. Commit: `"partial: bump major version to N — <reason>"`.

On next startup the manager detects the stored version mismatch, prints the
changelog entry, shows the deletion summary, and asks the user to type `DELETE`
before deleting old-format data.

## URL Priority

The manager prioritizes URL files by ratio descending by default. The ratio is the remaining URL count divided by already downloaded MP4 count. URL files with remaining URLs and zero downloaded MP4 files have an infinite ratio, and infinite ratios are treated as higher priority than any finite ratio.

Examples:

```bash
ytaedl -O ratio
ytaedl -O remaining
ytaedl -O gb -C
```

Use `--url-pick-temperature` to keep the same ranking while adding controlled randomness to assignment:

```bash
ytaedl -O ratio --url-pick-temperature 0
ytaedl -O ratio --url-pick-temperature 0.75
```

At `0`, the top-ranked eligible URL file is chosen. Higher temperatures flatten the weighted distribution, making lower-ranked URL files more likely without becoming fully random. Use `--url-random-order` for full random assignment.

## Domain-Diverse Scheduling

Before assigning a URL file, the manager estimates each candidate's source domains by reading its remaining URL file and normalizing URL hosts. Hosts are lowercased and a leading `www.` is stripped; no public suffix parsing is added, so subdomains such as `cdn.example.com` remain distinct.

The scheduler prefers URL files that add new active domains across workers, then falls back to the configured URL priority rank. This helps spread active downloads across sites and reduce throttling from sending too many workers to one host.

Priority files passed with `-p/--priority-files` still win over the regular pool, but when multiple priority files are available the manager uses the same domain-diverse tie-break. If `--url-pick-temperature` is greater than zero, selection is sampled from the domain-scored order. If `--url-random-order` is set, full random assignment overrides both ranking and domain diversity.

The downloads panel shows each worker's current domain as `Dom example.com`. The top status area also shows current and running-average active domain counts, for example:

```text
Domains: 4 now / 3.2 avg
Active domains: a.example,b.example,c.example,+
```

## Controlled Quit And Status Visibility

Press `x` on the downloads panel to enter controlled quit mode. The manager stops assigning new URL files and each worker finishes its current URL before exiting its assigned URL file. Active tool subprocesses are not terminated for controlled quit.

Press `i` while the manager is running to submit one URL or existing URL-file path per line. URL query strings and fragments are retained. Select queueing or request additional worker slots; submissions are stored under the configured log directory in `pending_manual_submissions.json` and restored after a restart. Manual work is scheduled ahead of regular URL files while remaining subject to domain and global bandwidth limits. Use `--stay-open` to receive submissions when starting without work or after the queue drains; additional slots are capped by `--max-workers`.

While controlled quit is enabled, the pinned downloads header shows:

```text
CONTROLLED QUIT eta 120s
```

The ETA is the largest known ETA among active workers. It shows `?` if any active worker does not have an ETA and `0s` after all workers are idle. The manager exits cleanly once controlled quit is active and no workers remain.

The manager implements this by passing `-B/--stop-sentinel` to `ytaedl-download`. The worker checks that sentinel before each new URL and exits without starting another URL when it exists.

Press `h` on the downloads panel to hide or show the normal top status bars. Worker rows, footer keys, and verbose output remain visible. Critical alerts, including controlled quit and destination disk-space alerts, remain visible even when normal status bars are hidden.

## MP4 Watcher Space Guard

When `--enable-mp4-watcher` is active, the watcher builds a transfer plan from the staging root to the final destination root. The `-m/--space-remaining` option reserves free space on the final destination disk.

Example:

```bash
ytaedl -w -P B:/staging -L D:/stars --space-remaining 100GB
```

With this setting, the watcher only moves/copies files that fit while leaving at least `100GB` free on the destination disk. If no planned transfer fits, no files are moved and both the downloads and watcher status areas show:

```text
NO DISK SPACE LEFT AT FINAL DESTINATION
```

This destination reserve is separate from `--mp4-trigger-free-gb`, which watches the staging/tmp disk and decides when automatic cleanup should start.

## Units

Download sizes and speeds use binary units:

- `B`, `KiB`, `MiB`, `GiB`, `TiB`
- rates append `/s`, for example `7.82 MiB/s`

Disk and storage values use disk labels:

- `B`, `KB`, `MB`, `GB`, `TB`
- values switch units at 1024 of the current unit, so `1023MB` remains `1023MB` and `1024MB` becomes `1GB`.

## Tests

Run the ytaedl test suite from the repository root:

```bash
pytest modules/ytaedl/tests -v
```

If TermDash utility formatting changes are touched, also run:

```bash
pytest modules/termdash/tests/utils_test.py -v
```
