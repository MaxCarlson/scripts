# interactive_reports

Standalone, reusable reporting package providing portable offline HTML visualization, task divergence matrices, execution efficiency scatterplots, and trial inspection across benchmarking and experiment domains.

## Features

- **100% Offline & Portable:** Inlined styles and scripts; zero external CDN dependencies; operates cleanly under `file://` protocols.
- **Strict Escaping & Safe Injection:** Rigorous HTML escaping on all raw model and execution outputs.
- **Tabbed Modern UI:**
  - **Overview & Leaderboard:** Canonical rankings with Wilson 95% confidence intervals, separate reference comparisons, interactive filter bar, and sortable columns.
  - **Task Divergence Matrix:** High-density task vs variant outcome grid with color-coded badges and clickable cells.
  - **Execution Efficiency Analytics:** Interactive SVG scatterplots (Duration vs Tokens vs Throughput) with hover tooltips and trial links.
  - **Trial Inspector Drawer:** Instant drill-down showing verifier logs, diffs, token telemetry, and scope compliance.
- **Generic Architecture:** Reusable across LLM benchmarking, compression, GPU kernel tuning, and subprocess benchmarking. Zero mandatory dependencies outside the Python standard library.
