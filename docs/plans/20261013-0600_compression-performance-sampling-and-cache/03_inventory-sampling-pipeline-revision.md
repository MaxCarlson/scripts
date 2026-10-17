# Inventory, sampling, and compression pipeline implementation plan — revised

> **For agentic workers:** Use `superpowers:executing-plans` inline with test-first checkpoints and one fresh whole-branch review at completion. User authorized implementation2026-10-17 after adding the CLI simplification step below. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make inventory progress understandable, reduce analysis overhead, persist reusable sampling guidance, and accelerate expensive work without weakening source validation, statistical inference, cancellation, or memory limits.

**Architecture:** One bounded filesystem/header pipeline and coordinator-owned inventory connection; stable gallery work identities; versioned inventory-derived sampling profiles; existing memory-admitted encoder workers and durable trial cache. Optimize redundant work before introducing additional parallelism.

**Tech stack:** Existing Python/Pillow/NumPy/SQLite/cross_platform/termdash dependencies. Development runtime Python3.12; compresser currently declares Python>=3.10, so do not introduce 3.14-only executor APIs. No new mandatory dependencies in this proposal.

**Spec:** Reviewed replacement for the user's attached “Inventory UI, Optimal Sampling Distribution, and Multi-Threaded Pipeline Implementation Plan,” attachment `5d2e52ad-6633-4590-9e8c-cfb521fac28c/Pasted text.txt`, the clarification excluding the earlier pilot/confirmation Task6, and the2026-10-17 instruction to integrate argument-audit attachment `98f03690-037b-4e16-9f4b-078dd5f311cd/Pasted text.txt` then implement. Attachments are proposals, not independent authority; reviewed decisions here govern. Existing safety contracts in [02_review-repairs.md](02_review-repairs.md) remain authoritative; its unimplemented pilot/confirmation Task6 is explicitly outside this work.

## Baseline and review findings

Reviewed branch: `compression-inventory-and-analysis-20261016`, HEAD `876115e`, compresser0.26.4/MangaDL1.52.4. Parent working tree clean before this documentation change; inaccessible `pscripts` submodule excluded.

1. **“True ETA” is not possible from unknown folder contents.** The proposed formula mixes started/completed folders and can count the active folder twice. Nested chapter directories are not independent manga galleries. The UI must say *estimated* or *unknown*, and count completed work only after completion.
2. **Inventory variation is not compression-savings variation.** Neyman allocation targets the standard deviation of the measured outcome, not automatically that of input file sizes. Equal-size pages can have very different compressibility. A metadata profile is a useful planning heuristic, not an accuracy guarantee or a proven minimum sample size.
3. **New within-gallery strata invalidate the current estimator if simply bolted on.** `GallerySample.estimate()` currently assumes uniform selection within each gallery. Keep that selection design initially; format/size coverage diagnostics already exist. Explicit nested strata require new inclusion probabilities, estimator, variance, and tests together.
4. **Do not silently replace existing `-s`/`-P` allocation.** Saved profiles must be opt-in and versioned, otherwise the same command/seed can change meaning after an inventory refresh, breaking reproducibility and expanding-sample reuse.
5. **`os.walk()` already uses `scandir()`.** The opportunity is retaining directory-entry information and eliminating extra path queries, not the function-name substitution itself. Do not eliminate before/after freshness checks in the name of “one stat per file.”
6. **One giant transaction/full-database preload is not the right default.** Both increase resource/lock duration; preloading all roots and historical records is unbounded. Existing completed-selection publication is already atomic. Reuse one connection, scope queries, bound batches, and preserve that publication boundary.
7. **A thread pool around locked cache calls can serialize anyway.** `AnalysisCache.get()` uses an RLock and repeatedly resolves/stats paths; `_probe_cached()` runs over the whole selected set before dispatch. Batch identities/lookups and overlap bounded preparation with encoding instead of merely moving the same contention into more threads.
8. **Available RAM does not justify a larger silent default.** Reservations estimate memory, not enforce OS RSS. Never fall back from unknown available RAM to total RAM. Retain the512MiB default; offer an explicit auto policy only with guards and measured validation.
9. **Preview manifest locking alone is insufficient.** Shared report mutation and serialization must have one owner; cancellation must stop queued work and wait for active owners before a final manifest. Source copies, decoded pixels, candidate bytes and retained best AUTO output all consume memory.
10. **The attachment's tests often prove metadata, not the feature.** A `threads_requested` field does not prove concurrent execution; one scan scope does not prove one connection/transaction; avoiding one ETA string does not establish a meaningful estimate. Add behavioral, concurrency, safety and statistical tests.

### Evidence and limits

Generated-only review probe: eight galleries,32 small PNGs each,256 images, live UI disabled. Cold run:2,431 `Path.stat()` calls,10 SQLite connections,265 SELECTs,10 COMMITs,256 headers inspected. Warm run:2,175 stat calls,10 connections,265 SELECTs,10 COMMITs,256 reused headers. Instrumented wall times1.155s/0.179s are observations, **not production performance predictions**. Counting includes supporting path operations and the counters add overhead.

The existing STATUS records an earlier narrow source-image experiment: WebP effort6 spent45.344s encoding out of45.625s wall time; effort0 encoded in1.500s but produced a larger candidate. That historical result supports investigating encoder effort and memory admission, not assuming every new run has the same bottleneck. Repeat only with authorized fixtures or a separately approved bounded read-only source sample.

Documentation freshness (0 fresh,100 stale): compresser20/MangaDL20, because README and API hotfix shipped together but older status paragraphs remain historical. Termdash30: LiveBlock is documented, but its handoff still names the older branch. Repo plans handoff needs a current pointer; do not treat historical “complete” paragraphs as acceptance of the deferred work.

## Global constraints

- User authorized local merge of the verified prior branch into main, creation of a new branch and implementation. Main fast-forwarded to0672a42; work now runs in the existing checkout on `compression-pipeline-and-cli-20261017`. Prior standing authority covers verified feature-branch commits/pushes per usable checkpoint. Do not push main or run production writes/large benchmarks. Recheck dirty state before changes.
- **The earlier repair plan's Task6 (pilot/confirmation CLI) is excluded, not a prerequisite.** Sampling guidance must be computed from existing inventory metadata without an extra compression pilot, confirmation run, precision-target search, or outcome-adaptive allocation. These P-prefixed checkpoints do not authorize that earlier Task6; P6 here concerns memory policy only.
- Preserve source ownership, nested chapter grouping, cover/control/archive/partial/link exclusions, read/write coordination, selected-source validation, corruption/failure visibility and scratch ownership/cleanup guarantees.
- Existing CLI semantics remain through P7 except the explicit P4 `-s auto`/P6 `-B auto` additions. P8 is the documented major-version canonical CLI migration; new flags require short/long forms. Future flag syntax in this plan is not implemented until its checkpoint.
- Keep inventory, trial cache, preview output and scratch outside the source tree. `-D files` stays extension/size-only and cannot become a trusted header snapshot or compression input.
- Use one concurrency budget per phase; never create nested gallery × file × candidate thread pools. Bound pending futures/results to at most `2 * effective_workers` unless a tested smaller cap is needed.
- Persistent completed trial results remain reusable during a running analysis. Do not turn immediate durable `AnalysisCache.set()` into deferred end-of-run persistence.
- Keep explicit `-B` limits,512MiB per-image estimate limit and40-million-pixel rejection unchanged; do not treat higher aggregate RAM as permission to admit oversized images.
- Cancellation is cooperative. Native encoder/I/O calls may need to return; show active work, stop submissions promptly, drain owners, and then release locks/finalize manifests. No hard-kill guarantee.
- Generated test directories stay under owning module's ignored `.pytest_tmp_root`; do not track artifacts or recursively clean other tasks' fixtures.
- Update module versions, dependencies, exposed versions, help registry, READMEs and handoffs at each authorized usable checkpoint. Changed features/dependency metadata use appropriate minor versions, not a patch by default.

## Review focus

- Unknown folder populations, empty galleries, nested chapters and out-of-order worker completion must never imply100% before work is done.
- Changing files/ancestors, links/junctions and stale cache hints must fail closed; optimization cannot turn a snapshot into authority over unverified current files.
- Tiny/insufficient budgets, singleton galleries and constant-size/different-savings populations must not produce false precision claims or omit galleries silently.
- Cancellation, read errors, full disks and mid-publication failures must preserve the previous completed inventory and produce parseable preview state.
- Cold/warm runs, explicit/implicit memory policies and AUTO candidate reuse must retain identical verified results and explain where speed came from.

## Execution order

P0 measurement baseline → P1 progress correctness → P2 inventory pipeline → P3 trusted/cache preparation → P4 metadata sampling profiles → P5 expensive-work reuse → P6 explicit memory auto-policy → P7 parallel previews → P8 canonical CLI simplification.

P4 does not add within-gallery strata or implement the excluded pilot CLI. P5 can move ahead of P4 if P0 shows encoding/repeated similarity work dominates. Process pools, compiled metric changes and cross-stage source-decode reuse are experiment-gated extensions, not assumed improvements.

## Task 1: P0 — establish phase measurements and reproducible comparisons

**Files:** `modules/compresser/compresser/timing.py`, `inventory.py`, `scanner.py`, `engine.py`; new `modules/compresser/tests/pipeline_diagnostics_test.py`; generated-fixture benchmark utility under `modules/compresser/tests/`.

**Interfaces:** Add JSON-safe diagnostics with exclusive coordinator/worker seconds for enumeration, metadata lookup, header read, validation, cache preparation, encode, verification, similarity, publication and waits. Counts include scanned/reused/inspected/error images, inventory connections/queries/commits, queued/active work and peak reservations. Existing phase fields stay compatible; do not conflate summed worker seconds with wall time.

- [ ] RED: deterministic instrumented operations report the correct phase/counter; warm inventory opens no unchanged image content; cache hits report lookup work, not historical encoder throughput.
- [ ] GREEN: extend existing timing boundaries rather than adding a second competing profiler; record environment, settings, workers, memory policy and cold/warm state.
- [ ] Benchmark generated small-image many-gallery, few large-image, mixed-format/nested and cached cases with worker limits1/2/4/8. Record median of3 repetitions, wall/CPU, peak RSS where available, failures and result equality. Do not claim OS page cache is cold merely because trial cache is empty.
- [ ] Validate behavior tests without timing thresholds in CI. Record the bottleneck and selected implementation before P2/P3/P5; a change that adds concurrency without repeatable benefit is revised or dropped.

## Task 2: P1 — correct two-level inventory progress and estimated ETA

**Files:** `inventory_ui.py`, `scanner.py`, `file_inventory.py`, `modules/mangadl/mangadl/compress.py`; tests `inventory_summary_test.py`, `inventory_test.py`, MangaDL `compress_test.py`.

**Interfaces:** Keep `InventoryProgress` compatibility, add `start_gallery(key, total_files=None)`, `finish_gallery(key, status="complete")`, and gallery-keyed `advance_file(..., gallery_key=None)` events. `set_folder_total()` means known candidate gallery work units, not every nested directory. Add immutable rendering snapshots protected by a short lock; renderer never reads a mutating worker structure.

- [ ] RED: explicit completion of43/1,107 galleries renders3.9%; starting44 does not increment completion. One known gallery with1/2 files renders50%; nested chapter parents do not reset it. Empty galleries finish once; completed-with-errors is not called fully verified.
- [ ] RED: inject a fake clock. At43 completions after24s under constant gallery throughput, fallback remaining ETA is approximately594s, not0. Early/no-progress, growing/unknown totals and zero throughput show unknown/estimated status rather than fabricated precision. Known completed totals alone show done/zero.
- [ ] GREEN: render active gallery + current files bar + overall completed-gallery bar, plus counts/bytes/rate/elapsed/estimated ETA. With parallel workers, keep one stable active gallery until it finishes and show how many others are active; store counters for every active gallery independently.
- [ ] Use smoothed completed-work throughput over15s once there is enough history; folder-duration fallback must be labeled approximate for unequal galleries. Do not add an active remainder to a remaining count that already includes that active gallery. Discovery with unknown totals is indeterminate; no expensive second full traversal solely for an exact percentage.
- [ ] Test actual LiveBlock/ProgressBar contracts with TTY streams, redraw, narrow/CJK paths, no-UI, redirected JSON and double close. Do not hold state locks while joining the timer thread. Preserve the0.26.4 API regression tests and run a real Windows terminal smoke test before claiming visual acceptance.

## Task 3: P2 — reduce redundant I/O and add bounded header concurrency

**Files:** `inventory.py`, `scanner.py`, `file_inventory.py`, both compression CLI adapters; new `modules/compresser/compresser/inventory_pipeline.py` and `tests/inventory_parallel_test.py`.

**Interfaces:** `scan_directory(..., threads: int = 4)` and `scan_file_inventory(..., threads: int = 4)`; shared `InventoryStore.run() -> ContextManager[InventoryStore]` owns one inventory connection across discovery/gallery scans, while existing `scan(root, recursive)` sessions reuse that connection when in a run. Internal immutable `FileObservation` carries lexical path, gallery key, no-follow stat/identity and inspection outcome. Do not pass a SQLite connection, DirEntry iterator or PIL object across worker ownership boundaries.

- [ ] RED: serial/parallel inventories match images, bytes, ownership, exclusions and failures; one run reuses one inventory connection. A barrier-controlled header reader proves simultaneous admitted inspections, not merely a requested-workers field. Queue high-water mark stays bounded and a slow first file does not stall completed-result collection.
- [ ] GREEN: enumerate each relevant directory once, retaining `scandir` information instead of re-querying Path helpers for classification. Coordinator performs chunked, selection-scoped lookups of up to256 keys, submits only changed headers, and collects completed results. Use one shared executor, no nested per-gallery pools. File-only mode skips header workers; parallel stat batches are used only if P0 shows a gain.
- [ ] Coordinator alone updates inventory SQL, counters and report order. Flush bounded header-cache batches of up to256 changes, and reuse the connection rather than holding `BEGIN IMMEDIATE` over the entire filesystem scan. Preserve the previous completed `inventory_selections` record until final successful publication; header-cache reuse and completed-population publication are distinct guarantees.
- [ ] Freshness: no-follow observation before header read, then compare current identity/size/mtime/ctime before accepting changed headers. Retain source-change checks; DirEntry metadata is a short-lived observation, not a permanent truth. Noncooperating writers can still race; fail closed on detected changes rather than promise a filesystem transaction.
- [ ] Prune missing headers only in successfully enumerated scopes, never on cancelled/failed/unvisited or filtered-out scopes. Publish completed selection and matching derived profile atomically after all required scopes finish. Existing databases migrate additively or require explicit refresh, never silent reuse under incompatible policy.
- [ ] Failure tests: deleted/replaced/growing file, permission error, traversal failure, links/junctions, interrupted batch, DB lock/full disk, old completed snapshot still loadable after interruption. Corrupt images remain reportable exclusions, not pipeline success silently dropping their errors.
- [ ] Compare P0 cold/warm fixtures before selecting default concurrency. HDD random-read regressions warrant lower effective concurrency with a visible reason; `-t` is an upper bound, not a100% CPU promise.

## Task 4: P3 — optimize trusted-source validation and cache preparation

**Files:** `snapshots.py`, `cache.py`, `engine.py`, adapters; new `tests/trust_and_probe_perf_test.py`, existing cache/ownership tests.

**Interfaces:** `validate_selected(images: list[ImageMetadata], *, threads: int = 4) -> None` keeps selected-only validation; operation-scoped validated identities contain size,mtime,ctime and filesystem identity where available. Add bounded `AnalysisCache.get_many(requests: Sequence[tuple[ImageMetadata, CompressionStrategy, FileObservation]]) -> list[ImageResult | None]` using the same effective/legacy keys, runtime identity, miss causes, LRU and counters as scalar `get()`; each request carries a fresh observation, not an unchecked `(size,mtime)` hint. The returned list preserves request order, independently of concurrent filesystem completion order.

- [ ] RED: repeated deep ancestors are not revalidated once per file; changed images, ancestor replacement/link insertion between validation calls, and changed sources before a cache hit all remain rejected. No ancestor verification is retained across comparison stages/runs. Budgeted concurrent stat calls are actually exercised.
- [ ] GREEN: validate unique ancestors per call, capture their identity, check for changes at batch boundaries, and revalidate selected source identities at the engine boundary. Do not claim this prevents adversarial TOCTOU path swaps; no-follow/open-handle techniques are a separate platform-specific enhancement if stronger protection is required.
- [ ] RED: scalar/batch lookups agree for effective and legacy keys, refresh/off policy, source/settings/runtime invalidation, eviction and malformed rows. Cross-thread writes remain durable and diagnostic memory bounded.
- [ ] GREEN: prepare small bounded batches and overlap preparation with admitted encodes instead of probing every selected image before the first dispatch. Keep SQL under the existing cache owner/lock; chunk reads avoid SQLite parameter limits. If stat work benefits from threads, parallelize only that work outside the DB lock. Cache hits bypass encoder/scratch memory admission but never source validation.
- [ ] Test cancellation before/between probes, no duplicate lookups for an uncached dispatched image, and startup latency until first encode under a delayed later lookup. Repeat P0 warm-hit and cold-miss cases; use a batch query only if it improves measured work.

## Task 5: P4 — persist honest inventory-derived sampling profiles

**Files:** new `compresser/distribution.py`; `inventory.py`, `snapshots.py`, `sampling.py`, both adapters, inventory/report UI; `tests/distribution_test.py`, `sampling_test.py`, MangaDL integration tests.

**Interfaces:** `SamplingProfile` (not `OptimalDistribution`) records schema/policy revision, root/filter/scanner identity, population fingerprint, inventory depth/completion time, per-gallery count/bytes/size variance/format counts/dimension diagnostics, proxy weights and heuristic limitations. Store it in `inventory_sampling_profiles` for the matching completed selection; no compression encoders run during inventory creation.

- [ ] RED: same counts/total bytes but higher input-size variance can receive a higher *proxy* weight; equal-sized populations with deliberately different compression savings demonstrate that metadata alone cannot certify accuracy. File-only inventories label format/dimensions unknown and cannot supply a trusted compression selection.
- [ ] GREEN: derive a transparent initial proxy `w_g = N_g * max(sd(input_bytes_g), 0.15 * mean(input_bytes_g), 1)`; label0.15 a versioned heuristic floor, not a measured savings standard deviation. Store format/tallness as diagnostics, not arbitrary additive Neyman multipliers. Compare against existing balanced allocation in P0-style simulations before making efficiency claims.
- [ ] Extend existing `-s/--sample` with explicit `auto`, which uses this profile and a labeled starter budget `min(N, max(sum(min(2,N_g)), ceil(0.01*N)))`; numeric `-s` and `-P` remain unchanged until P8. This is **not a recommended statistical minimum**. Do not add a temporary `-S` flag or sampling-profile-policy switch only to remove it later. `-I` alone never enables sampling.
- [ ] Reserve positive gallery coverage; where budget permits reserve two for variance, cap by gallery population, then distribute remaining seats by deterministic weighted divisor allocation with canonical tie-breaking. Within every gallery retain the existing seeded uniform random priority permutation. Persist actual per-budget quotas/seed/selected identities/revision; do not confuse a weight profile with an executable measured plan. Census default stays unchanged without explicit sampling flags.
- [ ] RED: exact budgets, singleton/census/empty selections, below-gallery-count `-s` failure, percent coverage inflation disclosed, `-s auto` without profile requires completed header refresh or a clear error in trust mode. Bad/stale/incompatible roots, population IDs, owners/filters or policy reject profile reuse. No fallback that quietly changes design. Refresh publishes matching selection/profile together.
- [ ] RED: growing a budget with unchanged population/profile/revision/seed retains earlier samples; serial/parallel inventory order cannot change profiles or selections. Use repeated-seed finite populations with known savings totals to test design-weighted estimates/bias/interval behavior; singleton/skewed/failed outcomes preserve uncertainty caveats.
- [ ] Summary names: `metadata_proxy` or `balanced`; print coverage/variance floors and starter size separately from achievable precision. Estimates continue to use the existing gallery expansion weights and caveated finite-population uncertainty. Comparisons use one shared inventory-derived sample for every strategy; compression outcomes do not alter its selection. **No measured/adaptive allocation, pilot/confirmation workflow, or extra sampling-control subsystem is required or planned.** This is practical inventory-informed coverage, not a promise of optimality or a certified minimum for a requested error margin.

## Task 6: P5 — reuse expensive verified encoder work before adding CPU pools

**Files:** `engine.py`, `cache.py`, relevant `compresser/codecs/` backend only if needed, `perceptual.py` only if measurement justifies it; new `tests/auto_candidate_cache_test.py`, existing effective-key/phase tests.

**Interfaces:** Analysis AUTO publishes successful measured per-format `ImageResult` records using the same single-format strategy construction as `_cached_auto()`. Preserve source/runtime/policy fingerprints and PNG-lossless normalization. Preview/publication continues to require actual verified encoded bytes, never size-only trial records.

- [ ] RED: AUTO-first then matching WebP/PNG/JPEG analysis avoids duplicate encodes; reverse stage order gives equivalent retained sizes/formats/SSIM. Test larger candidates, unavailable JPEG optimizer, metadata verification failure, partial AUTO success and source changes before cache publication. Unsupported/failed candidates are not fabricated as successful results.
- [ ] GREEN: publish each fully verified candidate during read-only AUTO evaluation with real candidate size and the same retain-original policy as single-format analysis. Keep candidate timing separate from whole AUTO timing; no duplicated charging. A valid candidate may be cached even if another candidate later fails, but final AUTO success still requires valid evidence.
- [ ] Benchmark effort0/2/6 without changing defaults or comparing savings as if settings were equal. Explain speed-versus-ratio differences in reports. Reuse source-side similarity preparation across quality trials only if P0 shows similarity dominates; cache lifetime is one admitted source, counts against its memory reservation, and keys include metric/options.
- [ ] If investigating `_filter2d` row/column Python-call overhead, compare a compiled separable implementation against current numeric/detail/color tests and RSS before proposing a dependency. A changed metric needs a revision/cache invalidation; never accelerate by dropping detail patches or lowering the requested SSIM threshold.
- [ ] No default ProcessPoolExecutor: first compare native threads with measured GIL-bound time and Windows spawn/serialization/RSS costs. Do not transfer decoded PIL/NumPy buffers between processes or create nested candidate pools as an unmeasured optimization.

## Task 7: P6 — optional available-memory scheduling policy, not a silent increase

**Files:** shared argument validation in `sampling.py`, both CLI parsers/adapters, `engine.py`, `scheduler.py`; new `tests/memory_policy_test.py`.

**Interfaces:** Extend existing `-B/--memory-budget-mib` to accept `auto` in addition to64..4096. Omitted remains512. Resolve auto once at run start: `floor(0.20 * available_bytes / MiB)`, capped4096; if below64 or telemetry unavailable, fail with a clear explicit-`-B` suggestion. Use a cross-platform available-memory provider; introduce any new dependency only as a separately documented/install-tested choice.

- [ ] RED: default512 unchanged; explicit value honored; low/unavailable telemetry never falls back to total RAM or exceeds the calculated allowance. Include malformed/nonfinite input and near-boundary tests. Report requested policy, available measurement/time, resolved budget, active workers and memory wait reason.
- [ ] GREEN: feed existing per-job MemoryScheduler, including bounded head bypass, not a second global-largest-image worker cap. Do not reject small jobs because one large job exists. Admission covers source pixels, verification/metric workspace and retained candidate bytes; measure RSS against the conservative estimate in representative generated cases before increasing any default limit.
- [ ] Pressure after start stops new admission rather than terminating owners; show pressure/wait state and allow cancellation. Reservations are not an OS guarantee or a cross-process global budget. Test pressure/cancellation with fake telemetry and worker barriers; preserve per-image and pixel caps.

## Task 8: P7 — parallel previews with one manifest owner

**Files:** `preview.py`, `scheduler.py`, `cancellation.py`; `tests/preview_test.py`, MangaDL integration tests.

**Interfaces:** Honor existing `-t` and resolved `-B` with one admitted job per source; variants for a source remain serial, decoded source reused locally. Coordinator preassigns `0001...` folders/result slots in source selection order and is the only report mutator/manifest writer. Workers return immutable progress/completion events via a bounded queue; actual candidate output paths are exclusively owned and atomically published.

- [ ] RED: barriers prove more than one source runs when the memory budget permits; peak reservations/active counts remain bounded. Out-of-order completion still produces ordered source entries and ordered lossless/quality variants. One-image or small-budget runs stay serial without failure.
- [ ] GREEN: reuse admission/cancellation primitives without using transactional source-replacement paths. Count originals/candidates/verification memory and limited queued events; do not share a decoded PIL object across workers. Keep source copies/checksums/fingerprint validation and all preview failure diagnostics.
- [ ] RED: every observed published manifest is parseable; source/variant states move pending→running→complete/failed/cancelled. Mark never-submitted work cancelled on Ctrl+C, drain active owners before final publication/lock release, retain diagnosable partial output, never announce complete prematurely.
- [ ] Failure tests: disk-full/short write, partial candidate, source change, manifest replacement error, permission error and cancellation while workers are encoding. Final publication failure is explicit, not masked by shutdown. Existing artifact names are never overwritten and unrelated files never removed.
- [ ] Benchmark default3-source previews and a larger fixture. Report requested/effective/active concurrency and why limited; preserve seeded source selection. Size-only analysis cache cannot bypass preview encoding.

## Task 9: P8 — simplify and normalize both compression CLIs

**Files:** new `modules/compresser/compresser/arguments.py`; shared argument owners `sampling.py`/`preview.py`, standalone `cli.py`, MangaDL `cli_core.py`/`compress.py`; new `tests/arguments_test.py`, both CLI integration suites/READMEs/help registry. Do not change unrelated MangaDL commands.

**Interfaces:** one shared `normalize_compression_arguments(namespace) -> CompressionOptions` value object drives both adapters. Define explicit operation, sampling specification, comparison scope, quality list, inventory depth, recovery token and resolved resource paths. Parse once, validate conflicting/ignored arguments before ownership acquisition or output creation, then use normalized values throughout. Preserve library APIs separately from CLI migration.

### Reviewed argument decisions

| Current surface | Canonical surface after P8 | Decision/compatibility |
| --- | --- | --- |
| `-o/--output-dir` standalone | removed | Dead placeholder always rejects; do not repurpose it silently. Preview output remains `-O`. |
| `-s N`, `-P p`, proposed `-S` | `-s/--sample N\|p%\|auto` | Explicit value required, no bare `-s` or implicit sampling from `-I`. `auto` is metadata-only starter sampling. |
| `-q`, `-Q/--qualities/--preview-qualities` | `-q/--quality VALUE [VALUE ...]` | Accept1..100 or decimal fractions, deduplicate in input order. Multiple values only compare/preview. Omitted defaults:80 single/compare,90/80 preview. |
| `-c`, `-b` | `-c/--compare [both\|lossless\|lossy\|perceptual]` | Bare `-c` means both; explicit `-m` narrows bare `-c`. Conflicting explicit scope/mode is an error. Comparison always read-only. |
| `-l`, `-D` | `-l/--inventory-only [headers\|files]` | Bare `-l` means headers; file-only remains unverified and incompatible with compression/trust. |
| `-R`, `-C` | `-R/--recover [TOKEN]` | Bare recovery previews. Apply still requires `-w` plus the exact current token; folding syntax does not weaken stale-plan checks. |
| `-I`, `-K` | retain `-I`; advanced `-K` override | Default trial path already derives beside inventory. Keep separate non-evicting inventory and bounded trial-result DBs; no same-file migration/WAL assumptions. Ordinary commands need only `-I`. |
| `-L/--allow-lossy`, `-F/--allow-larger` | retain in safety group | They are intentional independent destructive-policy interlocks, not cosmetic redundancy. Never infer library `allow_lossy` from mode alone. |
| `-A`, `-f`, `-e` | retain, group backend/encoding | Different controls (backend/format/effort). Reject incompatible explicit combinations; do not silently ignore them. |
| `-U`, `-k`, `-B`, `-t`, `-X` | retain, group persistence/performance | Population freshness, trial reuse, RAM, worker slots and scratch are distinct policies. No additional profile-policy switch. |
| `-N`, `-J`, `-v` | retain, group output | No-UI, machine-readable output and verbose error tracebacks are distinct. Normal JSON stays parseable. |

- [ ] RED: standalone and MangaDL normalize equivalent commands identically except target/URL selection; exact syntax cases `-s 200`, `-s 2%`, `-s auto`, `-q 0.9 80`, `-l files`, bare `-c`, `-c lossless`, bare `-R` and `-R TOKEN -w`. Zero/NaN/negative/ambiguous percentages, bare sample and contradictory aliases fail before filesystem mutations.
- [ ] GREEN: retain legacy `-P`, `-Q`, `-b`, `-D`, `-C` as hidden compatibility aliases for one major release with stderr deprecation notices and deterministic conflict errors; remove them from normal help. Legacy `-c` default changes are explicitly documented, not described as unchanged. Keep the canonical short/long forms grouped by operation, sampling/quality, storage/performance and safety/output.
- [ ] P8 canonical explicit sample budgets use versioned metadata-profile allocation, with the existing gallery-uniform random draws/estimator. Hidden legacy `-P` preserves its old balanced design during the transition; explicit output names the chosen design revision so cached selections are never silently mistaken for equivalent ones. Missing profile in trust mode fails with refresh guidance; default refresh can create it. No pilot/confirmation workflow.
- [ ] RED: no sampling when only `-I` supplied; defaults remain lossless analysis with no writes; `-m lossy -w` without `-L` still rejects; recovery token alone cannot bypass `-w` or exact-token verification. No accidental compression after an inventory/preview/recovery mode conflict; preview/count/qualities and comparison/perceptual combinations validate consistently.
- [ ] Retain `-K` functionality for existing workflows and explain that it is normally unnecessary. Do not remove a capability merely to reduce the flag count. The attachment's proposed `--sampling-profile-policy` is absent from the current plan/code; do not add it. Its “<5ms” calculation claim is unmeasured and not an acceptance criterion.
- [ ] Major-version migration: compresser1.0.0/MangaDL2.0.0 (or next available major if versions have advanced), update dependency minima/help registry, full editable-entrypoint reinstall per repository rules, and verify installed wrappers. Include old→new command examples and test help excludes deprecated flags while aliases still execute safely. No new entrypoint name or separate recovery subcommand is needed in this checkpoint.
- [ ] Run all common checks below plus parser/help/entrypoint tests; commit/push the verified feature branch under standing authority. Final whole-branch review covers all P0-P8 changes, especially safety and compatibility; no automatic merge back to main.

## Common checkpoint validation and delivery

For each authorized checkpoint: write behavior tests first, observe the intended failure, implement the scoped change, run focused tests and full affected module suites, then update docs/version/help metadata. Performance tests use barriers/counters for correctness, not fragile elapsed-time assertions. Keep before/after benchmark settings identical and report regressions or non-improvements.

From repository root, using the active venv (replace the temp suffix per checkpoint):

```powershell
.venv/Scripts/python.exe -m pytest modules/compresser/tests -q -p no:cacheprovider --basetemp=modules/compresser/.pytest_tmp_root/pipeline-CHECKPOINT --tb=short
.venv/Scripts/python.exe -m pytest modules/mangadl/tests -o addopts= -q -p no:cacheprovider --tb=short
.venv/Scripts/python.exe -m pytest modules/scripts_help/tests -q -p no:cacheprovider --basetemp=modules/scripts_help/.pytest_tmp_root/pipeline-CHECKPOINT --tb=short
```

Run black120/ruff on changed Python and `git diff --check`. If termdash changes, run its full suite too; if cross_platform changes, run its suite from its package root (existing import constraints). Real Windows terminal and reader acceptance stay explicit manual gates, not replaced by StringIO fixtures. Run no production inventory/encode merely because a plan lists a target path. Stage only reviewed task paths and commit/push only under applicable direct user authority; never infer it from this document.

## Documentation update tasks

- [ ] Each new CLI/profile/policy entry documents current versus proposed behavior, profile validation, uncertainty, effective concurrency and safe read-only commands in both module READMEs.
- [ ] Update `docs/HANDOFF.md`, repo plans handoff and both module handoffs at actual execution checkpoints; preserve the excluded repair Task6 distinction.
- [ ] Update termdash handoff only if its public APIs change; keep callers on supported `ProgressBar.set_total/str` and `LiveBlock.close` APIs.

## Primary references checked for this review

- [Python3.12 os.walk/scandir](https://docs.python.org/3.12/library/os.html#os.walk): walk already uses scandir; directory entry observations may be cached and must not be treated as permanent freshness evidence.
- [Python3.12 concurrent.futures](https://docs.python.org/3.12/library/concurrent.futures.html): map collects inputs immediately; use explicit bounded submission on supported Python versions.
- [Python3.12 sqlite3](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.connect): connection thread ownership and user serialization requirements.
- [Pillow file lifecycle](https://pillow.readthedocs.io/en/stable/reference/open_files.html): header open versus pixel load and explicit close/context ownership.
- [Statistics Canada, stratified allocation](https://www150.statcan.gc.ca/n1/pub/12-001-x/2015002/article/14249/02-eng.htm): estimator variance, precision objectives and cost constraints; inventory proxy variance is not measured compression-outcome variance.

## Status

Implementation authorized2026-10-17. Prior feature branch merged locally into main at0672a42 after199 compression/309 MangaDL/55 help/129 cross_platform passed (1+4 platform skips); main not pushed. Active implementation branch `compression-pipeline-and-cli-20261017`. P8 argument review integrated; P0 starts first. The earlier repair Task6 pilot/confirmation machinery remains excluded.
