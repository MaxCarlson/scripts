---
plan_index: 0011
origin: ai
status: implemented
source_file: user_request_20260622_explicit_urlfile_workers_and_locking
---

# Explicit URL-File Workers and Cross-Process Locking

## Objective

Add an opt-in `ytaedl run` mode that uses the existing repeatable
`-p/--priority-files` values as the complete workload:

```text
ytaedl run -i -p path/to/a.txt -p path/to/b.txt
ytaedl run --priority-files-only \
  --priority-files path/to/a.txt \
  --priority-files path/to/b.txt
```

In this mode:

- only the explicitly named URL files are eligible;
- exactly one persistent worker slot is created per unique URL file;
- `-t/--threads` does not determine the worker count;
- no URL-root scan, test-directory fallback, URL ranking, preemption, or
  domain-index scheduling may add other work;
- a worker blocked by another process's URL-file lock stays visible in the
  downloads panel and starts automatically when the lock becomes available;
- multiple `ytaedl run --priority-files-only` processes can concurrently
  process different URL files.

The implemented mode flag is `-i/--priority-files-only`. The originally
proposed `-b` remains reserved by the removed `show-bars` compatibility test.
The existing
`-p/--priority-files` argument remains the only argument used to name files.

## Current Behavior and Constraints

- `-p/--priority-files` currently adds files to a priority pool but does not
  restrict the regular URL-root pool.
- Worker slots are currently created from `-t/--threads`.
- Normal `run` defaults to `-D 2`, initializes the shared domain index, and
  takes a manager-lifetime lock on `archive/domain_index.json.lock`.
- Domain-index scheduling converts an original URL file into temporary
  single-URL files before launching `downloader.py`.
- File-level scheduling prevents duplicate assignments only through the
  manager-local `active` set. That does not protect against another manager.
- `DomainIndexFileLock` already demonstrates nonblocking Windows
  `msvcrt.locking` and POSIX `fcntl.flock`, but it is manager-owned and guards
  one global index rather than individual source URL files.
- Manager shutdown kills child process trees, but uncatchable manager death can
  release a manager-owned lock while an orphan worker is still alive.

These constraints mean the authoritative URL-file lock must be owned by the
worker process that performs the download. Manager-side checks may improve
scheduling, but they cannot be the source of truth.

## Locking Model

### Lock identity and sidecar

Create a small internal module, proposed as `ytaedl/urlfile_lock.py`, containing
the cross-platform lock implementation.

- Canonicalize the source URL-file path with `expanduser().resolve()`.
- Lock a sibling sidecar, not the URL file itself:
  `<url-file-name>.ytaedl.lock`.
- For domain-index temporary files, use `-O/--archive-source-file` as the lock
  identity so the original URL file is protected.
- Do not use lock-file existence as the lock state.
- Keep the sidecar file in place after release. Removing a sidecar can create
  inode/handle races in which two processes lock different files with the same
  path.
- The held kernel lock is authoritative. Any metadata left in an unlocked
  sidecar after a crash is informational only.

### OS primitives

- Windows: open the sidecar and hold a one-byte nonblocking
  `msvcrt.locking(..., LK_NBLCK, 1)` lock.
- POSIX/Termux/WSL2: hold
  `fcntl.flock(..., LOCK_EX | LOCK_NB)` on the open sidecar handle.
- Keep the file handle alive for the complete worker lifetime.
- Release by unlocking and closing the handle in `finally`.
- If the worker exits normally, raises, receives Ctrl+C, is terminated, or is
  hard-killed, the OS closes the process handle and returns the lock.

This avoids stale-lock cleanup, PID-liveness guesses, and timeout-based lock
stealing.

### Metadata

After acquisition, truncate and write diagnostic metadata while the lock is
held:

- worker PID;
- manager PID when supplied;
- acquisition timestamp;
- canonical source URL-file path;
- worker slot;
- command/mode label.

On a failed acquisition, read metadata best-effort for warnings and the TUI.
Malformed or stale metadata must never affect lock decisions.

### Lock API

Provide a focused API with unit-testable behavior:

- `UrlFileLock(source_path, *, worker_slot, manager_pid)`
- `try_acquire() -> LockAttempt`
- `acquire_waiting(stop_requested, poll_seconds, on_wait) -> LockAttempt`
- `release()`
- `probe_urlfile_lock(source_path) -> LockProbe`
- context-manager support

`LockAttempt`/`LockProbe` should distinguish:

- acquired/available;
- held by another process;
- unusable because the sidecar cannot be opened or locked.

An unusable lock is a hard safety failure. The worker must not download the
file without a lock.

## Worker-Side Enforcement

Update `downloader.py` so every invocation of `ytaedl worker` participates in
the lock protocol, including standalone invocations.

1. Resolve the lock identity before reading URLs:
   `archive_source_file` when present, otherwise `urlfile`.
2. Add hidden manager-only arguments with both short and long forms:
   `-H/--wait-for-url-file-lock` and a nonconflicting
   `-N/--manager-pid`-style option selected after checking the complete worker
   parser. If `-N` conflicts, choose another free short form.
3. Standalone workers perform one nonblocking acquisition attempt. If locked,
   print an actionable warning and exit with a dedicated nonzero return code.
4. Exact-file manager workers use waiting mode. While blocked they:
   - emit one `urlfile_lock_wait` NDJSON transition event;
   - periodically check the controlled-quit sentinel;
   - do not read or process any URL;
   - retry the nonblocking OS acquisition at a bounded interval.
5. Emit `urlfile_lock_acquired` immediately after acquisition.
6. Wrap all URL reading, archive checks, and downloading in a `try/finally`
   that releases the lock.
7. Emit `urlfile_lock_released` on normal release where practical; correctness
   must not depend on that event.

The worker owns the authoritative lock so:

- killing only the worker releases it;
- a surviving worker keeps the lock if its manager is hard-killed;
- killing both manager and worker releases it automatically;
- a standalone `ytaedl worker` cannot bypass manager locks.

## Manager Exact-File Mode

### Argument validation

Add `-i/--priority-files-only` to `_add_run_core_args`.

At startup:

- require at least one `-p/--priority-files` value when the mode is enabled;
- canonicalize and stable-deduplicate the paths;
- reject missing paths and non-files with an actionable error before spawning
  any worker;
- do not remove files because they appear in `finished_urls.txt`;
- do not fall back to test URL directories;
- log that `-t/--threads` is overridden when its value differs from the number
  of unique explicit files.

The downloader's archive handling may still skip URLs already recorded as
successfully processed. Exact mode controls file eligibility, not archive
semantics.

### Scheduler isolation

Exact-file mode must bypass:

- `_gather_from_roots` for workload construction and completion checks;
- domain-index creation and `DomainIndexFileLock`;
- URL ranking/rescans and preemption;
- domain-index temporary single-URL assignment;
- normal priority/regular pool reassignment.

This bypass is required because the global domain-index lock would otherwise
prevent concurrent exact-file manager instances before their workers can
coordinate through per-file locks.

### Worker slots

Create one `WorkerState` per unique explicit file and bind the file to that
slot for the complete manager run.

Extend `WorkerState` with explicit lock/display state, for example:

- `requested_urlfile`;
- `is_waiting_urlfile_lock`;
- `urlfile_lock_since`;
- `urlfile_lock_owner`;
- `urlfile_lock_path`;
- `assignment_terminal`.

Each exact slot launches its bound worker once with
`--wait-for-url-file-lock`. It never consumes another file after completion.
The manager exits when all exact slots are terminal. A slot waiting on a lock
is nonterminal and may wait until the lock becomes available or the user
quits.

### Event handling and warnings

Handle the new worker events in `_reader`:

- `urlfile_lock_wait`: set waiting state, capture owner metadata, write one
  manager warning and one worker log transition;
- `urlfile_lock_acquired`: clear waiting state and log acquisition;
- `urlfile_lock_released`: clear lock state without erasing the completed
  assignment label.

Warnings should include the canonical URL file and holder PID when available:

```text
[03] URL file locked by another ytaedl worker (pid 1234):
C:\...\stars\channel.txt; waiting
```

Avoid printing the warning every refresh tick.

### TUI behavior

Add a lock-wait row before the existing domain-wait rendering branch.

The worker row should retain its fixed URL-file name and show a clear state,
for example:

```text
 [03] channel.txt  WAITING: URL FILE LOCK  holder pid 1234  00:01:42
```

Requirements:

- use a distinct yellow status;
- show wait elapsed time;
- show owner PID/details only when metadata is available;
- do not show stale percentage, speed, ETA, or prior URL data;
- preserve the existing compact two-line layout and footer;
- represent every requested file even if all of them are locked.

The TermDash web mirror must receive equivalent worker-name/status values.

## Protection in Normal Manager Mode

The worker-side lock is authoritative for all modes. Add manager-side probes
to avoid wasting normal worker slots:

- file-level assignment filters candidates whose source lock is held;
- domain-index assignment excludes source file IDs whose locks are held before
  calling `pick_url`;
- if a race occurs after the probe, the worker's nonblocking lock failure is
  handled as a safe requeue, never as a download attempt;
- manager-local `active` tracking remains as an optimization, not a
  concurrency guarantee.

Normal domain-index managers may still be mutually exclusive because they
share mutable `domain_index.json`; this plan does not make that shared data
structure multi-writer. The guaranteed concurrent-manager path is the new
exact-file mode, which deliberately bypasses the domain index.

## Lifecycle and Release Paths

Audit every worker lifecycle path so assignment state and lock state agree:

- normal worker completion;
- nonzero worker exit;
- time-limit kill;
- URL preemption;
- controlled quit;
- immediate quit/Ctrl+C;
- pause followed by quit;
- throttle/unthrottle worker restart;
- `Popen` failure;
- reader-thread failure;
- manager exception;
- standalone worker Ctrl+C;
- direct worker termination;
- direct manager hard kill with a surviving worker;
- hard kill of both processes.

Important invariants:

- manager code never manually deletes a lock sidecar;
- the worker releases in `finally`, but kernel close-on-process-exit is the
  final guarantee;
- throttle/unthrottle restarts must not create a download gap in which an
  unlocked replacement worker starts processing. Prefer avoiding process
  restart for lock-waiting workers; for active workers, let the replacement
  reacquire before processing and treat failure as a safe stop/requeue;
- manager status is cleared only after the old worker process is confirmed
  exited or its lock-release event is observed;
- no exception path may continue downloading after lock acquisition fails.

## Tests

Add focused tests under `modules/ytaedl/tests/`, using `tmp_path` and the
module-local pytest temp root.

### Lock unit tests

- first process/handle acquires a URL-file lock;
- second acquisition is nonblocking and reports held;
- release makes the lock immediately acquirable;
- closing the owning handle without explicit `release()` returns the lock;
- a spawned process that acquires then exits normally returns the lock;
- a spawned process that acquires then is forcibly terminated returns the
  lock;
- sidecar metadata identifies the current holder;
- stale/malformed metadata does not make an unlocked file appear locked;
- source paths that resolve to the same file map to the same sidecar;
- lock-open/permission failure blocks downloading safely.

Use real subprocesses for the process-death tests; mocking `msvcrt`/`fcntl`
cannot prove kernel release behavior.

### Parser and exact-mode tests

- `-i` and `--priority-files-only` parse identically;
- exact mode without `-p` exits with code 2 and actionable help;
- repeated `-p` values are stable-deduplicated after resolution;
- invalid explicit files fail before any worker launch;
- worker count equals unique explicit file count, regardless of `-t`;
- exact mode does not scan roots or use test-directory fallback;
- exact mode bypasses domain-index construction and its global lock;
- a file in `finished_urls.txt` still receives its exact worker slot.

### Orchestration tests

- two distinct exact files launch concurrently;
- two exact managers targeting the same file result in one downloader and one
  visible lock waiter;
- the waiter starts after the first worker exits;
- one exact manager targeting a mix of free and locked files starts free files
  immediately and shows blocked rows for locked files;
- duplicate explicit path spellings never create two slots;
- a normal manager skips a file held by an exact manager and can choose another
  file;
- domain-index scheduling does not pick a URL from a locked source file;
- standalone `ytaedl worker` refuses a held source file;
- a domain-index temp worker locks its original `-O/--archive-source-file`,
  not the temporary file.

### Status and cleanup tests

- lock-wait events clear stale progress and set the correct worker state;
- lock-acquired events clear the waiting label;
- TUI text includes `WAITING: URL FILE LOCK` and the requested filename;
- warnings are transition-based and not repeated each refresh;
- controlled quit terminates lock waiters;
- manager cleanup terminates workers and leaves every lock acquirable;
- direct worker kill returns the lock even if no release event is emitted.

### Regression verification

Run:

```text
C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/ytaedl/tests/test_manager.py -v
C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/ytaedl/tests/test_downloader.py -v
C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/ytaedl/tests/test_cli_dispatch.py -v
C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/ytaedl/tests -v
C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m py_compile modules/ytaedl/ytaedl/manager.py modules/ytaedl/ytaedl/downloader.py modules/ytaedl/ytaedl/urlfile_lock.py
ruff check modules/ytaedl/ytaedl/manager.py modules/ytaedl/ytaedl/downloader.py modules/ytaedl/ytaedl/urlfile_lock.py modules/ytaedl/tests
```

Also perform a manual two-console smoke test with two small URL files:

1. Start exact manager A on files A and B.
2. Start exact manager B on files B and C.
3. Confirm A and C download concurrently while exactly one B worker waits.
4. Stop the B owner with Ctrl+C and confirm the waiter acquires B.
5. Repeat by forcibly terminating the owning worker process.
6. Force-kill an owning manager while leaving its worker alive and confirm the
   second manager remains blocked until that worker exits.

## Documentation and Versioning

Update:

- `modules/ytaedl/README.md` with exact-mode examples, one-worker-per-file
  behavior, waiting semantics, and the distinction from normal domain-index
  mode;
- `ytaedl run --help` text for `-i/--priority-files-only`;
- package version history.

This is backward-compatible user-facing functionality, so bump `ytaedl` from
`2.10.1` to `2.11.0` in both:

- `modules/ytaedl/pyproject.toml`;
- `modules/ytaedl/ytaedl/__init__.py`.

No entry point changes are required, so this is not a major-version change.

## Implementation Order

1. Add and test the reusable worker-owned `UrlFileLock`.
2. Enforce locking in `downloader.py`, including standalone and waiting modes.
3. Add exact-file argument validation and workload resolution in `manager.py`.
4. Bind one worker slot to each exact file and bypass domain-index scheduling.
5. Add lock events, warning transitions, TUI state, and TermDash updates.
6. Add normal-mode lock probes and race-safe requeue handling.
7. Audit all termination/restart paths.
8. Add parser, subprocess, orchestration, UI, and regression tests.
9. Update README/help and bump both version markers to `2.11.0`.
10. Run targeted tests, the full module suite, compile checks, lint, and the
    two-console process-death smoke test.

## Acceptance Criteria

- Exact mode starts no file other than the unique paths supplied through
  `-p/--priority-files`.
- Exact mode presents exactly one worker slot per supplied URL file.
- Different URL files can run concurrently across multiple manager instances.
- At most one live worker can process a given canonical source URL file.
- Locked exact-file workers remain visible and automatically start after
  release.
- Normal managers do not download from source files held by exact workers.
- Standalone workers cannot bypass locks.
- Ctrl+C, normal exit, worker kill, manager kill, and combined process death
  cannot leave an unavailable stale lock.
- All new and existing ytaedl tests pass, and runtime lock release is verified
  with real subprocesses.

## Follow-up: Centralized Lock Storage

Implemented after initial delivery:

- lock sidecars live under `<archive>/locks/`;
- filenames use `<source-basename>.<canonical-path-hash>.ytaedl.lock`;
- canonical full paths provide collision-free identities for same-named URL
  files in different directories;
- pre-`2.12.0` sibling sidecars are legacy artifacts and are no longer used.
