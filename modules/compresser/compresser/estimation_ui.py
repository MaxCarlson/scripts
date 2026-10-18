"""Live terminal presentation for bounded fixed-design compression estimation."""

from __future__ import annotations

from collections import deque
import math
from pathlib import Path
import shutil
import sys
import threading
import time

from termdash.live import LiveBlock
from termdash.progress import ProgressBar
from termdash.table import render_table, _truncate_cell
from termdash.utils import color_text, fmt_hms, format_bytes_decimal, format_rate_bps

from .estimation_models import EstimationProgress, RecipeEstimate, RecipeProgressStat
from .reporting import binary_bytes, clean


class EstimationProgressUI:
    """In-place live terminal progress renderer for estimation with rich visual progress and live tables."""

    def __init__(
        self,
        target: Path,
        *,
        enabled: bool = True,
        stream=None,
        interactive: bool | None = None,
        max_width: int | None = None,
        population_total_bytes: int | None = None,
    ) -> None:
        self.target = target
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = bool(enabled)
        self.block = LiveBlock(stream=self.stream, enabled=self.enabled)
        self.interactive = bool(interactive) if interactive is not None else self.block.interactive
        self.max_width = max_width
        self.population_total_bytes = population_total_bytes
        self._lock = threading.RLock()
        self.start_time = time.monotonic()
        self.last_progress: EstimationProgress | None = None
        self.last_estimates: tuple[RecipeEstimate, ...] = ()
        self.samples: deque[tuple[float, int, int]] = deque([(self.start_time, 0, 0)])
        self.total_source_bytes = 0
        self.last_completed = ""
        self.last_render_time = 0.0

    def on_progress(self, progress: EstimationProgress) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            self.last_progress = progress
            if progress.estimates:
                self.last_estimates = progress.estimates
            if progress.total_source_bytes:
                self.total_source_bytes += progress.total_source_bytes
            if progress.last_completed_text:
                self.last_completed = progress.last_completed_text
            if progress.population_total_bytes is not None and self.population_total_bytes is None:
                self.population_total_bytes = progress.population_total_bytes

            self.samples.append((now, progress.completed_sources, self.total_source_bytes))
            while len(self.samples) > 1 and self.samples[0][0] < now - 15.0:
                self.samples.popleft()

            # Responsive throttling for synchronous renders; LiveBlock's background timer
            # handles smooth continuous clock / ETA refreshes between updates.
            if now - self.last_render_time >= 0.08 or (
                progress.total_sources > 0 and progress.completed_sources == progress.total_sources
            ):
                self.block.update(self._lines)
                self.last_render_time = now

    def _effective_width(self) -> int:
        if self.max_width is not None and self.max_width > 0:
            return self.max_width
        try:
            return max(40, shutil.get_terminal_size().columns)
        except Exception:
            return 80

    def _table_style(self) -> str:
        enc = (getattr(self.stream, "encoding", "") or "").lower()
        style = "rule"
        if "utf" not in enc and "65001" not in enc and enc:
            try:
                "┌─┐".encode(enc)
            except (UnicodeEncodeError, LookupError):
                style = "dash"
        return style

    def _render_recipe_stats_table(self, stats: tuple[RecipeProgressStat, ...]) -> list[str]:
        if not stats:
            return []
        rows = []
        for s in stats:
            pct_str = (
                f"-{(s.saved_bytes / s.input_bytes * 100):.1f}%" if s.input_bytes > 0 and s.saved_bytes > 0 else "0.0%"
            )
            if self.population_total_bytes and s.input_bytes > 0 and s.saved_bytes > 0:
                ratio = s.saved_bytes / s.input_bytes
                proj_bytes = round(self.population_total_bytes * ratio)
                proj_str = f"~{format_bytes_decimal(proj_bytes)}"
            else:
                proj_str = "—"

            rows.append(
                [
                    s.recipe_label[:14],
                    f"{s.trials:,}",
                    format_bytes_decimal(s.input_bytes),
                    format_bytes_decimal(s.retained_bytes),
                    pct_str,
                    proj_str,
                ]
            )

        tbl = render_table(
            headers=["Recipe", "Trials", "Sampled", "Retained", "Savings", "Est. Lib"],
            rows=rows,
            alignments=["left", "right", "right", "right", "right", "right"],
            style=self._table_style(),
            padding=1,
        )
        return ["  MEASURED RECIPES & PROJECTED SAVINGS (LIVE)"] + [f"  {line}" for line in tbl.splitlines()]

    def _render_estimates_table(self, estimates: tuple[RecipeEstimate, ...]) -> list[str]:
        if not estimates:
            return []
        rows = []
        for est in estimates:
            saved = binary_bytes(round(est.estimated_saved_bytes)) if est.estimated_saved_bytes is not None else "—"
            pct = f"{est.savings_percent:.1f}%" if est.savings_percent is not None else "—"
            stddev = (
                f"±{binary_bytes(round(math.sqrt(est.variance)))}"
                if est.variance is not None and est.variance >= 0
                else "—"
            )
            gaps = ", ".join(est.gaps) if est.gaps else "none"
            rows.append([est.recipe_id[:16], saved, pct, stddev, gaps])

        tbl = render_table(
            headers=["Recipe", "Est. Saved", "Savings %", "StdDev", "Gaps"],
            rows=rows,
            alignments=["left", "right", "right", "right", "left"],
            style=self._table_style(),
            padding=1,
        )
        return ["  CERTIFIED POPULATION ESTIMATES (LIVE)"] + [f"  {line}" for line in tbl.splitlines()]

    def _lines(self) -> list[str]:
        with self._lock:
            p = self.last_progress
            if p is None:
                return ["Initializing estimation..."]

            now = time.monotonic()
            elapsed = max(0.001, now - self.start_time)
            term_w = self._effective_width()
            paint = color_text if self.interactive else (lambda text, _tone: text)

            # Rolling throughput and ETA
            recent = [(stamp, done, b) for stamp, done, b in tuple(self.samples) if stamp >= now - 15.0]
            if recent and len(recent) > 1 and now - recent[0][0] >= 0.5:
                dt = max(0.001, now - recent[0][0])
                rate_src = max(0.0, (p.completed_sources - recent[0][1]) / dt)
                rate_bytes = max(0.0, (self.total_source_bytes - recent[0][2]) / dt)
            else:
                rate_src = p.completed_sources / elapsed
                rate_bytes = self.total_source_bytes / elapsed

            rem_src = max(0, p.total_sources - p.completed_sources)
            if rate_src > 0.01 and rem_src > 0:
                eta_str = fmt_hms(rem_src / rate_src) + " estimated"
            else:
                eta_str = "unknown"

            stage_name = p.stage.upper()
            phase_name = p.phase.replace("_", " ").title()
            stage_badge = paint(f"ESTIMATION: {stage_name}", "cyan")
            target_str = clean(self.target)
            if len(target_str) > 30:
                target_str = "…" + target_str[-29:]
            header = f"[{stage_badge}] [{phase_name}] {target_str}"
            if p.active_recipe:
                header += f" | active: {paint(p.active_recipe, 'cyan')}"

            # Visual progress bars
            src_bar = ProgressBar("src", max(1, p.total_sources), p.completed_sources, width=28, charset="block")
            src_bar_str = paint(str(src_bar), "cyan")
            src_pct = (p.completed_sources / max(1, p.total_sources)) * 100.0 if p.total_sources > 0 else 0.0

            budget_total = p.budget_total or (p.new_encodes + p.remaining_trials) or 1
            bgt_bar = ProgressBar(
                "bgt",
                max(1, budget_total),
                min(p.new_encodes, max(1, budget_total)),
                width=28,
                charset="block",
            )
            bgt_bar_str = paint(str(bgt_bar), "yellow")
            bgt_pct = (p.new_encodes / max(1, budget_total)) * 100.0

            rem_s = f"{p.remaining_seconds:.1f}s" if p.remaining_seconds is not None else "unbounded"

            current_line = f"Stage:   {src_bar_str} {src_pct:5.1f}% ({p.completed_sources}/{p.total_sources} sources)"
            overall_line = f"Overall: {bgt_bar_str} {bgt_pct:5.1f}% ({p.new_encodes}/{budget_total} budget)"

            clock_line = f"Elapsed: {fmt_hms(elapsed)} | ETA: {paint(eta_str, 'green')} | Rate: {paint(f'{rate_src:.1f} src/s', 'yellow')} ({format_rate_bps(rate_bytes)})"

            budget_line = f"Remaining: {p.remaining_trials} ({rem_s})"
            if p.stopping_reason:
                budget_line += f" · Stopping: {paint(p.stopping_reason, 'yellow')}"

            counts_line = (
                f"Sources: {p.completed_sources}/{p.total_sources} · "
                f"New encodes: {paint(str(p.new_encodes), 'yellow')} · "
                f"Cache hits: {paint(str(p.cache_hits), 'green')} · "
                f"{budget_line}"
            )

            last_line = f"Last completed: {paint(self.last_completed or 'waiting for first trial...', 'bright')}"

            lines = [
                header,
                current_line,
                overall_line,
                clock_line,
                counts_line,
                last_line,
            ]

            # Render live tables:
            # 1. Evaluated recipes table (trials, original bytes, retained bytes, savings, projected library)
            if p.recipe_stats:
                lines.append("")
                lines.extend(self._render_recipe_stats_table(p.recipe_stats))

            # 2. Statistical population savings table (once available)
            if self.last_estimates:
                lines.append("")
                lines.extend(self._render_estimates_table(self.last_estimates))

            return [_truncate_cell(line, term_w) for line in lines]

    def close(self) -> None:
        if self.enabled:
            self.block.close()

    def __enter__(self) -> "EstimationProgressUI":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
