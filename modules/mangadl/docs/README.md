# mangadl Documentation

- [Project handoff](HANDOFF.md)
- [Plan index](plans/HANDOFF.md)
- [Image compression and perceptual optimization plan](../../../docs/plans/20261013-0151_compression-module-and-mangadl-integration/00_implementation-plan.md)
- [Active library identity, audit, repair, and Kavita plan](plans/20261009-1204_library-identity-audit-and-kavita-operations/00_implementation-plan.md)
- [Kavita collection assignment plan](../../../docs/plans/20261009-0349_kavita-module-mangadl-collections/00_implementation-plan.md)
- [URL-file audit and repair plan](plans/20261009-0409_url-file-audit-and-repair/00_implementation-plan.md) (historical; live nhentai repair accepted under the generalized repair plan)
- [Active graceful quit and worker scaling plan](plans/20261009-0325_graceful-quit-and-worker-scaling/00_implementation-plan.md)
- [Active SSD scratch staging plan](plans/20260926-1224_ssd-scratch-staging/00_implementation-plan.md)
- [Historical partial-safety and merge-readiness plan](plans/20260921-0943_partial-safety-and-merge-readiness/00_implementation-plan.md)
- [Managed gallery-dl auth plan](plans/20260825-0540_gallery-dl-managed-auth/00_implementation-plan.md)

---

## Subcommands

### `mangadl compress`

MangaDL1.30.0 integrates compresser0.2.0. Both CLIs default to lossless;
lossy/perceptual writes require `-w -L`. Analysis never mutates pending recovery.
PNG/WebP/JPEG candidates are measured; original files remain if nothing smaller
passes verification. AVIF is explicit lossy only. Exact URL/folder selection,
separate persistent cache, stratified estimates and shared transient UI are
implemented. Pending transactions block writes; `compress -d GALLERY -R`
previews recovery, then `-R -w -C TOKEN` applies that exact record. Real-terminal,
nested-gallery and concurrent-download coordination acceptance remain pending;
do not bulk-write a production library yet.

Integrates the reusable `compresser` module to analyze, benchmark, and compress gallery images within downloaded libraries.

- **Non-destructive Analysis by Default**: Dry-run scanning evaluates compression ratios, estimated savings, and perceptual quality metrics without modifying any files on disk.
- **Explicit Write Mode (`-w / --write`)**: Modifies files only when explicitly requested.
- **Explicit Lossy Permission (`-L / --allow-lossy`)**: Write mode refuses lossy compression without this flag or an explicit lossy mode.
- **Audit Invariant Safety**: Verifies temporary outputs, records cross-extension changes in `.compress_journal.json`, and exposes explicit recovery. Cross-extension publication is journaled, not atomic; analysis never recovers at startup.
- **Reader Compatibility Guard**: Detects manhwa images exceeding WebP's 16,383px dimension ceiling and safely retains them in optimized JPEG/PNG format.
