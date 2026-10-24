# Media Safety Contract — Video Compression and Recovery

**Companion to:** [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md), especially §§4, 8, 10, 13–14.  
**Classification:** Normative safety acceptance requirements, with implementation mechanics subject to agent review.  
**Scope:** Library inventory, previews, experimental transcodes, file publication, optional in-place replacement and recovery.  
**Default:** Never mutate, delete, overwrite or rename a source media file without an explicit, scoped authorization. A `plan` or `estimate` is not an `apply`.

## 1. Safety invariants (must remain true under crashes and cancellation)

- **S1 — Original preservation:** Inventory, plan, estimate, analyze, compare and preview never modify originals. The initial `apply` implementation must also retain originals by writing verified outputs to a separate tree. In-place replacement is a later, separately authorized mode.
- **S2 — No silent loss:** Every expected video/audio/subtitle/attachment/data stream, chapter, track disposition and required metadata field either survives according to a declared policy or causes a recorded `skip`/`verification_failed`. Do not infer preservation from an FFmpeg exit code.
- **S3 — No unrelated overwrite:** No destination publication may clobber an existing unrelated file, including same-basename sources from different folders. Relative structure and target identity remain unambiguous.
- **S4 — Source change protection:** The source must not change between the identity snapshot used for encoding and the final publication gate. A path, size and mtime match alone is provisional; before destructive replacement use a stronger source-verification policy (prefer full hash) and document performance costs.
- **S5 — Bounded scratch:** Never start a candidate unless output staging and rollback capacity satisfy the configured free-space floor. Actual disk exhaustion is recoverable without source loss.
- **S6 — Recoverable publication:** Journal enough durable state to resolve every partial publication without guessing what belongs to the source, candidate or backup. Never claim completed without verified published bytes.
- **S7 — Locks are real locks:** Coordinate overlapping source operations through `cross_platform.locks` OS-backed ownership. Do not treat an existing lock filename as proof of an active lock, and do not unlink a persistent OS lock file to "fix" a stale appearance.
- **S8 — Cancellations are observable:** On `Ctrl+C`, TUI cancel/quit, timeout or worker crash, terminate managed FFmpeg descendants and preserve a durable interrupted/failed job record. Never mark a partial output successful.
- **S9 — Lossy permission:** Any operation replacing an existing original with a lossy candidate requires explicit write and lossy flags and any required confirmation token. Size/quality estimates are not authorization.
- **S10 — Exclusions remain visible:** Unsupported, unknown, excluded, corrupt and verification-failed assets count toward inventory/report denominators and must have reasons; no silent skipped video.

## 2. Preservation decision matrix

| Asset/properties | Default behavior | Verification / unsafe case |
|---|---|---|
| Main video track | Explicit selection and encode; preserve display orientation, frame dimensions/FPS policy, aspect, interlace/color fields | Fail on unapproved crop, rotate, scale, FPS change, unexpected extra/missing video track; attached cover art is not the main video |
| Multiple real video tracks | Count and inventory all; no automatic source-replacement until explicit multi-track policy implemented | Fail if a second angle/video track would be lost |
| Audio tracks | Copy every track, preserve order, language, default/forced disposition and channels by default | Container incompatible with copy ⇒ skip or require an explicitly different recipe; no silent AAC conversion |
| Subtitle tracks | Copy every compatible text/image subtitle with order/disposition/language | MP4/Matroska compatibility differences ⇒ skip rather than silently discard or burn in |
| Attachments/fonts/data | Preserve if output format supports them and policy requires | Fonts, attachments and data not automatically selected by FFmpeg; skip incompatible remux/transcode |
| Chapters | Preserve timestamps/names and chapter metadata when supported | No silent chapter loss or unexplained time shift |
| Container/metadata | Preserve container initially; copy required tags, creation times when configured and stream dispositions | Metadata can be container-specific; maintain explicit allowlist/equivalence tests rather than naive byte equality |
| Timing | Preserve audio/video synchronization, time base semantics, presentation duration and variable-frame-rate characteristics unless recipe says otherwise | Check pts/dts, stream start/end, A/V drift and frame/drop/duplicate anomalies to declared tolerance |
| Color/bit depth/HDR10 | Inventory color space, transfer, primaries, mastering metadata, light levels and bit depth | Unsupported preservation/metric ⇒ skip automatic lossy replacement; no accidental SDR tone-map |
| Dolby Vision/HDR10+/dynamic metadata | Record/identify dynamic metadata where feasible | **Default ineligible** for automatic lossy replacement until demonstrably preserved and verified end to end |
| Source filename/path | Preserve source folder layout in output tree, account for extension changes | Reject collisions, traversal, symlink/reparse-point aliases and mismatched canonical target identities |
| Originals/sidecars | Never touch originals or adjacent metadata sidecars by default | Separate cleanup operation with fresh confirmation and verified independent backup policy |

**Important:** A default stream-copy policy is not proof that every stream can be copied to a different container. Require per-container compatibility checks before encoding. FFmpeg's default stream selection is incomplete for these requirements: construct explicit `-map`/`-map_metadata`/`-map_chapters` policies and verify the result. Review cover art and attachments separately.

## 3. Media verification levels

- **`V0 inventory`:** source stat and probe facts, no guarantee of complete decodability.
- **`V1 structural`:** output exists, final size > 0, exact output container and streams probe correctly; compare expected stream manifest and declared transformation. Mandatory for trial artifacts.
- **`V2 full decode`:** decode all applicable output video and audio streams to a sink (e.g. FFmpeg `-f null -` with appropriate mapping); check nonzero errors, presentation duration, frame/timebase anomalies, stream metadata and chapter/attachment survival. Mandatory for publication. A successful decode alone does not prove visual equivalence.
- **`V3 perceptual`:** appropriately aligned decoded source/output; apply supported SDR metric models plus difficult-scene review and declared tolerances. Quality tests must record chosen metric model/version and preprocessing. Mandatory where a lossy quality gate claims compliance.
- **`V4 playback compatibility`:** optional separate target-player/container compatibility profile, beyond merely decoder success. If target-player compatibility is a hard requirement, apply needs explicit evidence or must abstain.

No automatic lossy replacement may bypass its configured V2/V3 gates because a quality metric is unavailable; that is an `unsupported_quality_validation` reason. Unsupported HDR/Dolby Vision is a policy refusal, not a low VMAF score.

## 4. Publication modes and authorization

| Mode | Source mutation | Authorization | Initial implementation? |
|---|---|---|---|
| `inventory`, `plan`, `estimate-metadata` | None | None beyond read access | Yes |
| `estimate-sampled`, `compare`, `preview`, `calibrate` | None; temporary/test outputs only | Explicit budget/encode opt-in; no implicit expensive work | Yes |
| `apply --output-root PATH` | None; candidate published externally | Explicit `-w/--write` for final publication; `-L/--allow-lossy` as policy requires | Yes, after safety gates |
| `apply --in-place` | Replaces source path, with verified backup retained | Explicit `-w`, `-L`, separate in-place enablement + scoped confirmation | Later only |
| `cleanup` / deletion of originals | Irreversible effect | Separate command and confirmation; verified backup/retention review | **Deferred** |

`--dry-run`/omitted `--write` must not publish final outputs. Experimental encode tiers *may* write isolated scratch/preview artifacts with explicit consent/budget, but must not modify the library tree. All output paths must be outside any scanned input tree unless an explicit exclusion and collision-proof policy is validated.

## 5. Transaction journal and source identity

A versioned per-job manifest should have an idempotent `job_id`, normalized source/target paths, policy and recipe IDs, source fingerprints, selected streams, FFmpeg runtime, reservations, staged/backup paths, output hashes, verification report IDs, user authorization evidence and timestamps.

Suggested **monotonic state graph** (finalize under tests):

```text
PLANNED -> ELIGIBLE -> ADMITTED -> ENCODING -> CANDIDATE_WRITTEN
      -> VERIFYING -> VERIFIED -> SOURCE_RECHECKED -> PUBLISHING
      -> PUBLISHED -> COMPLETED
          \--> SKIPPED / FAILED / INTERRUPTED / RECOVERY_REQUIRED
```

Journal records need **phase-specific** durable evidence, not just an editable `status` string. E.g., `PUBLISHING` means commit intent was fsynced; `PUBLISHED` requires destination identity and hash verification; `COMPLETED` means report and retention policy are reconciled. Transitions must be idempotent and reject invalid state regression.

Write journal updates by exclusive temp file + flush/fsync + atomic replacement on the same volume when supported; test Windows behavior. Ensure directory durability as far as the platform supports it and report limits candidly. Never assume atomicity across volumes or claim power-loss durability beyond what the OS/filesystem proves.

### Source identity and alias safety

1. Canonicalize destination-relative paths under an authorized root, reject path traversal, restricted device paths, symlinks/reparse-point surprises and hardlink aliases by default.
2. Inventory identity may use `(canonical scope, relative path, stat fingerprint)` for speed; this is **not** the same strength as a pre-publication content identity.
3. Re-stat/re-probe just before encoding; before a destructive commit revalidate the source with full or policy-approved strong hash. Prevent TOCTOU via scoped locks, exclusive ownership and handle-level identity where practical; acknowledge external non-cooperating writers may still require a final verification.
4. Unique staged outputs and job IDs must include canonical scope and source identity; never derive uniqueness from basename alone.
5. On publication, use no-clobber exclusive creation/rename semantics with tested native-platform fallbacks. Do not use FFmpeg `-y` on a path that might belong to user content.

## 6. Filesystem, space, backups and cross-volume cases

- Stage *encoding* on fast scratch if selected; use a **same-destination-volume** staging area for atomic final publication. Scratch→destination is a verified copy then same-volume publish, never assumed atomic cross-volume rename.
- Before starting, require a conservative reservation plus user-configured minimum free-space floor for input/output/staging/backup coexistence. Make `unknown_capacity` a blocking state for dangerous operations unless user explicitly sets a safe capacity policy.
- For separate-output apply, preserve sources indefinitely by default. For in-place apply, create an independently verified restore candidate (retained backup/rename under a journal) and verify it before replacing source path. A mirrored pair alone is **not** an independent backup.
- Never delete staging or backups merely because a process returned code 0. Cleanup is allowed only for artifacts proven superseded and not necessary for recovery; default cleanup policy must be explicit and tested.
- Preserve track metadata/file timestamps where specified; filesystem ACLs, alternate data streams, extended attributes and hardlinks may be unpreservable. The in-place implementation must detect those and refuse rather than pretending to preserve them.

## 7. Recovery and idempotence

- `recover` without write authorization is **inspection-only**: list outstanding jobs, source/staged/backup/destination identities, last verified transition and safe choices.
- Recovery actions require `-w/--write` plus a fresh target/job-scoped confirmation token. They must reacquire relevant locks, independently inspect current bytes and never guess that a same-named file is ours.
- A recovered job can either complete a verified publication or restore a verified backup; never silently overwrite a newer user's file. If paths disagree or source identity changed, stop with `manual_intervention_required` and preserve evidence.
- If interrupted during full encoding, batch resume reuses verified completed jobs and re-encodes incomplete files; no promise of arbitrary frame-perfect mid-file resume.
- Cache/result records marked `completed` require corresponding output identity/verification evidence; a file's mere existence is insufficient.

## 8. Failure-injection matrix (minimum)

| Injection point | Expected invariant / observed state |
|---|---|
| Before admit / during capability probe | No media mutation, correct skip/failure report |
| FFmpeg missing, bad args, encoder fails, nonzero exit | Original unchanged; candidate quarantined; not published |
| FFmpeg hangs, timeout, user cancel, TUI forced exit | Kill managed subprocess tree; persist interrupted state; no orphan encoders |
| Power/process loss during write/verification | Journal identifies uncommitted candidate; original intact |
| Disk full during encode/scratch→destination copy/journal flush | No partial destination presented as verified; no source loss |
| Journal saved but publish not started; crash during rename | Recovery compares actual on-disk identities, not stale intent alone |
| After publish, before `COMPLETED` journal | Inspect existing output hash; idempotently finalize, don't duplicate |
| Concurrent overlapping target operations | Exclusivity enforced; actionable conflict diagnosis |
| Independent sibling folders | No false conflict; separate workspace+lock identities |
| Source changes mid-job / output destination collision | Skip/abort; no replacement of changed or unrelated content |
| Wrong stream count/disposition, lost chapters/fonts, color mismatch | Verification fails before publish |
| VMAF unavailable, malformed metric JSON, unsupported HDR | No false quality pass; explicit unsupported/failed result |
| Source symlink, destination junction/reparse alias, hardlinks | Fail closed or pass deliberately tested policy; no escape from authorized roots |
| Partial output with apparent valid headers | Full decode/stream verification catches or classifies uncertainty; no existence-only pass |

Each failure test should assert original bytes or cryptographic digest, directory tree and sidecars unchanged, output ownership, journal state and lock release. Where a behavior cannot be simulated reliably, add a clearly labeled manual platform-specific acceptance test.

## 9. Report and approval contract

Per input item, report source bytes, target recipe, measured/estimated output, eligibility, stream-preservation result, verification level, actual publish mode, saved bytes, current journal state, error codes, retained source/backup location and whether the outcome requires user action. Aggregate complete, skipped, unsupported, failed, interrupted, untouched and externally-published items; sum only **verified actual published savings** in a field called `realized_savings_bytes`.

A safe dry-run report must never display estimated savings as realized. A successful partial batch with failed items must retain failures and return documented exit status, not conceal them.

## 10. Engineering references

- [FFmpeg stream selection and mapping](https://ffmpeg.org/ffmpeg.html#Stream-selection).
- [FFprobe format/stream/packet selection](https://ffmpeg.org/ffprobe.html).
- [NVIDIA Video Codec SDK](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/).
- Local `scripts`: `modules/cross_platform/locks.py`, `modules/compresser/compresser/transactions.py` (image-specific design reference), `pyscripts/video_processor.py` (audit before copying), `modules/video_dataset_tools` (test fixtures).

**Safety acceptance gate:** No in-place publication or cleanup implementation proceeds until synthetic-media fault-injection tests pass on the target filesystem/OS and the user separately authorizes that risky stage. Unsupported cases must fail closed instead of weakening safeguards.
