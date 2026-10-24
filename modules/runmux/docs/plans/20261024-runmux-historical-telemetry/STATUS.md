# Status — Runmux Historical Telemetry Architecture (Phase 5C)

**Date:** 2026-10-24  
**Branch:** `codex/runmux-historical-telemetry-20261024`  
**Base:** `origin/main` (commit `6fa307f3bd84761f6fe21f3700dceb9889fe090b`)  
**Current Stage:** Architecture Proposal Finalized (Awaiting Final User Approvals)  
**Approval State:** User accepted direction in principle; requested 7 specific corrections and rebenchmarks; awaiting final decision approvals before Stage 1 implementation.

---

### Completed Verification & Correction Evidence
1. **Windows Sampling Overhead Recalculated:**
   - Proved mathematically and empirically that 5.0s sampling with 5.0s TTL yields a **0.0% hit rate** (33.3 ms / process).
   - Proved that decoupling cache TTL to **30.0 seconds** achieves an **85.7% hit rate** (6 hits per miss), reducing average sampling latency to **4.76 ms / process** (1.9% CPU for 20 active runs).
2. **Rebenchmarked SQLite with Full Schema & Realistic Run IDs:**
   - Evaluated genuine 22-char Run IDs (`YYYYMMDD-HHMMSS-xxxxxx`), full 5-table schema, and indexes.
   - Measured actual on-disk row footprint: **140.7 bytes / row**.
   - Verified WAL truncation: `PRAGMA wal_checkpoint(TRUNCATE)` executes in $< 4.2\text{ ms}$ and truncates WAL to 0 bytes.
   - Verified 1-hour range query latency: **0.98 ms** for 720 rows.
   - Verified deletion pruning: 25,000 rows pruned in $25.5\text{ ms}$; `PRAGMA incremental_vacuum` reclaims pages in $0.18\text{ ms}$.
3. **Storage Budget & Enforceable Limits Defined:**
   - Reconciled steady-state storage: 395.1 KB / run for 7 full days of history.
   - Defined 15-minute maintenance cycle enforcing 50 MB hard cap via WAL truncation, incremental vacuum, and emergency rollup pruning.
4. **State-Directory-Local Path Resolution:**
   - Anchored database to `ensure_state_tree(state_dir or get_state_dir()) / "telemetry.sqlite3"`, honoring `RUNMUX_HOME` and `--state-dir`.
5. **API Contract Examples Corrected:**
   - Updated with genuine 22-character Run IDs, ISO 8601 UTC timestamps, and `sample_interval_seconds` monotonic measurements.
6. **Memory Capacity Reconciled:**
   - Reconciled across all documents: 720 samples (1 hour at 5.0s interval) $\times$ 128.2 bytes = **92.3 KB / active run**.
7. **In-Memory vs. SQLite Coordination Reevaluated:**
   - Formulated Write-Through Tiered Hybrid to eliminate dual-source boundary-merging complexity while preserving sub-millisecond UI query response.

---

### Next Action
- Present the finalized Phase 5C architecture report to the user.
- Await final user approval on the 4 decisions in `06_approval_decisions.md` before implementing Stage 1.
