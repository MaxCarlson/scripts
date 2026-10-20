"""
Single-file self-contained HTML report builder for interactive benchmark reports.

Embeds all styling, interactive vanilla JavaScript, and data offline with 0 external dependencies.
Strictly escapes all dynamic content to ensure safe offline viewing.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Optional, Union

from .charts import render_scatter_svg
from .models import ReportData, VariantReportRow


def escape_json_script(data_dict: dict[str, Any]) -> str:
    """Serialize dictionary to JSON safely for embedding in a <script> tag."""
    raw_json = json.dumps(data_dict, ensure_ascii=False)
    # Prevent closing script tag injection
    return raw_json.replace("</", r"\u003c/").replace("<!--", r"\u003c!--")


def generate_html_report(
    data: Union[ReportData, dict[str, Any]],
    output_path: Optional[Union[Path, str]] = None,
) -> str:
    """
    Generate a standalone, offline interactive HTML report.

    Args:
        data: ReportData instance or corresponding dictionary.
        output_path: Optional file path to write HTML output.

    Returns:
        Rendered HTML string.
    """
    if isinstance(data, dict):
        report = ReportData.from_dict(data)
    else:
        report = data

    data_json = escape_json_script(report.to_dict())

    # Generate scatterplot SVG
    scatter_svg = render_scatter_svg(
        report.efficiency_points,
        x_metric="duration_s",
        y_metric="throughput",
    )

    # Calculate summary metrics
    model_ids = {v.variant_id for v in report.variants} | {t.variant_id for t in report.trials.values()}
    for group in report.metadata.get("condition_groups", {}).values():
        model_ids.update(group.get("eligible_variants", {}))
        model_ids.update(group.get("reference_variants", {}))
    for run in report.metadata.get("incompatible_runs", []):
        model_ids.update(t["variant_id"] for t in run.get("trials", []))
    total_models = len(model_ids)
    eligible_variants = [v for v in report.variants if v.is_eligible and v.scored_denominator > 0
                         and v.strict_acceptance_rate is not None]
    unranked_variants = [v for v in report.variants if v.is_eligible and v not in eligible_variants]
    reference_variants = [v for v in report.variants if not v.is_eligible]

    top_winner = eligible_variants[0] if eligible_variants else None
    top_winner_id = top_winner.variant_id if top_winner else "N/A"
    top_winner_rate = (
        f"{top_winner.strict_acceptance_rate * 100:.1f}%"
        if top_winner and top_winner.strict_acceptance_rate is not None
        else "N/A"
    )

    total_trials = sum(v.total_trials for v in report.variants)
    for group in report.metadata.get("condition_groups", {}).values():
        total_trials += sum(v["total_trials"] for v in {**group.get("eligible_variants", {}), **group.get("reference_variants", {})}.values())
    total_trials += sum(len(run.get("trials", [])) for run in report.metadata.get("incompatible_runs", [])
                        if run.get("condition_key") not in report.metadata.get("condition_groups", {}))
    total_scored_denom = sum(v.scored_denominator for v in report.variants)

    # Top throughput
    variants_with_tp = [
        v for v in report.variants if v.throughput_tok_per_s is not None and v.throughput_tok_per_s > 0
    ]
    fastest = max(variants_with_tp, key=lambda v: v.throughput_tok_per_s or 0.0, default=None)
    top_tp_str = f"{fastest.throughput_tok_per_s:.1f} tok/s ({fastest.variant_id})" if fastest else "N/A"

    # Distinct categories in divergence matrix
    categories = sorted({d.category for d in report.divergence_matrix})

    # Render HTML template
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(report.title)} - {html.escape(report.experiment_id)}</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-hover: #24344d;
      --border: #334155;
      --border-light: #475569;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --accent: #38bdf8;
      --accent-hover: #0ea5e9;
      --success: #10b981;
      --success-bg: rgba(16, 185, 129, 0.15);
      --danger: #ef4444;
      --danger-bg: rgba(239, 68, 68, 0.15);
      --warning: #f59e0b;
      --warning-bg: rgba(245, 158, 11, 0.15);
      --mixed: #ec4899;
      --mixed-bg: rgba(236, 72, 153, 0.15);
      --neutral: #64748b;
      --neutral-bg: rgba(100, 116, 139, 0.15);
      --radius: 8px;
      --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2), 0 2px 4px -2px rgba(0, 0, 0, 0.2);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      line-height: 1.5;
      padding: 24px;
    }}

    header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 24px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 16px;
      flex-wrap: wrap;
      gap: 16px;
    }}

    .header-title h1 {{
      font-size: 24px;
      font-weight: 700;
      color: var(--text-main);
      display: flex;
      align-items: center;
      gap: 12px;
    }}

    .header-title .exp-id {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 14px;
      background: var(--card-bg);
      padding: 4px 10px;
      border-radius: 6px;
      border: 1px solid var(--border);
      color: var(--accent);
    }}

    .header-pills {{
      display: flex;
      gap: 8px;
      margin-top: 8px;
      flex-wrap: wrap;
    }}

    .pill {{
      font-size: 12px;
      padding: 3px 8px;
      border-radius: 4px;
      background: var(--card-bg);
      border: 1px solid var(--border);
      color: var(--text-muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .pill strong {{ color: var(--text-main); }}

    /* Tab Navigation */
    .nav-tabs {{
      display: flex;
      gap: 8px;
      margin-bottom: 20px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 8px;
    }}

    .tab-btn {{
      background: transparent;
      border: 1px solid transparent;
      color: var(--text-muted);
      padding: 8px 18px;
      font-size: 14px;
      font-weight: 600;
      border-radius: var(--radius);
      cursor: pointer;
      transition: all 0.15s ease;
    }}

    .tab-btn:hover {{
      color: var(--text-main);
      background: var(--card-bg);
    }}

    .tab-btn.active {{
      background: var(--card-bg);
      color: var(--accent);
      border-color: var(--border);
    }}

    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}

    /* KPI Summary Cards */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}

    .kpi-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px 20px;
      box-shadow: var(--shadow);
    }}

    .kpi-label {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      font-weight: 600;
      margin-bottom: 6px;
    }}

    .kpi-val {{
      font-size: 24px;
      font-weight: 700;
      color: var(--text-main);
    }}

    .kpi-sub {{
      font-size: 12px;
      color: var(--text-dim);
      margin-top: 4px;
    }}

    /* Controls & Filter Bar */
    .filter-bar {{
      display: flex;
      gap: 12px;
      align-items: center;
      margin-bottom: 16px;
      background: var(--card-bg);
      padding: 12px 16px;
      border-radius: var(--radius);
      border: 1px solid var(--border);
      flex-wrap: wrap;
    }}

    .filter-bar input[type="text"],
    .filter-bar select {{
      background: var(--bg);
      border: 1px solid var(--border);
      color: var(--text-main);
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 13px;
      outline: none;
    }}

    .filter-bar input[type="text"]:focus,
    .filter-bar select:focus {{
      border-color: var(--accent);
    }}

    /* Tables */
    .table-container {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow-x: auto;
      margin-bottom: 24px;
      box-shadow: var(--shadow);
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      text-align: left;
    }}

    th {{
      background: #192231;
      padding: 10px 14px;
      font-weight: 600;
      color: var(--text-muted);
      border-bottom: 1px solid var(--border);
      user-select: none;
      white-space: nowrap;
    }}

    th.sortable {{
      cursor: pointer;
    }}

    th.sortable:hover {{
      color: var(--text-main);
      background: #202b3d;
    }}

    th .sort-arrow {{
      font-size: 10px;
      margin-left: 4px;
      opacity: 0.6;
    }}

    td {{
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      color: var(--text-main);
      white-space: nowrap;
    }}

    tr:last-child td {{
      border-bottom: none;
    }}

    tr:hover td {{
      background: var(--card-hover);
    }}

    .rank-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      border-radius: 50%;
      font-weight: 700;
      font-size: 12px;
      background: var(--border);
      color: var(--text-main);
    }}
    .rank-1 {{ background: #eab308; color: #000; }}
    .rank-2 {{ background: #94a3b8; color: #000; }}
    .rank-3 {{ background: #b45309; color: #fff; }}

    /* CI Bar & Percentage */
    .rate-bar-container {{
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 180px;
    }}

    .rate-bar-bg {{
      flex: 1;
      height: 8px;
      background: #0f172a;
      border-radius: 4px;
      overflow: hidden;
      position: relative;
    }}

    .rate-bar-fill {{
      height: 100%;
      background: var(--success);
      border-radius: 4px;
    }}

    .ci-sub {{
      font-size: 11px;
      color: var(--text-dim);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}

    /* Badges */
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}

    .badge-success {{ background: var(--success-bg); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.3); }}
    .badge-danger {{ background: var(--danger-bg); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.3); }}
    .badge-warning {{ background: var(--warning-bg); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.3); }}
    .badge-mixed {{ background: var(--mixed-bg); color: var(--mixed); border: 1px solid rgba(236, 72, 153, 0.3); }}
    .badge-neutral {{ background: var(--neutral-bg); color: var(--neutral); border: 1px solid rgba(100, 116, 139, 0.3); }}

    /* Divergence Matrix Cell */
    .divergence-cell {{
      cursor: pointer;
      text-align: center;
      transition: transform 0.1s ease, box-shadow 0.1s ease;
    }}

    .divergence-cell:hover .badge {{
      filter: brightness(1.2);
      transform: scale(1.05);
      box-shadow: 0 0 8px rgba(56, 189, 248, 0.3);
    }}

    /* Warnings Banner */
    .alert-box {{
      background: rgba(245, 158, 11, 0.1);
      border: 1px solid rgba(245, 158, 11, 0.3);
      border-radius: var(--radius);
      padding: 12px 16px;
      margin-bottom: 20px;
      font-size: 13px;
      color: #fde68a;
    }}
    .alert-box ul {{ margin-left: 20px; margin-top: 6px; }}

    /* Chart Container */
    .chart-wrapper {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      box-shadow: var(--shadow);
      margin-bottom: 24px;
      position: relative;
    }}

    .chart-controls {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      flex-wrap: wrap;
      gap: 12px;
    }}

    .chart-svg {{
      width: 100%;
      height: auto;
      max-height: 480px;
    }}

    .scatter-dot {{
      cursor: pointer;
      transition: r 0.15s ease, filter 0.15s ease;
    }}

    .scatter-dot:hover, .scatter-dot:focus {{
      r: 8px;
      filter: drop-shadow(0 0 6px var(--accent));
      outline: none;
    }}

    /* Tooltip */
    #chart-tooltip {{
      position: absolute;
      display: none;
      background: #090d16;
      border: 1px solid var(--accent);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
      pointer-events: none;
      z-index: 100;
      box-shadow: 0 4px 12px rgba(0,0,0,0.5);
      line-height: 1.4;
    }}

    /* Trial Inspector Drawer / Modal */
    #inspector-backdrop {{
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.7);
      backdrop-filter: blur(2px);
      display: none;
      z-index: 200;
    }}

    #inspector-drawer {{
      position: fixed;
      top: 0; right: 0; bottom: 0;
      width: 680px;
      max-width: 90vw;
      background: #111827;
      border-left: 1px solid var(--border);
      box-shadow: -8px 0 24px rgba(0, 0, 0, 0.5);
      display: flex;
      flex-direction: column;
      z-index: 201;
      transform: translateX(100%);
      transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }}

    #inspector-drawer.open {{
      transform: translateX(0);
    }}

    .drawer-header {{
      padding: 16px 20px;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #182234;
    }}

    .drawer-header h2 {{
      font-size: 16px;
      font-weight: 700;
      color: var(--text-main);
    }}

    .drawer-close {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 22px;
      cursor: pointer;
      line-height: 1;
    }}
    .drawer-close:hover {{ color: var(--danger); }}

    .drawer-tabs {{
      display: flex;
      background: #0f172a;
      border-bottom: 1px solid var(--border);
      padding: 0 16px;
    }}

    .drawer-tab-btn {{
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--text-muted);
      padding: 10px 14px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }}

    .drawer-tab-btn.active {{
      color: var(--accent);
      border-bottom-color: var(--accent);
    }}

    .drawer-content {{
      flex: 1;
      overflow-y: auto;
      padding: 20px;
    }}

    .code-box {{
      background: #090d16;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      color: #e2e8f0;
      white-space: pre-wrap;
      word-break: break-all;
      max-height: 400px;
      overflow-y: auto;
    }}

    .key-value-grid {{
      display: grid;
      grid-template-columns: 160px 1fr;
      gap: 8px 16px;
      font-size: 13px;
      margin-bottom: 16px;
    }}
    .kv-key {{ color: var(--text-muted); }}
    .kv-val {{ color: var(--text-main); font-family: ui-monospace, Menlo, monospace; }}
  </style>
</head>
<body>

  <header>
    <div class="header-title">
      <h1>
        {html.escape(report.title)}
        <span class="exp-id">{html.escape(report.experiment_id)}</span>
      </h1>
      <div class="header-pills">
        <span class="pill">Suite: <strong>{html.escape(report.suite_id)}</strong> (v{html.escape(report.suite_version)})</span>
        <span class="pill">Budget: <strong>{html.escape(report.budget_profile)}</strong></span>
        <span class="pill">Scoring Basis: <strong>{html.escape(report.scoring_basis)}</strong></span>
        <span class="pill">Created: {html.escape(report.created_at)}</span>
      </div>
    </div>
  </header>

  <!-- Navigation Tabs -->
  <nav class="nav-tabs">
    <button class="tab-btn active" onclick="switchTab('leaderboard')">Leaderboard & Rankings</button>
    <button class="tab-btn" onclick="switchTab('divergence')">Task Divergence Matrix</button>
    <button class="tab-btn" onclick="switchTab('efficiency')">Execution Efficiency</button>
    <button class="tab-btn" onclick="switchTab('explorer')">Raw Trial Explorer</button>
  </nav>

  <!-- Tab 1: Leaderboard -->
  <div id="tab-leaderboard" class="tab-panel active">
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Top Ranked Model</div>
        <div class="kpi-val" style="color: var(--accent);">{html.escape(top_winner_id)}</div>
        <div class="kpi-sub">Acceptance: {html.escape(top_winner_rate)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Models Benchmarked</div>
        <div class="kpi-val">{total_models}</div>
        <div class="kpi-sub">{len(eligible_variants)} ranked, {len(unranked_variants)} unranked, {len(reference_variants)} reference</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Scored Trials Denominator</div>
        <div class="kpi-val">{total_scored_denom}</div>
        <div class="kpi-sub">{total_trials} recorded trials</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Peak Generation Speed</div>
        <div class="kpi-val" style="font-size: 20px;">{html.escape(top_tp_str)}</div>
        <div class="kpi-sub">Throughput across successful tasks</div>
      </div>
    </div>

    <!-- Warnings Banner -->
    {"".join('<div class="alert-box"><strong>Incompatibilities / Warnings:</strong><ul>' + "".join(f'<li>{html.escape(w)}</li>' for w in report.warnings) + '</ul></div>' if report.warnings else '')}

    <!-- Filter Bar -->
    <div class="filter-bar">
      <input type="text" id="leaderboard-search" placeholder="Search model or variant..." onkeyup="filterLeaderboard()">
      <span style="font-size: 13px; color: var(--text-muted); margin-left: auto;">
        * Denominator = Passed + Failed + Timed Out. Wilson 95% Confidence Interval.
      </span>
    </div>

    <!-- Canonical Leaderboard Table -->
    <div class="table-container">
      <table id="leaderboard-table">
        <thead>
          <tr>
            <th class="sortable" onclick="sortTable('leaderboard-table', 0)">Rank <span class="sort-arrow">↕</span></th>
            <th class="sortable" onclick="sortTable('leaderboard-table', 1)">Model / Variant <span class="sort-arrow">↕</span></th>
            <th class="sortable" onclick="sortTable('leaderboard-table', 2, 'num')">Strict Acceptance (95% CI) <span class="sort-arrow">↕</span></th>
            <th>Scored Denom (Pass / Fail / Time)</th>
            <th class="sortable" onclick="sortTable('leaderboard-table', 4, 'num')">Infra / Unscored <span class="sort-arrow">↕</span></th>
            <th class="sortable" onclick="sortTable('leaderboard-table', 5, 'num')">Mean Duration <span class="sort-arrow">↕</span></th>
            <th class="sortable" onclick="sortTable('leaderboard-table', 6, 'num')">Throughput <span class="sort-arrow">↕</span></th>
            <th class="sortable" onclick="sortTable('leaderboard-table', 7, 'num')">Reasoning Share <span class="sort-arrow">↕</span></th>
          </tr>
        </thead>
        <tbody>
          {"".join(_render_canonical_rows(eligible_variants)) if eligible_variants else '<tr><td colspan="8">No variants with a defined strict rate.</td></tr>'}
        </tbody>
      </table>
    </div>

    <!-- Reference / Ineligible Variants Table -->
    {_render_unranked_section(unranked_variants)}
    {_render_reference_section(reference_variants)}
    {_render_condition_sections(report.metadata)}
  </div>

  <!-- Tab 2: Task Divergence Matrix -->
  <div id="tab-divergence" class="tab-panel">
    <div class="filter-bar">
      <label for="divergence-cat" style="font-size: 13px; color: var(--text-muted);">Category:</label>
      <select id="divergence-cat" onchange="filterDivergence()">
        <option value="ALL">All Categories</option>
        {"".join(f'<option value="{html.escape(c)}">{html.escape(c)}</option>' for c in categories)}
      </select>
      <input type="text" id="divergence-search" placeholder="Search task ID..." onkeyup="filterDivergence()">
      <span style="font-size: 13px; color: var(--text-muted); margin-left: auto;">
        Click any cell badge to inspect trial logs and verifier output.
      </span>
    </div>

    <div class="table-container">
      <table id="divergence-table">
        <thead>
          <tr>
            <th>Task ID</th>
            <th>Category</th>
            {"".join(f'<th>{html.escape(v.variant_id)}</th>' for v in report.variants)}
          </tr>
        </thead>
        <tbody>
          {"".join(_render_divergence_rows(report.divergence_matrix, report.variants))}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Tab 3: Execution Efficiency -->
  <div id="tab-efficiency" class="tab-panel">
    <div class="chart-wrapper">
      <div class="chart-controls">
        <h2 style="font-size: 16px; font-weight: 700;">Throughput vs Duration Scatterplot</h2>
        <span style="font-size: 12px; color: var(--text-muted);">Hover points for metrics. Click to inspect trial.</span>
      </div>
      <div id="scatter-chart-container">
        {scatter_svg}
      </div>
      <div id="chart-tooltip"></div>
    </div>

    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>Variant</th>
            <th>Throughput (mean tok/s)</th>
            <th>Mean Duration</th>
            <th>Median Duration</th>
            <th>Tokens / Success Task</th>
            <th>Reasoning Token Share</th>
          </tr>
        </thead>
        <tbody>
          {"".join(_render_efficiency_summary_rows(report.variants))}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Tab 4: Trial Explorer -->
  <div id="tab-explorer" class="tab-panel">
    <div class="filter-bar">
      <input type="text" id="explorer-search" placeholder="Search trials by task, variant, or status..." onkeyup="filterExplorer()">
    </div>
    <div class="table-container">
      <table id="explorer-table">
        <thead>
          <tr>
            <th>Trial ID</th>
            <th>Variant</th>
            <th>Task ID</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Total Tokens</th>
            <th>Throughput</th>
            <th>Inspect</th>
          </tr>
        </thead>
        <tbody>
          {"".join(_render_explorer_rows(report.trials.values()))}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Trial Inspector Drawer / Modal -->
  <div id="inspector-backdrop" onclick="closeInspector()"></div>
  <aside id="inspector-drawer" aria-label="Trial Inspector">
    <div class="drawer-header">
      <div>
        <h2>Trial Details</h2>
        <span id="drawer-sub" style="font-size: 12px; color: var(--text-muted); font-family: ui-monospace, Menlo, monospace;"></span>
      </div>
      <button class="drawer-close" onclick="closeInspector()">&times;</button>
    </div>
    <div class="drawer-tabs">
      <button class="drawer-tab-btn active" onclick="switchDrawerTab('logs')">Verification & Output</button>
      <button class="drawer-tab-btn" onclick="switchDrawerTab('telemetry')">Token Telemetry</button>
      <button class="drawer-tab-btn" onclick="switchDrawerTab('scope')">Scope & Safety</button>
      <button class="drawer-tab-btn" onclick="switchDrawerTab('diff')">Patch Diff</button>
    </div>
    <div class="drawer-content">
      <div id="drawer-panel-logs" class="drawer-panel">
        <div class="key-value-grid" id="drawer-kv"></div>
        <div style="font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 6px;">Verifier Logs / Output:</div>
        <div class="code-box" id="drawer-output">None</div>
      </div>
      <div id="drawer-panel-telemetry" class="drawer-panel" style="display: none;">
        <div class="key-value-grid" id="drawer-telemetry-kv"></div>
      </div>
      <div id="drawer-panel-scope" class="drawer-panel" style="display: none;">
        <div class="key-value-grid" id="drawer-scope-kv"></div>
      </div>
      <div id="drawer-panel-diff" class="drawer-panel" style="display: none;">
        <div class="code-box" id="drawer-diff">No diff recorded.</div>
      </div>
    </div>
  </aside>

  <!-- Embedded Report Data JSON -->
  <script id="report-data" type="application/json">
    {data_json}
  </script>

  <!-- Inlined Vanilla JavaScript -->
  <script>
    const reportData = JSON.parse(document.getElementById('report-data').textContent);

    function switchTab(tabId) {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

      const targetBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b =>
        b.getAttribute('onclick') && b.getAttribute('onclick').includes(tabId)
      );
      if (targetBtn) targetBtn.classList.add('active');

      const targetPanel = document.getElementById('tab-' + tabId);
      if (targetPanel) targetPanel.classList.add('active');
    }}

    function filterLeaderboard() {{
      const query = document.getElementById('leaderboard-search').value.toLowerCase();
      const rows = document.querySelectorAll('#leaderboard-table tbody tr');
      rows.forEach(r => {{
        const text = r.textContent.toLowerCase();
        r.style.display = text.includes(query) ? '' : 'none';
      }});
    }}

    function filterDivergence() {{
      const cat = document.getElementById('divergence-cat').value;
      const query = document.getElementById('divergence-search').value.toLowerCase();
      const rows = document.querySelectorAll('#divergence-table tbody tr');
      rows.forEach(r => {{
        const rowCat = r.getAttribute('data-category');
        const rowText = r.textContent.toLowerCase();
        const catMatch = (cat === 'ALL' || rowCat === cat);
        const queryMatch = rowText.includes(query);
        r.style.display = (catMatch && queryMatch) ? '' : 'none';
      }});
    }}

    function filterExplorer() {{
      const query = document.getElementById('explorer-search').value.toLowerCase();
      const rows = document.querySelectorAll('#explorer-table tbody tr');
      rows.forEach(r => {{
        r.style.display = r.textContent.toLowerCase().includes(query) ? '' : 'none';
      }});
    }}

    function sortTable(tableId, colIdx, type = 'str') {{
      const table = document.getElementById(tableId);
      const tbody = table.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const th = table.querySelectorAll('th')[colIdx];
      const isAsc = th.getAttribute('data-asc') !== 'true';

      rows.sort((a, b) => {{
        const aText = a.children[colIdx] ? a.children[colIdx].getAttribute('data-sort') || a.children[colIdx].textContent.trim() : '';
        const bText = b.children[colIdx] ? b.children[colIdx].getAttribute('data-sort') || b.children[colIdx].textContent.trim() : '';
        if (type === 'num') {{
          const aNum = parseFloat(aText) || 0;
          const bNum = parseFloat(bText) || 0;
          return isAsc ? aNum - bNum : bNum - aNum;
        }}
        return isAsc ? aText.localeCompare(bText) : bText.localeCompare(aText);
      }});

      th.setAttribute('data-asc', isAsc ? 'true' : 'false');
      rows.forEach(r => tbody.appendChild(r));
    }}

    /* Tooltip & Scatter Interactions */
    const tooltip = document.getElementById('chart-tooltip');
    const chartContainer = document.getElementById('scatter-chart-container');

    document.querySelectorAll('.scatter-dot').forEach(dot => {{
      dot.addEventListener('mousemove', (e) => {{
        const trialId = dot.getAttribute('data-trial-id');
        const variant = dot.getAttribute('data-variant');
        const task = dot.getAttribute('data-task');
        const status = dot.getAttribute('data-status');
        const dur = dot.getAttribute('data-duration');
        const tok = dot.getAttribute('data-tokens');
        const tp = dot.getAttribute('data-throughput');
        const share = dot.getAttribute('data-reasoning-share');

        tooltip.innerHTML = `
          <strong>${{variant}}</strong> (${{status}})<br>
          Task: ${{task}}<br>
          Duration: ${{dur}} | Throughput: ${{tp}} tok/s<br>
          Tokens: ${{tok}} (Reasoning Share: ${{share}})
        `;
        tooltip.style.display = 'block';

        const rect = chartContainer.getBoundingClientRect();
        tooltip.style.left = (e.clientX - rect.left + 15) + 'px';
        tooltip.style.top = (e.clientY - rect.top + 15) + 'px';
      }});

      dot.addEventListener('mouseleave', () => {{
        tooltip.style.display = 'none';
      }});

      dot.addEventListener('click', () => {{
        const trialId = dot.getAttribute('data-trial-id');
        openTrialInspector(trialId);
      }});
    }});

    /* Trial Inspector Logic */
    function openTrialInspector(trialId) {{
      const trial = reportData.trials[trialId];
      if (!trial) return;

      document.getElementById('drawer-sub').textContent = `${{trial.variant_id}} / ${{trial.task_id}} (${{trial.trial_id}})`;

      const kv = document.getElementById('drawer-kv');
      kv.innerHTML = `
        <div class="kv-key">Status:</div><div class="kv-val"><span class="badge badge-${{getStatusClass(trial.status)}}">${{trial.status}}</span></div>
        <div class="kv-key">Duration:</div><div class="kv-val">${{trial.duration_ms.toFixed(1)}} ms (${{(trial.duration_ms / 1000).toFixed(2)}}s)</div>
        <div class="kv-key">Variant ID:</div><div class="kv-val">${{trial.variant_id}}</div>
        <div class="kv-key">Task ID:</div><div class="kv-val">${{trial.task_id}}</div>
      `;

      document.getElementById('drawer-output').textContent = trial.verifier_output || trial.error_message || '(No verifier output recorded)';

      const tKv = document.getElementById('drawer-telemetry-kv');
      const shareStr = trial.reasoning_token_share !== null && trial.reasoning_token_share !== undefined
        ? (trial.reasoning_token_share * 100).toFixed(1) + '%'
        : 'N/A';
      tKv.innerHTML = `
        <div class="kv-key">Input Tokens:</div><div class="kv-val">${{trial.input_tokens ?? 'N/A'}}</div>
        <div class="kv-key">Output Tokens:</div><div class="kv-val">${{trial.output_tokens ?? 'N/A'}}</div>
        <div class="kv-key">Reasoning Tokens:</div><div class="kv-val">${{trial.reasoning_tokens ?? 'N/A'}}</div>
        <div class="kv-key">Total Tokens:</div><div class="kv-val">${{trial.total_tokens ?? 'N/A'}}</div>
        <div class="kv-key">Peak Context:</div><div class="kv-val">${{trial.peak_context_tokens ?? 'N/A'}}</div>
        <div class="kv-key">Reasoning Share:</div><div class="kv-val">${{shareStr}}</div>
        <div class="kv-key">Throughput:</div><div class="kv-val">${{trial.throughput_tok_per_s ? trial.throughput_tok_per_s.toFixed(1) + ' tok/s' : 'N/A'}}</div>
      `;

      const sKv = document.getElementById('drawer-scope-kv');
      sKv.innerHTML = `
        <div class="kv-key">Scope Compliance:</div><div class="kv-val">${{trial.scope_compliance === true ? '✅ PASS' : (trial.scope_compliance === false ? '❌ VIOLATION' : 'UNKNOWN')}}</div>
        <div class="kv-key">Uncertain Operations:</div><div class="kv-val">${{trial.uncertain_operations === true ? '⚠️ DETECTED' : (trial.uncertain_operations === false ? 'None detected' : 'UNKNOWN')}}</div>
      `;

      const judgments = trial.metadata?.benchmark_details?.judgments || {{}};
      for (const name of ['functional', 'artifact', 'execution', 'budget', 'termination']) {{
        const key = document.createElement('div'); key.className = 'kv-key'; key.textContent = name + ':';
        const value = document.createElement('div'); value.className = 'kv-val';
        value.textContent = ['passed', 'failed', 'unknown'].includes(judgments[name]) ? judgments[name].toUpperCase() : 'UNKNOWN';
        sKv.append(key, value);
      }}
      for (const name of ['first_edit_ms', 'last_edit_ms', 'completion_ms']) {{
        const key = document.createElement('div'); key.className = 'kv-key'; key.textContent = name + ':';
        const value = document.createElement('div'); value.className = 'kv-val';
        const stamp = trial.metrics?.['agent.' + name];
        value.textContent = Number.isFinite(stamp) ? stamp.toFixed(1) + ' ms' : 'UNKNOWN';
        sKv.append(key, value);
      }}

      document.getElementById('drawer-diff').textContent = trial.diff || '(No diff recorded)';

      switchDrawerTab('logs');
      document.getElementById('inspector-backdrop').style.display = 'block';
      document.getElementById('inspector-drawer').classList.add('open');
    }}

    function openCellTrials(trialIdsStr) {{
      const ids = trialIdsStr.split(',').filter(Boolean);
      if (ids.length > 0) {{
        openTrialInspector(ids[0]);
      }}
    }}

    function closeInspector() {{
      document.getElementById('inspector-backdrop').style.display = 'none';
      document.getElementById('inspector-drawer').classList.remove('open');
    }}

    function switchDrawerTab(tabName) {{
      document.querySelectorAll('.drawer-tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.drawer-panel').forEach(p => p.style.display = 'none');

      const btn = Array.from(document.querySelectorAll('.drawer-tab-btn')).find(b =>
        b.getAttribute('onclick') && b.getAttribute('onclick').includes(tabName)
      );
      if (btn) btn.classList.add('active');

      const panel = document.getElementById('drawer-panel-' + tabName);
      if (panel) panel.style.display = 'block';
    }}

    function getStatusClass(status) {{
      if (status === 'passed') return 'success';
      if (status === 'failed') return 'danger';
      if (status === 'timed_out') return 'warning';
      if (status === 'mixed') return 'mixed';
      return 'neutral';
    }}

    document.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape') closeInspector();
    }});
  </script>
</body>
</html>"""

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html_content, encoding="utf-8")

    return html_content


def _render_canonical_rows(variants: list[VariantReportRow]) -> str:
    """Render table rows for eligible variants."""
    rows: list[str] = []
    for rank, v in enumerate(variants, start=1):
        rank_class = f"rank-{rank}" if rank <= 3 else ""
        rate_val = v.strict_acceptance_rate or 0.0
        pct_str = f"{rate_val * 100:.1f}%" if v.strict_acceptance_rate is not None else "N/A"

        ci_str = ""
        if v.ci_lower is not None and v.ci_upper is not None:
            ci_str = f'<div class="ci-sub">[{v.ci_lower * 100:.1f}% &ndash; {v.ci_upper * 100:.1f}%]</div>'

        denom_str = f"{v.scored_denominator} ({v.passed} / {v.failed} / {v.timed_out})"
        infra_str = f"{v.infrastructure_error} / {v.unscored}"
        dur_str = f"{v.duration_mean_ms:.1f} ms" if v.duration_mean_ms is not None else "N/A"
        tp_str = f"{v.throughput_tok_per_s:.1f} tok/s" if v.throughput_tok_per_s is not None else "N/A"
        share_str = f"{v.reasoning_token_share * 100:.1f}%" if v.reasoning_token_share is not None else "N/A"

        rows.append(f"""<tr>
          <td data-sort="{rank}"><span class="rank-badge {rank_class}">{rank}</span></td>
          <td><strong>{html.escape(v.variant_id)}</strong></td>
          <td data-sort="{rate_val}">
            <div class="rate-bar-container">
              <div class="rate-bar-bg">
                <div class="rate-bar-fill" style="width: {rate_val * 100:.1f}%;"></div>
              </div>
              <div>
                <strong>{pct_str}</strong>
                {ci_str}
              </div>
            </div>
          </td>
          <td>{denom_str}</td>
          <td data-sort="{v.infrastructure_error + v.unscored}">{infra_str}</td>
          <td data-sort="{v.duration_mean_ms or 0}">{dur_str}</td>
          <td data-sort="{v.throughput_tok_per_s or 0}">{tp_str}</td>
          <td data-sort="{v.reasoning_token_share or 0}">{share_str}</td>
        </tr>""")
    return "\n".join(rows)


def _render_reference_section(variants: list[VariantReportRow]) -> str:
    """Render reference & ineligible variants section if any exist."""
    if not variants:
        return ""

    rows: list[str] = []
    for v in variants:
        reasons = "; ".join(v.exclusion_reasons) if v.exclusion_reasons else "Experimental budget or ineligible"
        rate_val = v.strict_acceptance_rate or 0.0
        pct_str = f"{rate_val * 100:.1f}%" if v.strict_acceptance_rate is not None else "N/A"
        denom_str = f"{v.scored_denominator} ({v.passed} / {v.failed} / {v.timed_out})"
        dur_str = f"{v.duration_mean_ms:.1f} ms" if v.duration_mean_ms is not None else "N/A"

        rows.append(f"""<tr>
          <td><strong>{html.escape(v.variant_id)}</strong></td>
          <td><span class="badge badge-warning">{html.escape(reasons)}</span></td>
          <td>{pct_str}</td>
          <td>{denom_str}</td>
          <td>{v.infrastructure_error}</td>
          <td>{dur_str}</td>
        </tr>""")

    return f"""
    <div style="margin-top: 32px;">
      <h3 style="font-size: 16px; font-weight: 700; margin-bottom: 8px;">Reference & Ineligible Variants</h3>
      <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">
        These variants were evaluated under experimental budgets or flagged ineligible for canonical comparison. They are presented for reference and do not affect canonical rankings.
      </p>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Variant</th>
              <th>Exclusion Reason</th>
              <th>Strict Acceptance</th>
              <th>Scored Denom</th>
              <th>Infra Errors</th>
              <th>Mean Duration</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows)}
          </tbody>
        </table>
      </div>
    </div>
    """


def _render_divergence_rows(divergence: list[Any], variants: list[VariantReportRow]) -> str:
    """Render divergence matrix rows."""
    rows: list[str] = []
    for d in divergence:
        cells: list[str] = [
            f'<td><code>{html.escape(d.task_id)}</code></td>',
            f'<td><span class="badge badge-neutral">{html.escape(d.category)}</span></td>',
        ]
        for v in variants:
            res = d.results_by_variant.get(v.variant_id)
            if not res or res.total == 0:
                badge = '<span class="badge badge-neutral">UNSCORED</span>'
                trial_ids_str = ""
            elif res.status == "passed":
                badge = f'<span class="badge badge-success">PASS ({res.passed}/{res.total})</span>'
                trial_ids_str = ",".join(res.trial_ids)
            elif res.status == "failed":
                badge = f'<span class="badge badge-danger">FAIL ({res.passed}/{res.total})</span>'
                trial_ids_str = ",".join(res.trial_ids)
            elif res.status == "timed_out":
                badge = '<span class="badge badge-warning">TIMEOUT</span>'
                trial_ids_str = ",".join(res.trial_ids)
            elif res.status == "mixed":
                badge = f'<span class="badge badge-mixed">MIXED ({res.passed}/{res.total})</span>'
                trial_ids_str = ",".join(res.trial_ids)
            elif res.status == "infra_error":
                badge = '<span class="badge badge-neutral">INFRA ERROR</span>'
                trial_ids_str = ",".join(res.trial_ids)
            else:
                badge = f'<span class="badge badge-neutral">{html.escape(res.status.upper())}</span>'
                trial_ids_str = ",".join(res.trial_ids)

            cells.append(
                f'<td class="divergence-cell" onclick="openCellTrials(\'{trial_ids_str}\')">{badge}</td>'
            )

        rows.append(
            f'<tr data-category="{html.escape(d.category)}">{"".join(cells)}</tr>'
        )
    return "\n".join(rows)


def _render_efficiency_summary_rows(variants: list[VariantReportRow]) -> str:
    """Render summary rows for efficiency table."""
    rows: list[str] = []
    for v in variants:
        tp_str = f"{v.throughput_tok_per_s:.1f} tok/s" if v.throughput_tok_per_s is not None else "N/A"
        mean_dur = f"{v.duration_mean_ms:.1f} ms" if v.duration_mean_ms is not None else "N/A"
        med_dur = f"{v.duration_median_ms:.1f} ms" if v.duration_median_ms is not None else "N/A"
        tok_task = f"{v.tokens_per_successful_task:.0f}" if v.tokens_per_successful_task is not None else "N/A"
        share_str = f"{v.reasoning_token_share * 100:.1f}%" if v.reasoning_token_share is not None else "N/A"

        rows.append(f"""<tr>
          <td><strong>{html.escape(v.variant_id)}</strong></td>
          <td>{tp_str}</td>
          <td>{mean_dur}</td>
          <td>{med_dur}</td>
          <td>{tok_task}</td>
          <td>{share_str}</td>
        </tr>""")
    return "\n".join(rows)


def _render_explorer_rows(trials: Any) -> str:
    """Render rows for raw trial explorer table."""
    rows: list[str] = []
    for t in sorted(trials, key=lambda x: (x.variant_id, x.task_id)):
        badge_cls = "badge-neutral"
        if t.status == "passed":
            badge_cls = "badge-success"
        elif t.status == "failed":
            badge_cls = "badge-danger"
        elif t.status == "timed_out":
            badge_cls = "badge-warning"

        dur_s = f"{t.duration_ms / 1000.0:.2f}s"
        tp_s = f"{t.throughput_tok_per_s:.1f} tok/s" if t.throughput_tok_per_s else "N/A"

        rows.append(f"""<tr>
          <td><code>{html.escape(t.trial_id)}</code></td>
          <td>{html.escape(t.variant_id)}</td>
          <td><code>{html.escape(t.task_id)}</code></td>
          <td><span class="badge {badge_cls}">{html.escape(t.status)}</span></td>
          <td>{dur_s}</td>
          <td>{t.total_tokens or 'N/A'}</td>
          <td>{tp_s}</td>
          <td><button class="pill" onclick="openTrialInspector('{html.escape(t.trial_id)}')">Inspect</button></td>
        </tr>""")
    return "\n".join(rows)


def _render_unranked_section(variants: list[VariantReportRow]) -> str:
    if not variants:
        return ""
    rows = []
    for variant in variants:
        functional = variant.metrics.get("agent.functional_pass", {})
        rate = functional.get("mean") if isinstance(functional, dict) else None
        count = functional.get("available_count", 0) if isinstance(functional, dict) else 0
        code = f"{rate:.1%} ({count} measured)" if rate is not None else "UNKNOWN"
        duration = f"{variant.duration_mean_ms:.1f} ms" if variant.duration_mean_ms is not None else "UNKNOWN"
        reasons = "; ".join(variant.configuration.get("diagnostic_reasons", [])) or "No strict scored denominator"
        rows.append(f"<tr><td>{html.escape(variant.variant_id)}</td><td>{variant.total_trials}</td>"
                    f"<td>{variant.infrastructure_error} / {variant.unscored}</td><td>{code}</td><td>{duration}</td>"
                    f"<td>{html.escape(reasons)}</td></tr>")
    return ('<section style="margin-top:32px"><h3>Unranked Diagnostics</h3>'
            '<p>No numerical rank: strict scored denominator is zero. Functional results are independent.</p>'
            '<div class="table-container"><table><thead><tr><th>Variant</th><th>Trials</th><th>Infra / Unscored</th>'
            '<th>Functional rate</th><th>Observed duration</th><th>Reasons</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></div></section>')


def _render_condition_sections(metadata: dict) -> str:
    sections = []
    if metadata.get("comparison_contract"):
        sections.append('<details style="margin-top:32px"><summary>Primary comparison conditions</summary><pre>'
                        + html.escape(json.dumps(metadata["comparison_contract"], indent=2)) + '</pre></details>')
    for key, group in sorted(metadata.get("condition_groups", {}).items()):
        rows = []
        rankings = group.get("canonical_rankings", [])
        for vid, variant in sorted({**group.get("eligible_variants", {}), **group.get("reference_variants", {})}.items()):
            rank = str(rankings.index(vid) + 1) if vid in rankings else "Unranked"
            rate = variant.get("strict_acceptance_rate")
            rate_text = f"{rate:.1%}" if rate is not None else "UNKNOWN"
            rows.append(f"<tr><td>{rank}</td><td>{html.escape(vid)}</td><td>{rate_text}</td>"
                        f"<td>{variant['total_trials']}</td></tr>")
        conditions = group.get("config", {}).get("metadata", {}).get("comparison_contract")
        sections.append(f'<section style="margin-top:32px"><h3>Separate comparison conditions {html.escape(key[:12])}</h3>'
                        '<p>Ranks apply only within this condition group.</p>'
                        f'<details><summary>Recorded conditions</summary><pre>{html.escape(json.dumps(conditions, indent=2))}</pre></details>'
                        '<div class="table-container"><table><thead><tr><th>Group rank</th><th>Variant</th><th>Strict rate</th>'
                        '<th>Trials</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div></section>')
    if metadata.get("incompatible_runs"):
        rows = []
        for run in metadata["incompatible_runs"]:
            for trial in run.get("trials", []):
                functional = trial.get("metrics", {}).get("agent.functional_pass", {}).get("value")
                duration = trial.get("metrics", {}).get("duration.wall_ms", {}).get("value")
                text = f"{trial['variant_id']} / {trial['trial_id']}: {trial['status']}; functional={functional}; observed ms={duration}"
                rows.append('<li>' + html.escape(text) + '</li>')
            rows.append('<li>' + html.escape(run['run_id'] + ': ' + '; '.join(run['reasons'])) + '</li>')
        sections.append('<section style="margin-top:32px"><h3>Incompatible / Unknown-condition Diagnostics</h3><ul>'
                        + ''.join(rows) + '</ul></section>')
    return ''.join(sections)
