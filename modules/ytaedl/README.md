# ytaedl

`ytaedl` is a batch download manager for URL text files. It coordinates multiple worker processes, tracks progress from `yt-dlp` and AEBN downloaders, and can optionally move completed MP4 files from a staging/proxy disk to the final media destination.

## Commands

```bash
ytaedl [options]
ytaedl urls [url-scan-options]
ytaedl archive [archive-options]
ytaedl-download [single-worker-options]
```

The main `ytaedl` command is the interactive manager. It scans URL files, starts workers, renders the downloads dashboard, and can enable the MP4 watcher.

## Common Manager Options

```bash
ytaedl -t 12 -L /media/stars -s ./files/downloads/stars -d ./files/downloads/ae-stars
```

Important options:

- `-t/--threads`: number of concurrent workers.
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

## Interactive Panels

Downloads panel hotkeys:

- `w`: watcher panel.
- `u`: URL stats panel.
- `d`: downloads panel.
- `Up/Down`: select worker.
- `1` through `9`: select workers 1 through 9 directly.
- `P`: pause or resume the selected worker.
- `p`: pause or resume all workers.
- `x`: toggle controlled quit, which finishes active URLs and starts no new downloads.
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
