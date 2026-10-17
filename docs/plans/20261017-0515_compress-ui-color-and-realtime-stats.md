# Plan: Compression UI Polish, Color Hierarchy, Real-Time Statistics & Memory Budget Scaling

## Context & Objectives
During large-library compression runs (`mangadl compress`), users interact with several distinct phases (scanning/inventory, sampling, encoding benchmark/write, and final reporting). The current UI lacks clear phase indicators, is predominantly monochromatic, lacks real-time breakdown statistics for file types and worker concurrency, exhibits a noticeable silent startup delay during `-U trust` snapshot verification, suffers from an artificial 4096 MiB memory ceiling that throttles multi-threading on high-RAM machines (e.g., 64 GB), and produces an unformatted 87-line diagnostic dump at completion.

This plan details:
1. Eliminating the silent startup delay and adding a responsive status indicator during `-U trust` snapshot verification.
2. Distinct, colored phase indicators across all UI states.
3. Enhanced color hierarchy for termdash live dashboards and comparison tables.
4. Real-time file-type distribution table during inventory scanning.
5. Real-time per-worker utilization table and end-of-run concurrency efficiency report.
6. Flexible, uncapped memory budgeting (`-B 16G`, `-B 50%`, `-B auto`) to fully unlock worker threads on modern systems.
7. Executive final summary report with winning strategy callout, full-library projected savings, fidelity badges, and copy-paste execution command.
8. Command-line argument cleanup and simplification.

---

## 1. Startup Delay & Snapshot Verification UX (`-U trust`)

### What Was Observed
When running `-U trust`, the terminal showed no output for several seconds before the dashboard suddenly appeared. The command was not deadlocked; rather, it was silently deserializing and filtering the 82,000+ file records from SQLite in memory to verify snapshot membership and calculate gallery sampling quotas before rendering the first frame.

### Planned UX Improvements
- **Immediate Startup Feedback:** Print or display an immediate spinner / status line:
  `[VERIFYING SNAPSHOT] Loading cached inventory from SQLite...`
- **Fast Snapshot Header Probe:** Rather than fetching and hydrating all 80k+ `ImageMetadata` objects to check trust validity, inspect the lightweight `inventory_runs` metadata record first in < 5ms.
- **Path Sanitization:** Normalize paths strictly with `.resolve()` and strip trailing path separators so `'B:\Hent\tmphent3\'` and `'B:\Hent\tmphent3'` match identically without hesitation.

---

## 2. Flexible, Uncapped Memory Budgeting (`-B`)

### The Problem
Currently, `-B/--memory-budget-mib` enforces an artificial limit: `Use -B auto or an integer 64..4096MiB`. On a modern workstation with 32 GB or 64 GB of RAM, capping the pool at 4 GB causes large webtoon pages (e.g. 720x15000, which allocate ~494 MB decoded) to throttle 8 worker threads down to 1 active worker.

### Planned Redesign
- **Lift the 4096 MiB Ceiling:** Allow `-B` to scale up to the host machine's physical RAM.
- **Human-Friendly Units:** Parse strings like:
  - `-B 16G`, `-B 16GB`, `-B 8G`
  - `-B 2048M`, `-B 2048`
  - `-B 50%` (percentage of total system RAM)
- **Smart Default (`-B auto`):**
  When `-B` is omitted, default to:
  $$\text{Budget} = \min(32 \text{ GB},\; \max(2 \text{ GB},\; 0.50 \times \text{Available RAM}))$$
  On a 64 GB workstation, `-B auto` automatically provides 16–32 GB across the worker pool, ensuring threads are never starved by memory reservations.
- **Dynamic Pool Sharing:** All worker threads draw and return reservations from this single global pool dynamically without thread starvation.

---

## 3. Phase Indicators & Visual Clarity

### Proposed Phase Headers
Every stage of `mangadl compress` will display an explicit, colored phase header:
- **Phase 1:** `[PHASE 1/2: INVENTORY DISCOVERY]` (Cyan / Bright White)
  - Sub-states: `[SCANNING HEADERS]` or `[REUSING SNAPSHOT]`
- **Phase 2:** `[PHASE 2/2: COMPRESSION BENCHMARK]` or `[PHASE 2/2: EXECUTING COMPRESSION]` (Green / Bright White)
  - Displays active strategy: `[STRATEGY 3/10: webp-lossy-q90]`

---

## 4. Real-Time Extension Breakdown Table (During Inventory)

During Phase 1 (Inventory Scan), add a dynamic, compact live table below the progress bars that updates as workers process files:

```text
╭─ [PHASE 1/2: INVENTORY DISCOVERY] ──────────────────────────────────────────────────╮
│ Target: B:\Hent\tmphent3  •  Mode: Verified Headers                                 │
╰─────────────────────────────────────────────────────────────────────────────────────╯

  PROGRESS
  Folder:  [████████████████████] 100.0% (104/104)  Folder: Island Girl
  Overall: [████████░░░░░░░░░░░░]  30.6% (56/183)   ETA: 00:04:12

  DISCOVERED ASSETS (LIVE)
  ┌───────┬─────────┬───────────┬───────────┐
  │ Ext   │   Files │      Size │ Share (%) │
  ├───────┼─────────┼───────────┼───────────┤
  │ .jpg  │  65,420 │  39.12 GB │     78.8% │
  │ .webp │  14,455 │   7.91 GB │     17.4% │
  │ .png  │   3,110 │   2.15 GB │      3.7% │
  ├───────┼─────────┼───────────┼───────────┤
  │ Total │  82,985 │  49.18 GB │    100.0% │
  └───────┴─────────┴───────────┴───────────┘

  THROUGHPUT & CACHE
  Rate: 580.5 files/s  •  I/O: 391.28 MiB/s  •  Reused: 0  •  Inspected: 82,985
```

---

## 5. Multi-Threading & Per-Worker Diagnostics

Multi-threading in image compression is constrained by both CPU and memory reservations (`-B`). To provide clear visibility into whether threads are productive or starved:

### Live Worker Table (Inside `CompresserDashboard`)
```text
  WORKER POOL UTILIZATION (8 Threads | Memory Budget: 16 GB)
  Slot  State       Current Task                 CPU Time  Memory     Processed
  #1    ENCODING    0042.jpg (webp-lossy-q85)    1.4s      18.2 MB    14 files (38.1 MB)
  #2    ENCODING    0006.jpg (720x15000 webtoon) 3.8s     494.4 MB     3 files (12.4 MB)
  #3    ENCODING    0019.jpg (jpeg-lossy-q90)    0.9s      22.1 MB    11 files (29.8 MB)
  #4    ENCODING    0025.jpg (webp-lossless)     2.1s      34.0 MB     9 files (24.1 MB)
  #5    WAIT_MEM    [Waiting for budget...]        —          —       12 files (31.5 MB)
  #6    ENCODING    0011.jpg (png-lossless)      1.1s      19.5 MB    10 files (27.0 MB)
  #7    ENCODING    0003.jpg (webp-lossy-q80)    0.8s      15.2 MB     8 files (21.9 MB)
  #8    ENCODING    0088.jpg (jpeg-lossless)     1.3s      28.7 MB    13 files (34.2 MB)

  Pool Efficiency: 87.5% active (7/8)  •  Memory Reserved: 632.1 MB / 16.0 GB
```

### End-of-Run Concurrency Diagnostics
```text
  HARDWARE & RESOURCE SUMMARY
  Workers:     8 threads requested, 8 effective (Peak memory reserved: 847.5 MB / 16.0 GB)
  Bottlenecks: None! Memory reservations ran smoothly with 0 preflight rejections.
  Cache:       80 hits, 100 misses (AUTO strategies reused cached trials instantly).
```

---

## 6. Final Results Summary & Extrapolation Reporting

When a compression benchmark or dry run completes, replace the plain 87-line Unicode text dump with a 3-part executive report:

### 1. Recommended Hero Banner
```text
╭─ COMPRESSION BENCHMARK RESULTS ────────────────────────────────────────────────────────╮
│ Target: 308191 A midsummer NTR dream  •  Evaluated: 10 Strategies on 10 Sample Images   │
╰────────────────────────────────────────────────────────────────────────────────────────╯

  🏆 RECOMMENDED STRATEGY
  Strategy:    webp-lossy-q80 (Maximum Storage Reduction)
  Perception:  SSIM 0.980 (Very subtle compression smoothing)
  Sample:      Saved 978.9 KB / 3.47 MB (▼ 28.3% reduction)
  Gallery Est: 33.85 MB  ──▶  23.93 MB  (Projected Savings: ~9.92 MB ± 0.96 MB)

  ⚖ BEST QUALITY/SPEED BALANCE
  Strategy:    webp-lossy-q90  •  SSIM: 0.997 (Near-Perceptual Lossless)  •  Saved: 2.1%
```

### 2. Tiered Comparison Matrix Table
```text
┌───┬──────────────────┬───────────┬─────────────┬──────────────┬─────────────┬────────────┐
│ # │ Strategy         │ Format    │ SSIM Score  │ Sample Saved │ Gallery Est │ Speed      │
├───┼──────────────────┼───────────┼─────────────┼──────────────┼─────────────┼────────────┤
│ ★ │ webp-lossy-q80   │ WEBP (80) │ 0.980 (✓)   │ 28.3% (-1.0M)│   -9.92 MB  │  3.0 img/s │
│ 2 │ webp-lossy-q90   │ WEBP (90) │ 0.997 (✓✓)  │  2.1% (-75K) │  -749.3 KB  │  3.0 img/s │
│ 3 │ webp-lossless    │ WEBP (LL) │ 1.000 (Loss)│  0.0% ( 0 B) │    0 B      │  0.5 img/s │
│ 4 │ png-lossless     │ PNG (LL)  │ 1.000 (Loss)│  0.0% ( 0 B) │    0 B      │  7.0 img/s │
│ 5 │ jpeg-lossy-q90   │ JPEG (90) │ 1.000 (Loss)│  0.0% ( 0 B) │    0 B      │  2.7 img/s │
│ 6 │ jpeg-lossy-q80   │ JPEG (80) │ 1.000 (Loss)│  0.0% ( 0 B) │    0 B      │  2.8 img/s │
│ ✗ │ jpeg-lossless    │ JPEG (LL) │   FAILED    │  0.0% ( 0 B) │    N/A      │    FAILED  │
└───┴──────────────────┴───────────┴─────────────┴──────────────┴─────────────┴────────────┘
  Quality Badges: (Loss) Bit-for-bit Exact  •  (✓✓) Imperceptible  •  (✓) Slight Smoothing  •  (✗) Failed
  Note: Candidates that grew larger were safely discarded; original files retained.
```

### 3. Actionable Command Prompt
```text
╭─ READY TO COMPRESS? ───────────────────────────────────────────────────────────────────╮
│ To apply the recommended strategy (-m lossy -q 80 -f webp) to this folder, run:       │
│                                                                                        │
│ mangadl compress -d 'B:\Hent\tmphent3\308191 A midsummer NTR dream' \                 │
│   -f webp -m lossy -q 80 -B auto -t 8 -w                                               │
╰────────────────────────────────────────────────────────────────────────────────────────╯
```

---

## 7. Color Palette & Hierarchy

Applying standard ANSI / 256-color formatting through `termdash.formatting`:

| Element | Color | Purpose |
| :--- | :--- | :--- |
| **Phase Banner** | Bold Cyan (`\033[1;36m`) | High-level state orientation |
| **Overall Progress Bar** | Green (`\033[32m`) | Global completion indicator |
| **Stage Progress Bar** | Blue / Cyan (`\033[34m`) | Stage completion indicator |
| **Gallery Progress Bar** | Magenta (`\033[35m`) | Sub-task completion indicator |
| **Throughput / Rates** | Yellow / Magenta | Dynamic real-time speed metrics |
| **ETA** | Bright White / Green | Time expectation |
| **Memory Throttled / Warning** | Bright Yellow / Red | Concurrency bottleneck alert |
| **Winner Strategy** | Bold Bright Green (`\033[1;92m`) | Highlight best compression option |
| **Savings (> 25%)** | Green (`\033[32m`) | Substantial savings |
| **Savings (< 0% / Larger)** | Red (`\033[31m`) | Warning / negative efficiency |
| **SSIM Quality (>= 0.990)** | Green | Verified visual transparency |
| **SSIM Quality (< 0.980)** | Yellow / Red | Noticeable compression artifacts |

---

## 8. CLI Arguments & Sampling Usability Simplifications

1. **Sampling Usability & Removing the `-s < galleries` Hard Error:**
   - Currently, if a user specifies `-s 100` on 182 galleries, the program crashes with `Sample 100 cannot cover 182 galleries; use -s 182 or more`.
   - **Fix:** If target $N < \text{total galleries}$, do NOT crash. Instead, draw sample images across galleries using the Neyman variance/size proxy weights (e.g. allocating 1 sample to the top 100 highest-variance/size galleries) with an explicit notice: `Sample 100 drawn from top 100 galleries weighted by size/variance`.
2. **Consolidate Redundant Flags:**
   - Unify `-s <N>`, `-P <PCT>`, and `-S` into a single smart `-s/--sample` flag (`-s 100`, `-s 1%`, `-s auto`).
   - Unify `-q <INT>` and `-Q <LIST>` into `-q/--quality` supporting multiple entries.
   - Unify `-l` and `-D` into `-l [headers|files]`.
   - Remove dead `-o/--output-dir`.

---

## 9. Implementation Checklist

- [ ] **Stage 1 (Responsive Startup, Memory Uncap & Sampling Fix):** Add immediate startup status during snapshot verification, sanitize input paths, lift the 4096 MiB ceiling to host RAM (`-B 16G`, `-B 50%`, `-B auto`), and remove the hard error when `-s` is less than the gallery count.
- [ ] **Stage 2 (Live Extension Stats):** Add real-time format breakdown dictionary and table generator to `InventoryProgress`.
- [ ] **Stage 3 (Worker Pool Diagnostics):** Track per-worker state, elapsed times, and memory throttle events in `CompresserDashboard`.
- [ ] **Stage 4 (Coloring & Visual Hierarchy):** Update `InventoryProgress` and `CompresserDashboard` with colored phase banners and status indicators.
- [ ] **Stage 5 (Executive Summary & Report):** Implement winning strategy hero callout, whole-library extrapolation, fidelity badges, and copy-paste CLI prompt.
- [ ] **Stage 6 (Verification):** Test on mock directory and verify clean terminal redraws on Windows PowerShell.

