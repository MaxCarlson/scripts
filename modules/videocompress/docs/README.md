# Video Compression — Local Agent Handoff Package

**Prepared:** October 23, 2026. **Reference repo:** `MaxCarlson/scripts` `main` at `a0ff1778` (October 20). **Status:** Planning and research, *not* a record of implemented or locally tested code.

## Read in this order

1. [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — overall architecture, scope, repository review, research findings, stages and agent authorization boundaries.
2. [`ESTIMATION_BENCHMARK_PROTOCOL.md`](ESTIMATION_BENCHMARK_PROTOCOL.md) — experiment design, ground truth, accuracy/decision metrics and selection gates.
3. [`MEDIA_SAFETY_CONTRACT.md`](MEDIA_SAFETY_CONTRACT.md) — non-destructive behavior, stream/HDR preservation, verification, journaling and recovery guarantees.
4. [`INTEGRATION_CONTRACTS.md`](INTEGRATION_CONTRACTS.md) — proposed typed contracts and integration between `videocompress`, `compresser`, `cli_tui` and shared utilities.

**Precedence:** Live repository state, executed tests, official current tool contracts and the user's explicit approval override old assumptions in this package. The supporting documents refine the corresponding requirements in the main plan but do not independently authorize edits or destructive actions. If a proposed contract conflicts with demonstrably better evidence, revise the plan **before** implementation, explain the rationale and obtain any required approval.

## Initial agent assignment

> Independently inspect the `scripts` checkout and evaluate the four attached documents. Verify existing code, tests, CLI/TUI APIs, FFmpeg/NVIDIA capabilities, external `ab-av1` integration, codec-to-codec estimation approaches and preservation constraints. Challenge assumptions rather than treating the documents as gospel. Deliver a revised, staged implementation plan with a decision log, precise public interfaces, dependencies, benchmark corpus/budget proposal, risks and explicit acceptance gates. Do not perform production transcoding, destructive operations, code modifications, commits, pushes or merges without the applicable authorization.

## Critical design decisions to preserve unless independently disproven

- Inventory (`files`/`probe`) and planning do not encode target videos.
- Eligibility filters use **video-stream** bitrate, resolution and separate minimum *benefit* gates. Unknowns stay visible.
- The expensive sampled estimator is opt-in and budgeted; metadata-only predictions may abstain; quality/size evidence comes before any final apply.
- Prediction performance is tested against complete-file ground truth, with group-disjoint held-out sources and honest interval labels.
- Originals, streams, timing and metadata are preserved according to explicit policy, or the operation fails/skips; output publication and source replacement have separate authorization.
- Existing image `compresser` and MangaDL behavior must remain compatible. Add `compresser tui` by reusing `cli_tui`, not inventing a second TUI framework.
- Native Windows curses startup, FFmpeg descendant-tree cancellation and RTX 5090 capability/efficiency must be validated rather than assumed.

## Expected first response from the local agent

A concise list of (1) verified architecture and code drift, (2) proposed changes to this plan with reasons, (3) unresolved questions and approval needs, (4) a test/benchmark plan with bounded real compute and space usage, and (5) an ordered implementation checklist. Do not present hypotheses as completed tests or measured results.

## Sources and reproducibility

All cited repositories, papers and primary tools are linked in `IMPLEMENTATION_PLAN.md` and `ESTIMATION_BENCHMARK_PROTOCOL.md`. Reverify versions and interfaces against the local installation. Local fixtures/benchmarks must not scan the user's production media without specific authorization. Treat absolute paths, source titles and metadata as potentially private when publishing reports.
