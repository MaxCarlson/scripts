# AEBN Media Integrity

## Goal

Prevent incomplete or timestamp-corrupt AEBN scene/movie MP4s from being reported as successful, archived as downloaded, accepted as existing valid output, or used as verified replacements in historical reconciliation. Preserve resumability without trusting partial writes or mismatched fragments.

## Constraints

- No live AEBN requests or media downloads.
- No production output, archive, index, or media mutation.
- Keep `ytaedl` and vendored `aebndl` independently installable; do not add a mandatory cross-package dependency.
- Keep the scheduler worktree untouched.
- Validate with synthetic fragmented MP4, mocked network responses, and temporary files.
- Commit on `codex/aebn-media-integrity-20261106`; do not merge.

## Approach

Retain the current segment pipeline unless controlled fixtures prove it corrupts valid fragments. Make segment completion explicit and crash-safe, then validate intermediate and final media independently. Run metadata rewriting into a separate staging artifact, validate it, and only then promote it. Use the same fail-closed stream-coverage rules in the standalone AEBN downloader, ytaedl's AEBN duplicate/archive path, and reconciliation verification through package-local adapters.

The alternative of replacing raw fragmented-MP4 concatenation up front is not justified until packet/fragment evidence or a synthetic fixture demonstrates that valid fragments are corrupted by it.

## Work stages

1. Establish local provenance and reproduce metadata/mux behavior offline.
2. Add tests for output stream coverage, metadata rewrite preservation, final completion ordering, and existing-output validation.
3. Implement staged finalization and mandatory independent stream-duration validation.
4. Harden fragment inventory, atomic writes, resume-state validation, interruption status, and thread cleanup.
5. Gate ytaedl archive/duplicate success on AEBN output validation; strengthen reconciliation and invalidate older weak verification evidence.
6. Run synthetic end-to-end and targeted regression suites; generate a read-only 68-file report; review, document, and commit.

## Evidence checkpoint

- Local base: `c12779ab7dc69bac133b495757dc97989a51dcf9`.
- New branch/worktree: `codex/aebn-media-integrity-20261106` / `.worktrees/aebn-media-integrity-20261106`.
- Installed command wrappers resolve to the repository venv. Distribution metadata reports ytaedl 2.14.0 and aebndl 0.7.7 as editable installs, while the checked-out source declares ytaedl 2.17.0 and aebndl 0.8.0. Historical process logs do not contain an executable hash/version, so exact historical wrapper provenance remains unproven.
- Fresh output: 60,370,817 bytes; audio duration 1,756.562 s; video duration 2.002 s; 2,281 video packets / 2,168 decoded frames. Raw `complete.file_size` and archive size are about 485.7 MB. The completion event occurs before `add_metadata()` in source.
- A healthy 120-second fragmented fixture survived the current metadata rewrite with 3,600 video frames and both stream durations unchanged; rewrite added about 54 KB.
- A collapsed-timeline synthetic fixture (900 frames/2.0009 s plus 30.021 s audio) retained all packets/frames and durations through the current metadata rewrite; it added one chapter and one data stream, with a 712-byte size increase. This does not reproduce the incident's 87.6% size reduction.
- Retained `_partial`/`.part` state is for Busty Vixens 2, movie 322251, not the fresh movie 215286. Its URL-file path and worker slot match the fresh job; segment reuse remains a lower-priority unproven hypothesis.
- The same manager log shows the one-URL scene job finishing and then assigning persisted `jaye_summers.txt`, explaining the TUI transition.
- Baseline focused suites: AEBN downloader 68 passed; ytaedl AEBN/reconciliation 85 passed. Use `--import-mode=importlib` to avoid cross-module `tests.conftest` collisions in the shared venv.

## Main uncertainty

The fresh pre-metadata MP4 and its scene-215286 fragments were not retained. The logged pre-metadata size and final on-disk size strongly suggest postprocessing changed the artifact, but no direct before/after packet trace for that real file exists. Synthetic tests narrow behavior but cannot establish live AEBN fragment behavior.
