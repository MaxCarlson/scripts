"""Live terminal presentation for bounded fixed-design compression estimation."""

from __future__ import annotations

import math
from pathlib import Path
import shutil
import sys
import threading
import time

from termdash.live import LiveBlock
from termdash.table import render_table_panels
from termdash.utils import color_text, fmt_hms

from .estimation_models import EstimationProgress, RecipeEstimate
from .reporting import binary_bytes, clean


class EstimationProgressUI:
    """In-place live terminal progress renderer for estimation."""

    def __init__(
        self,
        target: Path,
        *,
        enabled: bool = True,
        stream=None,
        interactive: bool | None = None,
    ) -> None:
        self.target = target
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = bool(enabled)
        self.block = LiveBlock(stream=self.stream, enabled=self.enabled)
        self.interactive = bool(interactive) if interactive is not None else self.block.interactive
        self._lock = threading.RLock()
        self.start_time = time.monotonic()
        self.last_progress: EstimationProgress | None = None
        self.last_estimates: tuple[RecipeEstimate, ...] = ()

    def on_progress(self, progress: EstimationProgress) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.last_progress = progress
            if progress.estimates:
                self.last_estimates = progress.estimates
            self.block.update(self._lines)

    def _lines(self) -> list[str]:
        with self._lock:
            p = self.last_progress
            if p is None:
                return ["Initializing estimation..."]

            width = shutil.get_terminal_size().columns
            paint = color_text if self.interactive else lambda text, _tone: text

            stage_name = p.stage.upper()
            phase_name = p.phase.replace("_", " ").title()
            title = f"ESTIMATION: {stage_name} · {phase_name}"
            lines = [paint(title, "cyan")]

            elapsed = time.monotonic() - self.start_time
            lines.append(f"Target: {clean(self.target)} · Elapsed: {fmt_hms(elapsed)}")

            counts = (
                f"Sources: {p.completed_sources}/{p.total_sources} · "
                f"New encodes: {p.new_encodes} · "
                f"Cache hits: {p.cache_hits}"
            )
            if p.active_recipe:
                counts += f" · Recipe: {p.active_recipe}"
            lines.append(counts)

            rem_s = f"{p.remaining_seconds:.1f}s" if p.remaining_seconds is not None else "unbounded"
            budget_line = f"Remaining allowance: {p.remaining_trials} encodes · {rem_s}"
            if p.stopping_reason:
                budget_line += f" · Stopping: {paint(p.stopping_reason, 'yellow')}"
            lines.append(budget_line)

            if self.last_estimates:
                lines.append("")
                headers = ("Recipe", "Est. Saved", "Savings %", "StdDev", "Gaps")
                rows = []
                for est in self.last_estimates:
                    saved = (
                        binary_bytes(round(est.estimated_saved_bytes)) if est.estimated_saved_bytes is not None else "—"
                    )
                    pct = f"{est.savings_percent:.1f}%" if est.savings_percent is not None else "—"
                    stddev = (
                        f"±{binary_bytes(round(math.sqrt(est.variance)))}"
                        if est.variance is not None and est.variance >= 0
                        else "—"
                    )
                    gaps = ", ".join(est.gaps) if est.gaps else "none"
                    rows.append((est.recipe_id, saved, pct, stddev, gaps))

                panels = render_table_panels(
                    headers,
                    rows,
                    identity_columns=(0,),
                    max_width=width,
                    alignments=["left", "right", "right", "right", "left"],
                )
                for panel in panels:
                    lines.extend(panel.splitlines())

            return lines

    def close(self) -> None:
        if self.enabled:
            self.block.close()

    def __enter__(self) -> "EstimationProgressUI":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
