"""
interactive_reports — Standalone, offline interactive HTML reporting library.

Provides modern tabbed visual reports, task divergence matrices, execution efficiency scatterplots,
and portable trial inspection across benchmarking systems.
"""

from .adapter import convert_trial_to_detail, from_experiment_comparison
from .builder import generate_html_report
from .charts import build_efficiency_points, render_scatter_svg
from .divergence import build_task_divergence_matrix, compute_task_cell_status
from .models import (
    EfficiencyPoint,
    ReportData,
    TaskDivergenceRow,
    TaskVariantResult,
    TrialDetail,
    VariantReportRow,
)

__all__ = [
    "EfficiencyPoint",
    "ReportData",
    "TaskDivergenceRow",
    "TaskVariantResult",
    "TrialDetail",
    "VariantReportRow",
    "build_efficiency_points",
    "build_task_divergence_matrix",
    "compute_task_cell_status",
    "convert_trial_to_detail",
    "from_experiment_comparison",
    "generate_html_report",
    "render_scatter_svg",
]
