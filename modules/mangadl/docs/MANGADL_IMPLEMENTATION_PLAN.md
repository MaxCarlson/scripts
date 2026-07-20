# mangadl Implementation Plan

Date: 2026-07-12
Status: planned; no manga downloader code has been created yet
Project root: `C:\Users\mcarls\src\scripts`

## Decision

Create a new Python module at `modules/mangadl/` with the public CLI `mangadl`.

The module will be a manga/gallery download manager modeled after the useful operational parts of `ytaedl`: a manager process, isolated workers, NDJSON progress events, an in-place `termdash` UI, persistent job state, archives, restart recovery, and extensive logs.

Do not renovate `pscripts/modules/hentai_cli` in place. It is a small, working nhentai-only wrapper and should remain available until `mangadl` has passed real-world validation. Reuse its URL/ID parsing behavior and test cases, but do not migrate or delete it.

Use `gallery-dl` as the primary backend. Add a backend router so each URL is assigned to the best available downloader. Keep an optional `pshentai`/native-nhentai backend as a fallback for nhentai URLs. Future backends must implement the same adapter contract.

## Why gallery-dl Is the Primary Backend

The locally installed `gallery-dl` is version `1.32.6`. Its extractor inventory includes nhentai, ExHentai/E-Hentai, hentai2read, allporncomic, hentaihand, MangaDex, multiple general manga sites, and many other gallery sites. Its nhentai defaults already produce one gallery directory per manga and use a page-level SQLite download archive.

The current command is a valid baseline:

```powershell
gallery-dl.exe -i .\hetailistnhentai2.txt -d .\test\ --download-archive .\gallery-dl-archive.sqlite3
```

Current local evidence from `D:\Pictures\Saved\tmpvids\tmphent-tmp`:

- `hentailistnhentai.txt`: 43 non-empty unique URLs.
- `hetailistnhentai2.txt`: 74 non-empty unique URLs.
- `gallery-dl-archive.sqlite3`: 7,775 archived file/page records.
- 163 output directories currently exist in the working directory.

The archive count proves that gallery-dl's archive is file-level, not a complete manager-level record of source URLs, galleries, attempts, failure classes, or run history. `mangadl` therefore needs its own URL/job ledger in addition to gallery-dl's archive.

Official references:

- gallery-dl project: https://github.com/mikf/gallery-dl
- supported sites: https://github.com/mikf/gallery-dl/blob/master/docs/supportedsites.md
- configuration: https://gdl-org.github.io/docs/configuration.html

HakuNeko and FMD2 are useful end-user manga applications, but they are desktop/GUI-oriented systems rather than stable headless worker engines. They are not initial backends. Their connector coverage can be revisited only if gallery-dl lacks a required site.

## Current Code Status

### `pscripts/modules/hentai_cli` (`pshentai`)

Status: working seed code, not a suitable manager foundation.

- Accepts `-i/--id` and `-f/--file`.
- Extracts nhentai gallery IDs from raw IDs or URLs.
- Downloads sequentially through the separate `nhentai` executable.
- Supports an auth file containing user-agent and cookie values.
- Tracks only in-memory success/failure lists.
- Has no persistent manager state, archive selection, concurrency, progress transport, speed metrics, retries, TUI, or structured logs.
- Existing tests pass: 8 passed.
- README is minimal and has not kept pace with the repository's newer documentation/version conventions.

Reusable pieces:

- URL/ID normalization semantics.
- Input-file handling tests.
- Missing-executable and command-failure test patterns.
- Native nhentai command construction as an optional fallback adapter.

### `D:\Pictures\Saved\tmpvids\modules\nhentai-dl\dlnh.py` and `dlnhv2.py`

Status: legacy prototypes.

- Sequential wrappers around the `nhentai` executable.
- Duplicate most of `pshentai`.
- Depend on local plaintext credential files.
- No tests, durable state, concurrency, structured logging, or live metrics.

Use only as historical evidence. Do not migrate or delete them.

### `D:\Pictures\Saved\tmpvids\pyscripts\roundrr.py` and `roundrr_parallel.py`

Status: useful scheduling prototypes, unsafe as a direct base.

- Demonstrate URL-file rotation, process spawning, progress-line parsing, time limits, and domain concurrency.
- Text archives mark URLs processed too eagerly, including failures/timeouts.
- State is not transactional and cannot safely recover worker ownership after a crash.
- Logging and error classification are too weak for the requested manager.

Reuse concepts only: bounded concurrency, worker assignment, and subprocess stream handling.

### `modules/ytaedl`

Status: current and feature-rich, but too specialized and monolithic to import as the new manager.

Reuse patterns:

- Manager/worker process separation.
- Worker NDJSON event stream.
- Attempt IDs/generations so stale progress cannot overwrite a new assignment.
- Worker state clearing at assignment boundaries.
- Selected-worker and global pause/resume.
- Controlled quit: finish active jobs and assign no new jobs.
- Per-worker program logs plus manager-side event logs.
- Atomic active-instance statistics snapshots.
- `termdash` top statistics, worker rows, verbose pane, and fixed footer controls.
- Process-tree shutdown behavior and Windows `psutil` support.

Do not copy `manager.py` wholesale. Build smaller manga-specific modules with explicit contracts.

### Old `plans/refactor/refactor_plan_media-dl.md`

Status: stale and superseded for this work.

- References a missing `downloads_dlpn/` tree.
- Proposes a broad `pyprjs/media-dl` migration and deletion of source scripts.
- Combines video, manifests, manga, and unrelated utilities.
- Conflicts with the current requirement to avoid migrations and focus on a formal manga/gallery manager.

Keep it as historical evidence. This plan is authoritative for `mangadl`.

## Documentation Freshness

Scores use 0 as healthy and 100 as stale.

| Scope | Score | Assessment |
|---|---:|---|
| `ytaedl` | 15 | Current README and version history closely track CLI/manager behavior. |
| `pshentai` | 70 | Code works and tests pass, but README is only a minimal package note and omits operational constraints. |
| legacy `dlnh*` | 95 | No maintained docs/tests and duplicated by `pshentai`. |
| old media-dl plan | 100 | Paths and migration assumptions are no longer current. |
| current gallery-dl workflow | 35 | The command works, but configuration, state ownership, and recovery are informal. |

Docs task: when Stage 1 starts, create `modules/mangadl/docs/README.md`, `docs/HANDOFF.md`, and `docs/plans/HANDOFF.md` before behavior is implemented.

## Scope

Initial supported workload:

- One or more URL text files, each containing one URL per line.
- Direct URLs supplied on the command line.
- nhentai gallery URLs.
- Other gallery/manga URLs supported by the installed gallery-dl extractors.
- Multiple concurrent workers, each owning exactly one URL job at a time.
- One output folder per manga/gallery, containing its images and optional metadata.
- Shared download archive plus persistent manager state.
- Interactive and non-interactive operation.
- Restart/resume after manager or worker failure.
- Extensive manager, worker, raw backend, and structured event logs.

Explicitly out of scope for the first implementation:

- Migrating or deleting `pshentai`, `dlnh*`, HakuNeko, FMD2, or organizer scripts.
- OCR, summarization, tagging, Jellyfin organization, renaming, or author-folder consolidation.
- A universal video downloader.
- Browser automation for unsupported sites.
- Circumventing access controls, CAPTCHAs, or site restrictions.

Post-download hooks for existing organizer tools may be added later, but downloads must complete correctly without them.

## Proposed Package Layout

```text
modules/mangadl/
├── pyproject.toml
├── README.md
├── AGENTS.md                         # only if module-specific rules are needed
├── docs/
│   ├── README.md
│   ├── HANDOFF.md
│   └── plans/HANDOFF.md
├── mangadl/
│   ├── __init__.py
│   ├── cli.py
│   ├── manager.py
│   ├── worker.py
│   ├── models.py
│   ├── input_files.py
│   ├── scheduler.py
│   ├── state_db.py
│   ├── events.py
│   ├── metrics.py
│   ├── logging_config.py
│   ├── paths.py
│   ├── process_control.py
│   ├── ui.py
│   ├── config.py
│   └── backends/
│       ├── base.py
│       ├── router.py
│       ├── gallery_dl.py
│       └── native_nhentai.py
└── tests/
    ├── conftest.py
    ├── cli_test.py
    ├── input_files_test.py
    ├── router_test.py
    ├── state_db_test.py
    ├── scheduler_test.py
    ├── events_test.py
    ├── metrics_test.py
    ├── manager_test.py
    ├── worker_test.py
    ├── gallery_dl_backend_test.py
    ├── recovery_test.py
    └── ui_layout_test.py
```

Package name: `mangadl`

Public entry point:

```toml
[project.scripts]
mangadl = "mangadl.cli:main"
```

Initial version: `1.0.0`, because the first release establishes a formal public CLI and entry point.

Dependencies:

- `gallery-dl>=1.32,<2`
- `termdash>=0.5`
- `psutil>=5.9` on Windows

No dependency on `ytaedl`. Reuse its design patterns, not its package internals.

## CLI Design

Every user-facing option must have both short and long forms.

### Commands

```text
mangadl run       Run the manager and optional interactive UI.
mangadl worker    Internal/single-job worker; also useful for diagnostics.
mangadl inspect   Parse inputs, validate URLs, select backends, and estimate work.
mangadl status    Show active/recent run state without joining the TUI.
mangadl retry     Requeue selected failure classes or a prior run's failures.
mangadl archive   Inspect/verify manager and gallery-dl archives.
```

### `mangadl run`

Required/primary options:

```text
-i, --input-file PATH       Repeatable URL file.
-u, --url URL               Repeatable direct URL.
-D, --destination PATH      Destination root.
-a, --archive PATH          gallery-dl SQLite download archive.
-S, --state-db PATH         mangadl manager state database.
-t, --workers N             Concurrent workers; default 2.
-b, --backend NAME          auto, gallery-dl, or native-nhentai.
-c, --config PATH           mangadl TOML configuration.
-g, --gallery-config PATH   Optional gallery-dl JSON/TOML/YAML configuration.
-l, --log-dir PATH          Run and worker log root.
-r, --retries N             Per-URL retry count.
-w, --retry-wait SECONDS    Retry delay/backoff base.
-x, --max-rate RATE         Per-worker gallery-dl rate limit.
-k, --cookies PATH          Netscape cookies file.
-B, --cookies-browser NAME  Browser cookie source.
-n, --dry-run               Parse/probe without downloading.
-U, --no-ui                 Plain log/status output.
-q, --quiet                 Reduce console output; logs remain complete.
-v, --verbose               Show detailed diagnostics.
```

Validation rules:

- Require at least one `--input-file` or `--url`.
- Require destination, archive, state DB, and log paths to resolve independently.
- Reject archive/state DB path collisions.
- Reject worker counts below 1.
- Never prompt inside workers; authentication prompts belong to manager preflight.

### `mangadl inspect`

Print a table or JSON report with:

- total input lines;
- blank/comment lines;
- invalid URLs;
- duplicate input URLs;
- URLs already complete in manager state;
- selected backend and extractor/site;
- URLs unsupported by every backend;
- galleries/pages discoverable during optional preflight;
- authentication/config requirements.

### `mangadl retry`

Allow retry selection by:

- run ID;
- input file;
- URL;
- failure category;
- retryable-only default;
- maximum attempts.

## Backend Router

Define a small adapter protocol:

```python
class DownloadBackend(Protocol):
    name: str

    def probe(self, url: str, config: BackendConfig) -> ProbeResult: ...
    def prepare(self, job: Job, paths: JobPaths) -> PreparedJob: ...
    def run(self, prepared: PreparedJob, emit: EventEmitter) -> BackendResult: ...
    def cancel(self) -> None: ...
```

`ProbeResult` includes:

- supported boolean;
- confidence score;
- canonical URL;
- site/category/extractor;
- authentication requirements;
- reason when unsupported.

Routing order:

1. Explicit `--backend` override, if supplied.
2. Site-specific configured backend preference.
3. `gallery-dl` when `gallery_dl.extractor.find(url)` resolves an extractor.
4. `native-nhentai` for nhentai gallery URLs when installed/configured.
5. Unsupported classification with no worker assignment.

Fallbacks are configured per site, for example:

```toml
[routing.nhentai]
backends = ["gallery-dl", "native-nhentai"]

[routing.default]
backends = ["gallery-dl"]
```

Do not run multiple backends simultaneously for one URL. The manager advances to a fallback only after the active backend returns a retry/fallback-eligible failure.

## gallery-dl Worker Integration

Run each worker as a separate `python -m mangadl.worker` process. Inside that process, use gallery-dl's Python package rather than scraping human console output.

Implement a narrowly isolated gallery-dl adapter around `gallery_dl.job.DownloadJob` and a custom output/progress sink. The installed gallery-dl internals expose:

- extractor metadata and directory events;
- file preparation and final paths;
- file skip/archive checks;
- file success/error hooks;
- HTTP progress values: total bytes, downloaded bytes, and bytes per second.

The adapter emits stable mangadl NDJSON regardless of gallery-dl internal object shape. Pin gallery-dl below the next major version and add contract tests so an upstream API change fails clearly.

Worker stdout is NDJSON only. Raw backend logs go to the worker's raw log file. This avoids fragile mixed text/event parsing.

Required worker events:

```text
worker_ready
job_start
extractor_selected
gallery_metadata
gallery_start
file_start
file_progress
file_skip_archive
file_skip_existing
file_complete
file_failure
gallery_complete
job_retryable_failure
job_terminal_failure
job_complete
heartbeat
worker_stopping
```

Every event includes:

- schema version;
- run ID, job ID, attempt ID, worker slot;
- monotonic and wall-clock timestamps;
- source URL and canonical URL where safe;
- backend/site/extractor;
- relevant counts and byte values.

Credentials and cookie values must never appear in NDJSON or logs.

## Input and Job Model

Parsing rules:

- UTF-8 with replacement for malformed bytes and explicit warning counts.
- Ignore blank lines.
- Ignore lines beginning with `#` or `;`.
- Allow trailing comments only after two spaces followed by `#` or `;`, matching ytaedl behavior.
- Stable deduplication: first occurrence owns source attribution; later occurrences are counted as duplicates.
- Preserve source file and source line number.
- Canonicalize nhentai IDs to `https://nhentai.net/g/<id>/`.
- Let the selected backend canonicalize other supported sites.

Core states:

```text
discovered -> validated -> queued -> leased -> running
running -> succeeded | skipped_archive | skipped_existing
running -> retry_wait -> queued
running -> failed_bad_url | failed_auth | failed_http | failed_rate_limit
running -> failed_extractor | failed_filesystem | failed_archive
running -> failed_backend | canceled | interrupted
```

Terminal success-like states and failure states remain distinct. A duplicate input is not a download failure. An archive skip is not a bad URL.

## Persistent State Database

Use a manager-owned SQLite database separate from gallery-dl's archive.

Recommended tables:

- `runs`: invocation, config snapshot, timestamps, completion state.
- `sources`: input files and fingerprints.
- `jobs`: canonical URL, source attribution, backend, state, lease, counters.
- `attempts`: worker/backend attempt history and failure classification.
- `events`: compact durable event ledger or references to JSONL offsets.
- `artifacts`: final folder, image count, bytes, metadata paths.
- `workers`: active slot/PID/heartbeat/assignment state.

Use WAL mode, foreign keys, and a busy timeout. All claims occur in short manager transactions. Workers do not mutate manager state directly; they emit events and the manager writes state.

Lease rules:

- A queued job is atomically leased to one worker.
- Lease includes worker slot, PID, attempt ID, and heartbeat deadline.
- On startup, expired leases return to `queued` or `retry_wait` according to attempt policy.
- A stale event with the wrong attempt ID is logged and ignored.

## Archive and Duplicate Semantics

Two layers are required:

1. Manager state DB: URL/gallery-level scheduling and outcomes.
2. gallery-dl archive: image/file-level deduplication.

Use the user-supplied gallery-dl archive path unchanged. gallery-dl's SQLite archive uses a 60-second timeout and autocommit; multiple worker processes can share it, but lock errors must be classified as `failed_archive` and retried with jitter.

Manager safeguards:

- Never assign the same canonical URL twice concurrently.
- Record duplicate input lines before workers start.
- Do not mark a gallery complete merely because some pages are archived.
- A gallery is complete only after the backend finishes extraction and every emitted file is complete or archive/existing-skipped.
- Preserve partial files for gallery-dl resume behavior.
- On retry, reuse the same destination template and archive.

## Output Layout

Default layout:

```text
<destination>/
├── nhentai/
│   └── <gallery-id> <safe-title>/
│       ├── 001.jpg
│       ├── 002.jpg
│       └── info.json                 # optional, enabled by default
├── exhentai/
│   └── <gallery-id> <safe-title>/
└── <other-site>/
    └── <stable-id> <safe-title>/
```

Use a generated per-run gallery-dl config to enforce deterministic, Windows-safe names. Keep a site/category directory by default to prevent ID/title collisions across sites.

Requirements:

- One final directory per manga/gallery.
- Stable site-specific identifier precedes title.
- Windows-invalid characters are normalized.
- Long paths are bounded with deterministic hash suffixes.
- Existing matching directories are resumed, not renamed unpredictably.
- Temporary metadata/config files live under the run log/state root, not the destination library.

## Manager and Worker Scheduling

Use a fixed worker-slot pool. Each slot requests a new job only after its current job reaches a terminal or retry-wait state.

Manager responsibilities:

- parse and validate inputs;
- select backend candidates;
- atomically claim jobs;
- spawn and supervise worker processes;
- consume NDJSON and update state/metrics;
- enforce retry/backoff and global stop conditions;
- render UI or plain status;
- write logs and final summaries;
- terminate complete process trees on forced exit.

Worker responsibilities:

- process exactly one job attempt;
- initialize one backend adapter;
- emit NDJSON and heartbeat events;
- write its raw backend log;
- exit with a documented semantic return code.

Initial default: 2 workers. Nhentai and similar sites can rate-limit aggressively; concurrency should be user-controlled and conservative. Add per-site concurrency caps:

```toml
[sites.nhentai]
max_workers = 2
sleep_request = "0.5-1.5"
```

The scheduler enforces both global worker count and per-site limits.

## Progress and Metrics

Do not expose gallery-dl's default line-per-image console output as the primary UI. Capture it in the assigned worker's raw log and render a stable, in-place summary from structured worker events.

Each active worker row must show the assigned source URL, site/title/destination, image counts, downloaded/total/remaining bytes when known, current and per-URL average transfer rate, current and per-URL average images per second, attempt number, elapsed time, and failures. Current rates use a short rolling window; URL averages reset when the next URL is assigned. Unknown totals use an activity indicator rather than fabricated percentages.

Track both manga/gallery units and image/file units.

Exact metrics:

- input URLs total;
- queued/running/succeeded/skipped/failed manga count;
- duplicate and invalid input count;
- pages discovered/completed/skipped/failed;
- bytes downloaded in this run;
- active-file downloaded/total bytes;
- current aggregate download speed;
- per-worker current speed;
- elapsed time;
- retry counts and failure classes.

Derived metrics:

- average pages/items per second;
- average manga per hour;
- run-average bytes per second;
- active-file remaining bytes;
- estimated gallery/run remaining bytes;
- estimated ETA.

Important accuracy rule: total remaining bytes for an entire manga are not always known before each image response provides `Content-Length`. Display exact active-file remaining bytes and label wider estimates as `est.`. Estimate undiscovered byte totals from the rolling median page size for that site, never as an exact value.

Speed accounting must use monotonic timestamps and byte deltas. Archive skips and existing-file skips do not count as downloaded bytes or download speed.

## TUI Design

Worker rows are selectable using the ytaedl interaction model. `l` opens or closes a live log for the selected worker, `r` toggles its structured log versus captured raw gallery-dl output, Up/Down or `j`/`k` changes selection, `p` pauses the selected worker at a scheduling boundary, `P` pauses all workers, and `q` performs a controlled shutdown. The live-log view must return to the in-place dashboard without interrupting downloads.

Use `termdash`, with `ytaedl` as interaction/layout inspiration.

Target 80x24 minimum without overlapping text. Compact view must keep header, at least four workers, and footer visible.

```text
Manga 42/117 done | Q 69 Run 4 Retry 1 Fail 1 | Pages 3210 done 18 skip 2 fail
Speed 8.2 MiB/s | Avg 6.7 MiB/s | Items 2.4/s | DL 1.8 GiB | Rem est. 3.2 GiB | ETA est. 00:08:12

01 RUN  nhentai  123456 Title...       34/52  118/220 MiB  2.1 MiB/s  00:49
02 SKIP exhentai 98765 Another...       80/80  archive       -          -
03 WAIT nhentai  456789 Third...         0/?   retry 2/4     -          00:12
04 RUN  manga... stable-id Name...      8/31   22/95 MiB    1.4 MiB/s  00:52

Up/Down Select | P Worker | p All | x Controlled quit | r Retry | v Logs | h Header | q Quit
```

Views:

- downloads: worker slots and top statistics;
- queue: pending/retry/failure jobs with filters;
- logs: manager events, selected worker events, or raw backend log;
- run summary: completed and failure-category breakdown.

Hotkeys:

- `Up/Down` and `1-9`: select worker.
- `P`: pause/resume selected worker.
- `p`: pause/resume all workers.
- `x`: controlled quit; finish active jobs, assign no new jobs.
- `r`: retry selected retryable failure.
- `v`: cycle verbose/event/raw log pane.
- `h`: hide/show top summary rows.
- `q`: confirmation, then graceful stop; second forced action kills process trees.

Pause semantics:

- Manager pause stops new assignment immediately.
- On Windows/POSIX, active worker suspension uses tested process-tree helpers modeled after ytaedl.
- If reliable suspension is unavailable, report `drain pause`: active jobs continue but no new jobs start.

## Logging From Day One

Follow ytaedl's per-worker log ownership and record format. Each worker log includes worker ID, PID, attempt ID, backend, source URL, gallery identity, event, and timestamp. Manager dispatch/completion records use the same attempt ID, and the TUI tails these logs without becoming their authoritative writer.

Run layout:

```text
<log-dir>/<run-id>/
├── manager.log
├── events.jsonl
├── summary.json
├── config.resolved.toml
├── inputs.json
├── failures.jsonl
├── workers/
│   ├── worker-01.log
│   └── worker-02.log
└── raw/
    ├── worker-01-gallery-dl.log
    └── worker-02-gallery-dl.log
```

Logging requirements:

- Human-readable manager and worker logs.
- Versioned structured JSONL event schema.
- Run header/footer with command, versions, paths, and final counts.
- Rotating or size-bounded raw logs.
- Atomic final summary write.
- URLs may be anonymized through `-A/--anonymize-logs`.
- Always redact cookies, passwords, authorization headers, browser profiles, and query-string secrets.
- Record backend command/config without secrets.
- Include exception type, semantic category, attempt, worker, URL hash, and retry decision.

## Failure Classification and Retry Policy

Failure counters shown separately:

- bad/invalid URL;
- duplicate input;
- archive skip;
- existing-file skip;
- unsupported site;
- authentication/cookies;
- HTTP/network;
- rate limit/429;
- extractor/site layout change;
- filesystem/path/disk-space;
- archive/database lock;
- backend crash;
- canceled/interrupted;
- unknown/other.

Retry defaults:

- Invalid URL, unsupported, authentication, and filesystem-permission failures: terminal until user action.
- HTTP 5xx, connection reset, timeout, and temporary archive lock: exponential backoff with jitter.
- HTTP 429: site-specific longer backoff and temporary site concurrency reduction.
- Extractor failure: one retry, then fallback backend if configured.
- Existing/archive skips: success-like terminal states, never retried.

## Configuration and Authentication

Use a `mangadl.toml` file for manager settings and optionally merge a user-provided gallery-dl config.

Precedence:

1. CLI options.
2. explicit mangadl config.
3. environment variables for non-secret paths/settings.
4. defaults.

Authentication options:

- cookies file;
- cookies from browser;
- gallery-dl config references;
- site-specific environment references where unavoidable.

Do not reproduce the legacy three-line plaintext auth-file convention as the preferred design. The native nhentai fallback may support it only as an explicitly documented compatibility option.

## Implementation Stages

### Stage 1: Scaffold, contracts, and documentation

- Create module/docs/plan structure.
- Add `pyproject.toml`, package version, and `mangadl` CLI entry point.
- Define dataclasses/enums for jobs, attempts, workers, events, metrics, and failure categories.
- Define backend protocol and semantic worker exit codes.
- Add parser/help tests enforcing short and long forms.
- Add scripts-help registry entry only after CLI is runnable.

Exit criteria: package installs editable; all commands expose help; model/event schema tests pass.

### Stage 2: Input parsing and persistent state

- Implement repeatable input files/direct URLs.
- Normalize/deduplicate with source line attribution.
- Add manager SQLite schema initialization, WAL mode, schema-version compatibility checks, and transaction helpers. Do not implement data migrations in this work.
- Implement run creation, job insertion, leases, attempt IDs, heartbeat expiry, and restart recovery.
- Implement `inspect` and JSON output.

Exit criteria: repeated/crashed scheduling tests never assign one URL twice and recover expired leases.

### Stage 3: gallery-dl single-worker backend

- Implement gallery-dl probing and metadata extraction.
- Implement custom progress/event sink.
- Generate deterministic site-aware output configuration.
- Use user-selected gallery-dl archive.
- Emit stable NDJSON for file/gallery lifecycle.
- Add fake HTTP/extractor fixtures; no live network in default tests.

Exit criteria: fixture gallery downloads to one named folder, archive rerun skips files, events and byte totals are correct.

### Stage 4: Manager concurrency and recovery

- Spawn fixed worker slots.
- Enforce global and per-site limits.
- Apply NDJSON by run/job/attempt ID.
- Implement retries, backoff, fallbacks, heartbeats, process-tree shutdown, and controlled quit.
- Add native nhentai fallback adapter using retained `pshentai` behavior.

Exit criteria: parallel fixture jobs are unique, failed workers recover, stale events are ignored, forced exit leaves resumable state.

### Stage 5: Metrics, logging, and non-interactive status

- Add exact and estimated metric aggregation.
- Implement all run/worker/raw logs and redaction.
- Add active run stats snapshots and `mangadl status`.
- Add final summary JSON and console report.

Exit criteria: metrics tests cover archive skips, retries, active bytes, estimates, and no double counting.

### Stage 6: `termdash` UI and interaction

- Implement downloads, queue, logs, and summary views.
- Add selection, pause/resume, retry, controlled quit, verbose pane, and confirmation flows.
- Test 80x24, 120x30, and narrow Windows terminals.

Exit criteria: stable dimensions, no overlap, worker updates do not resize layout, keyboard actions are covered by tests.

### Stage 7: Additional sites and hardening

- Exercise gallery-dl routes for at least nhentai and two fixture-backed non-nhentai extractors.
- Add site config, auth diagnostics, 429 handling, and per-site caps.
- Add optional backend plugin registration through entry points or a local registry.
- Add marked manual/live smoke tests for user-approved URLs.

Exit criteria: routing is automatic, unsupported URLs fail before worker spawn, and one backend failure can advance to a configured fallback.

### Stage 8: Adoption without migration

- Document commands matching the current gallery-dl workflow.
- Add scripts-help registry/README version tags.
- Run bootstrap drift checks.
- Validate against copied input files and a copied/new test archive first.
- Only after user manual approval, use the production destination/archive.

No legacy deletion, relocation, or migration occurs in this stage.

## Test Strategy

Unit tests:

- URL parsing, canonicalization, comments, malformed input, and stable dedupe.
- Backend scoring/routing/fallback order.
- State transition legality and transactional leases.
- Retry classification/backoff/jitter.
- Attempt-generation stale-event rejection.
- Exact and estimated metrics.
- Path sanitization and deterministic collision handling.
- Secret redaction.
- Every public option has short and long forms.

Integration tests:

- Fake gallery-dl backend and fake worker subprocess emitting NDJSON.
- Local HTTP server serving multi-page fixture galleries.
- Concurrent workers sharing a temporary gallery archive.
- Manager crash/restart with active leases.
- Worker crash, malformed NDJSON, stalled heartbeat, and process-tree cleanup.
- Archive lock contention and retry.
- Controlled quit and resume.

UI tests:

- Worker row/state rendering.
- Header metrics at fixed widths.
- Footer hotkeys always visible.
- Long manga title clipping without overlap.
- Log pane cycling and scrolling.

Manual validation:

- Start with copied URL files and a new test archive/destination.
- Test one worker, then two workers.
- Interrupt during an image and during gallery transition; confirm resume.
- Re-run the same input and verify archive skips/no duplicate folders.
- Test malformed, duplicate, removed, and rate-limited URLs.
- Compare final folders/images to gallery-dl's current direct command.

## Acceptance Criteria

The initial implementation is complete only when:

- `mangadl run` accepts URL files, destination, archive, state DB, and worker count.
- URL routing selects gallery-dl automatically and supports a configured fallback.
- Every manga/gallery gets one deterministic folder containing its images.
- Multiple workers never receive the same canonical URL.
- Restarting after interruption resumes without duplicate scheduling.
- Archive/existing skips are distinguished from bad URLs and failures.
- UI shows manga and page counts, current/average speed, pages per second, downloaded bytes, exact active and estimated remaining bytes, ETA, workers, retries, and categorized failures.
- Manager and every worker have complete human and structured logs.
- Pause/resume, controlled quit, retry, and forced shutdown behave consistently on Windows and POSIX.
- Default tests make no live external requests.
- Focused tests and the full module suite pass.
- README, help registry, version metadata, and handoff docs match behavior.
- No existing downloader code is migrated or deleted without a later explicit request.

## Merge Candidates to Revisit Later

No merges are authorized by this plan. Good later candidates are:

- `pshentai`, `dlnh.py`, and `dlnhv2.py`: consolidate only after `native-nhentai` parity is verified.
- `roundrr.py`, `roundrr_parallel.py`, and old round-robin yt-dlp scripts: consolidate common scheduler/process ideas into a reusable runner only if another module needs them.
- `hentai_organizer.py`, `rename_hentai.py`, and `organize_by_author.py`: potential post-download organization suite, separate from downloading.
- `pscripts/images/dl-mangadex.py` and `dl-mangadex-old.py`: retire only after gallery-dl MangaDex behavior is validated.
- `manga_tools` tag scraping: potential optional metadata enrichment plugin, not part of the download manager core.

Until then, preserve all existing code and treat `mangadl` as additive.
