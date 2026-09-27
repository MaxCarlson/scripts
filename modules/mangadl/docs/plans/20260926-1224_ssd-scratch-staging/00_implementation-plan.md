# SSD scratch staging plan

## Objective

Allow an explicit fast scratch volume for active MangaDL image downloads while keeping the final library on a slower disk. Preserve the four-worker default safety ceiling, the existing archive path, and recoverable partial ownership.

## Storage evidence

On the user's machine, B: is a thin two-copy Storage Spaces mirror over two 24 TB SATA HDDs, with no SSD tier or write cache. E: is a separate NVMe SSD. Four series workers plus inner image threads generate small-file writes and metadata seeks that can saturate B: despite modest transfer throughput. This is a machine-specific observation, not a portable assumption.

## Stages

1. Add optional scratch staging, isolate partials by destination, serialize final promotions, copy to same-volume temporary files and rename, preserve staged data on collision or I/O failure, and expose scratch partial cleanup. Validate with synthetic tests; do not start a live download.
2. Apply user feedback: `-S/--scratch`, destination-aware duplicate checks for supported backends, active archive/state/log staging, safe final sync, and fail-closed routing for unsupported backends. Validate without a live download.
3. After user validation, measure B: active time and throughput with a bounded real workload. Decide whether residual metadata checks or final-write behavior warrant more work.

## Invariants

- No scratch option means existing paths and behavior stay unchanged.
- Dry-run creates no scratch or library files.
- Existing destination files are never silently replaced by scratch promotion; a mismatch retains scratch data and fails the job.
- A failed copy retains its source and removes its incomplete destination temporary.
- Existing destination archive/state history is imported to scratch before work and synced back at the end; new archive rows are withheld from B: while scratch partials remain.
- Existing B: partials are not moved or deleted automatically; enabling scratch changes where future partials are found.
- Only verified scratch backends are accepted; normal no-scratch routes remain unchanged.
