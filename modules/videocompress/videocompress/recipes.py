"""
Standard encoding recipes and resolution helpers for videocompress.
Follows INTEGRATION_CONTRACTS.md §2 and MEDIA_SAFETY_CONTRACT.md §1.
"""

from __future__ import annotations

from typing import Mapping

from .contracts import VideoRecipe

STANDARD_RECIPES: dict[str, VideoRecipe] = {
    "av1_nvenc_cq30": VideoRecipe(
        recipe_id="av1_nvenc_cq30",
        codec="av1",
        encoder="av1_nvenc",
        preset="p6",
        rate_control_mode="cq",
        rate_control_value=30.0,
        container="matroska",
        pix_fmt="yuv420p10le",
        bit_depth=10,
        audio_policy="copy",
        subtitle_policy="copy",
        attachment_policy="copy",
        metadata_policy="copy",
    ),
    "av1_nvenc_cq34": VideoRecipe(
        recipe_id="av1_nvenc_cq34",
        codec="av1",
        encoder="av1_nvenc",
        preset="p6",
        rate_control_mode="cq",
        rate_control_value=34.0,
        container="matroska",
        pix_fmt="yuv420p10le",
        bit_depth=10,
        audio_policy="copy",
        subtitle_policy="copy",
        attachment_policy="copy",
        metadata_policy="copy",
    ),
    "hevc_nvenc_cq28": VideoRecipe(
        recipe_id="hevc_nvenc_cq28",
        codec="hevc",
        encoder="hevc_nvenc",
        preset="p6",
        rate_control_mode="cq",
        rate_control_value=28.0,
        container="matroska",
        pix_fmt="yuv420p10le",
        bit_depth=10,
        audio_policy="copy",
        subtitle_policy="copy",
        attachment_policy="copy",
        metadata_policy="copy",
    ),
    "h264_nvenc_cq24": VideoRecipe(
        recipe_id="h264_nvenc_cq24",
        codec="h264",
        encoder="h264_nvenc",
        preset="p6",
        rate_control_mode="cq",
        rate_control_value=24.0,
        container="matroska",
        pix_fmt="yuv420p",
        bit_depth=8,
        audio_policy="copy",
        subtitle_policy="copy",
        attachment_policy="copy",
        metadata_policy="copy",
    ),
}

DEFAULT_RECIPE_ID = "av1_nvenc_cq30"


def get_recipe(name_or_id: str | None = None) -> VideoRecipe:
    """
    Retrieve a standard recipe by ID or return the default.
    Raises KeyError if the recipe is unknown.
    """
    key = (name_or_id or DEFAULT_RECIPE_ID).strip()
    if key in STANDARD_RECIPES:
        return STANDARD_RECIPES[key]
    raise KeyError(f"Unknown recipe '{key}'. Available recipes: {', '.join(sorted(STANDARD_RECIPES.keys()))}")


def list_standard_recipes() -> tuple[VideoRecipe, ...]:
    """Return all standard recipes in canonical order."""
    return tuple(STANDARD_RECIPES[k] for k in sorted(STANDARD_RECIPES.keys()))
