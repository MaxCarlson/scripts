"""
videocompress: Estimation-first media-aware video compression, analysis,
and preservation backend for scripts.
"""

__version__ = "0.1.0"

from .contracts import (
    CompressionReport,
    EligibilityDecision,
    Prediction,
    SamplingWindow,
    SourceIdentity,
    TrialObservation,
    VideoApplyJob,
    VideoAsset,
    VideoEstimationPlan,
    VideoRecipe,
    VideoStream,
)

__all__ = [
    "__version__",
    "CompressionReport",
    "EligibilityDecision",
    "Prediction",
    "SamplingWindow",
    "SourceIdentity",
    "TrialObservation",
    "VideoApplyJob",
    "VideoAsset",
    "VideoEstimationPlan",
    "VideoRecipe",
    "VideoStream",
]
