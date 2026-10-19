"""
Execution efficiency analytics and inline SVG scatterplot generator.

Provides domain-agnostic calculations for throughput, token consumption, reasoning token share,
and generates self-contained inline SVG visualizations.
"""

from __future__ import annotations

import html
from typing import Sequence

from .models import EfficiencyPoint, TrialDetail

# High-contrast color palette for variants
PALETTE = [
    "#3b82f6",  # blue
    "#10b981",  # emerald
    "#f59e0b",  # amber
    "#ec4899",  # pink
    "#8b5cf6",  # purple
    "#06b6d4",  # cyan
    "#f97316",  # orange
    "#14b8a6",  # teal
    "#6366f1",  # indigo
    "#84cc16",  # lime
]


def build_efficiency_points(trials: Sequence[TrialDetail]) -> list[EfficiencyPoint]:
    """Extract EfficiencyPoint data from a collection of TrialDetail records."""
    points: list[EfficiencyPoint] = []
    for t in trials:
        total_tok = t.total_tokens
        if total_tok is None:
            inp = t.input_tokens or 0
            out = t.output_tokens or 0
            total_tok = inp + out

        throughput = t.throughput_tok_per_s
        if throughput is None and t.duration_ms > 0 and t.output_tokens:
            throughput = round(t.output_tokens / (t.duration_ms / 1000.0), 2)

        share = t.reasoning_token_share
        if share is None and t.output_tokens and t.reasoning_tokens is not None:
            share = round(t.reasoning_tokens / t.output_tokens, 4)

        points.append(
            EfficiencyPoint(
                trial_id=t.trial_id,
                variant_id=t.variant_id,
                task_id=t.task_id,
                status=t.status,
                strict_pass=(t.status == "passed"),
                duration_ms=t.duration_ms,
                total_tokens=total_tok,
                throughput_tok_per_s=throughput,
                reasoning_token_share=share,
            )
        )
    return points


def render_scatter_svg(
    points: Sequence[EfficiencyPoint],
    x_metric: str = "duration_s",
    y_metric: str = "throughput",
    width: int = 800,
    height: int = 420,
) -> str:
    """
    Render an inline, interactive-ready SVG scatterplot.

    Args:
        points: Data points to plot.
        x_metric: 'duration_s' (duration in seconds) or 'tokens' (total tokens).
        y_metric: 'throughput' (tok/s) or 'tokens' (total tokens).
        width: SVG view width.
        height: SVG view height.

    Returns:
        String of XML SVG elements with data-* attributes for client-side tooltips.
    """
    if not points:
        return (
            f'<svg viewBox="0 0 {width} {height}" class="chart-svg" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<text x="{width // 2}" y="{height // 2}" text-anchor="middle" '
            f'fill="#94a3b8" font-size="14">No efficiency data available</text></svg>'
        )

    # Margins
    margin_top = 30
    margin_right = 160
    margin_bottom = 60
    margin_left = 70

    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    # Extract distinct variants and assign colors
    variants = sorted({p.variant_id for p in points})
    variant_colors = {v: PALETTE[i % len(PALETTE)] for i, v in enumerate(variants)}

    # Determine X values
    def get_x(p: EfficiencyPoint) -> float:
        if x_metric == "tokens":
            return float(p.total_tokens)
        return float(p.duration_ms) / 1000.0  # seconds

    # Determine Y values
    def get_y(p: EfficiencyPoint) -> float:
        if y_metric == "tokens":
            return float(p.total_tokens)
        return float(p.throughput_tok_per_s or 0.0)

    x_vals = [get_x(p) for p in points]
    y_vals = [get_y(p) for p in points]

    min_x = 0.0
    max_x = max(max(x_vals, default=10.0), 1.0)
    # Give some headroom
    max_x = max_x * 1.1

    min_y = 0.0
    max_y = max(max(y_vals, default=50.0), 10.0)
    max_y = max_y * 1.1

    def scale_x(v: float) -> float:
        if max_x <= min_x:
            return margin_left
        return margin_left + ((v - min_x) / (max_x - min_x)) * plot_w

    def scale_y(v: float) -> float:
        if max_y <= min_y:
            return margin_top + plot_h
        # SVG Y is inverted (0 at top)
        return margin_top + plot_h - ((v - min_y) / (max_y - min_y)) * plot_h

    svg_parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Execution Efficiency Scatterplot">'
    ]

    # Grid lines & ticks (4 horizontal, 5 vertical)
    # Horizontal grid lines
    num_y_ticks = 4
    for i in range(num_y_ticks + 1):
        tick_val = min_y + (i / num_y_ticks) * (max_y - min_y)
        y_pos = scale_y(tick_val)
        svg_parts.append(
            f'<line x1="{margin_left}" y1="{y_pos:.1f}" x2="{margin_left + plot_w}" y2="{y_pos:.1f}" '
            f'stroke="#334155" stroke-dasharray="3,3" stroke-width="1" />'
        )
        label_text = f"{tick_val:.0f}" if tick_val >= 10 else f"{tick_val:.1f}"
        svg_parts.append(
            f'<text x="{margin_left - 10}" y="{y_pos + 4:.1f}" text-anchor="end" '
            f'fill="#94a3b8" font-size="11">{label_text}</text>'
        )

    # Vertical grid lines
    num_x_ticks = 5
    for i in range(num_x_ticks + 1):
        tick_val = min_x + (i / num_x_ticks) * (max_x - min_x)
        x_pos = scale_x(tick_val)
        svg_parts.append(
            f'<line x1="{x_pos:.1f}" y1="{margin_top}" x2="{x_pos:.1f}" y2="{margin_top + plot_h}" '
            f'stroke="#334155" stroke-dasharray="3,3" stroke-width="1" />'
        )
        label_text = f"{tick_val:.1f}s" if x_metric == "duration_s" else f"{int(tick_val)}"
        svg_parts.append(
            f'<text x="{x_pos:.1f}" y="{margin_top + plot_h + 20}" text-anchor="middle" '
            f'fill="#94a3b8" font-size="11">{label_text}</text>'
        )

    # Axes
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" '
        f'y2="{margin_top + plot_h}" stroke="#64748b" stroke-width="1.5" />'
    )
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" '
        f'y2="{margin_top + plot_h}" stroke="#64748b" stroke-width="1.5" />'
    )

    # Axis Labels
    x_title = "Duration (seconds)" if x_metric == "duration_s" else "Total Tokens"
    y_title = "Throughput (tokens / second)" if y_metric == "throughput" else "Total Tokens"

    svg_parts.append(
        f'<text x="{margin_left + plot_w // 2}" y="{margin_top + plot_h + 46}" '
        f'text-anchor="middle" fill="#cbd5e1" font-size="12" font-weight="600">{x_title}</text>'
    )
    svg_parts.append(
        f'<text x="20" y="{margin_top + plot_h // 2}" text-anchor="middle" '
        f'fill="#cbd5e1" font-size="12" font-weight="600" '
        f'transform="rotate(-90 20 {margin_top + plot_h // 2})">{y_title}</text>'
    )

    # Legend
    leg_x = margin_left + plot_w + 20
    leg_y = margin_top + 10
    svg_parts.append(
        f'<text x="{leg_x}" y="{leg_y}" fill="#f8fafc" font-size="12" font-weight="700">Models</text>'
    )
    for i, v in enumerate(variants):
        cur_y = leg_y + 20 + i * 22
        col = variant_colors[v]
        v_label = v if len(v) <= 15 else v[:14] + "…"
        svg_parts.append(
            f'<circle cx="{leg_x + 6}" cy="{cur_y - 4}" r="5" fill="{col}" />'
        )
        svg_parts.append(
            f'<text x="{leg_x + 18}" y="{cur_y}" fill="#cbd5e1" font-size="11">{html.escape(v_label)}</text>'
        )

    # Status Legend below models
    status_leg_y = leg_y + 25 + len(variants) * 22
    svg_parts.append(
        f'<text x="{leg_x}" y="{status_leg_y}" fill="#f8fafc" font-size="11" font-weight="600">Status</text>'
    )
    svg_parts.append(
        f'<circle cx="{leg_x + 6}" cy="{status_leg_y + 16}" r="5" fill="#10b981" />'
        f'<text x="{leg_x + 18}" y="{status_leg_y + 20}" fill="#94a3b8" font-size="10">Passed</text>'
    )
    svg_parts.append(
        f'<circle cx="{leg_x + 6}" cy="{status_leg_y + 36}" r="5" fill="#ef4444" />'
        f'<text x="{leg_x + 18}" y="{status_leg_y + 40}" fill="#94a3b8" font-size="10">Failed/Timeout</text>'
    )

    # Render data points
    for p in points:
        px = scale_x(get_x(p))
        py = scale_y(get_y(p))
        v_col = variant_colors.get(p.variant_id, "#38bdf8")

        # Visual differentiation: stroke color indicates pass/fail
        stroke_col = "#10b981" if p.strict_pass else "#ef4444"
        stroke_w = "2" if not p.strict_pass else "1"
        r = 6 if p.strict_pass else 5

        # Safe data attributes for tooltip and trial inspector modal
        dur_s = p.duration_ms / 1000.0
        tok_s = f"{p.throughput_tok_per_s:.1f}" if p.throughput_tok_per_s else "N/A"
        share_s = (
            f"{p.reasoning_token_share * 100:.1f}%"
            if p.reasoning_token_share is not None
            else "N/A"
        )

        svg_parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{r}" fill="{v_col}" '
            f'stroke="{stroke_col}" stroke-width="{stroke_w}" class="scatter-dot" '
            f'data-trial-id="{html.escape(p.trial_id)}" '
            f'data-variant="{html.escape(p.variant_id)}" '
            f'data-task="{html.escape(p.task_id)}" '
            f'data-status="{html.escape(p.status)}" '
            f'data-duration="{dur_s:.2f}s" '
            f'data-tokens="{p.total_tokens}" '
            f'data-throughput="{tok_s}" '
            f'data-reasoning-share="{share_s}" '
            f'tabindex="0" />'
        )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)
