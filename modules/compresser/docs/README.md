# Compresser API and architecture

[Usage](../README.md) · [Handoff](HANDOFF.md) ·
[Reviewed plan](../../../docs/plans/20261013-0151_compression-module-and-mangadl-integration/05_reviewed-plan.md)

Actual public exports: ImageMetadata, ScanSummary, CompressionStrategy,
ImageResult, BatchResult, ComparisonRow, AnalysisCache, CompressionEngine,
analyze_collection, compare_strategies, compress_collection, scan_directory,
select_sample and discover_available_codecs.

```python
from pathlib import Path
from compresser import AnalysisCache, CompressionEngine, CompressionStrategy, scan_directory
cache = AnalysisCache(path=Path("E:/Temp/compression-cache.sqlite3"))
summary, images = scan_directory(Path("B:/Hent/hent1imageperpage"), cache=cache)
result = CompressionEngine(cache).compress_batch(
    images, CompressionStrategy("lossless-auto", mode="lossless"),
    write_mode=False, threads=4,
)
```

`analyze_collection(target_path, recursive=True, sample_size=None)` returns
(summary, metadata list). `compare_strategies(images, strategies, threads=4,
cache=None)` returns comparison rows; `compress_collection(images, strategy,
write_mode=False, threads=4, cache=None)` returns BatchResult.
Compression API defaults are lossless/read-only. Unsupported encoder combinations
produce per-file errors while preserving inputs; results must be checked.

Scanner inventory cache stores metadata, never encoded image bytes. The engine
enforces decode/working-set bounds, verifies samples/geometry/metadata, chooses
measured candidates and publishes only approved writes. Transactions use source
and output fingerprints, durable records and OS ownership. Explicit recovery is
shared through `compresser.recovery.recovery_plan` and `run_recovery`.
Engine batch/single-image writes and recovery apply also acquire an established
MangaDL library's `.mangadl/operation.lock`. The batch owner holds it through all
worker completion. MangaDL uses the same guard; unrelated external writers do not
honor it and must not run concurrently. Analysis does not create controls or locks.
`compresser.estimates.estimate_savings(images, results)` returns coverage-aware
projections, with null total savings when some population strata are unestimated.

Termdash LiveBlock owns transient progress on stderr; summary tables are stdout,
plain when redirected or NO_COLOR is set. CLI JSON is a single document. Progress
has no invented Pillow encoding percentage; gallery and overall counts use real
completed images, with elapsed and rolling15-second ETA.

Tests are offline and module-local, including child-process crash boundaries.
Production compression and reader/real-terminal acceptance remain outside the
completed fixture checks.

