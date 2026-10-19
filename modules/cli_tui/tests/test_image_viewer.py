from __future__ import annotations

from pathlib import Path

from cli_tui.image_viewer import (
    ImageViewerState,
    calculate_fit_dimensions,
    launch_image_viewer,
)
from cli_tui.preview_set import PreviewItem, PreviewSet, PreviewVariant


def _create_mock_preview_set() -> PreviewSet:
    var1 = PreviewVariant(
        recipe="WebP lossy 85",
        path=Path("sample_01_q85.webp"),
        size_bytes=1000,
        original_size_bytes=2000,
        format="webp",
        quality=85,
    )
    var2 = PreviewVariant(
        recipe="WebP lossy 70",
        path=Path("sample_01_q70.webp"),
        size_bytes=800,
        original_size_bytes=2000,
        format="webp",
        quality=70,
    )
    var3 = PreviewVariant(
        recipe="AVIF lossy 85",
        path=Path("sample_01_avif85.avif"),
        size_bytes=900,
        original_size_bytes=2000,
        format="avif",
        quality=85,
    )
    item1 = PreviewItem(
        source_path=Path("sample_01.png"),
        size_bytes=2000,
        variants=[var1, var2, var3],
    )

    item2 = PreviewItem(
        source_path=Path("sample_02.png"),
        size_bytes=3000,
        variants=[var1],
    )
    return PreviewSet([item1, item2])


def test_viewer_state_cycling_and_keys():
    ps = _create_mock_preview_set()
    state = ImageViewerState(ps)

    assert state.current_item.source_path == Path("sample_01.png")
    assert state.current_variant.recipe == "WebP lossy 85"
    assert state.is_zoomed_1_to_1 is False
    assert state.is_closed is False

    # Right arrow: next variant
    state.handle_key("Right")
    assert state.current_variant.recipe == "WebP lossy 70"

    # Right arrow again: next variant
    state.handle_key("Right")
    assert state.current_variant.recipe == "AVIF lossy 85"

    # Left arrow: previous variant
    state.handle_key("Left")
    assert state.current_variant.recipe == "WebP lossy 70"

    # Down arrow: next image
    state.handle_key("Down")
    assert state.current_item.source_path == Path("sample_02.png")

    # Up arrow: previous image
    state.handle_key("Up")
    assert state.current_item.source_path == Path("sample_01.png")

    # Space: toggle zoom
    state.handle_key("space")
    assert state.is_zoomed_1_to_1 is True
    state.handle_key("space")
    assert state.is_zoomed_1_to_1 is False

    # q: exit
    state.handle_key("q")
    assert state.is_closed is True


def test_calculate_fit_dimensions():
    # Image 2000x1000 into 1000x800 box -> aspect ratio 2.0 -> 1000x500
    w, h = calculate_fit_dimensions(image_w=2000, image_h=1000, max_w=1000, max_h=800)
    assert w == 1000
    assert h == 500

    # Image 1000x2000 into 800x1000 box -> aspect ratio 0.5 -> 500x1000
    w, h = calculate_fit_dimensions(image_w=1000, image_h=2000, max_w=800, max_h=1000)
    assert w == 500
    assert h == 1000

    # Image smaller than container: scale up or preserve
    w, h = calculate_fit_dimensions(image_w=100, image_h=100, max_w=800, max_h=800)
    assert w == 800
    assert h == 800


def test_launch_image_viewer_empty_set():
    ps = PreviewSet([])
    ret = launch_image_viewer(preview_set=ps)
    assert ret == 0
