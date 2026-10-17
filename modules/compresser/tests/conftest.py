from __future__ import annotations

import pytest
from pathlib import Path
from PIL import Image


@pytest.fixture
def sample_images_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with various sample images."""
    img_dir = tmp_path / "manga_sample"
    img_dir.mkdir()

    # 1. Normal color JPEG
    im_color = Image.new("RGB", (200, 300), color=(180, 100, 50))
    im_color.save(img_dir / "001.jpg", format="JPEG", quality=85)

    # 2. Grayscale line-art JPEG
    im_gray = Image.new("L", (200, 300), color=240)
    im_gray.save(img_dir / "002.jpg", format="JPEG", quality=85)

    # 3. WebP image
    im_webp = Image.new("RGB", (200, 300), color=(50, 100, 180))
    im_webp.save(img_dir / "003.webp", format="WEBP", quality=80)

    # 4. PNG image
    im_png = Image.new("RGB", (200, 300), color=(100, 200, 100))
    im_png.save(img_dir / "004.png", format="PNG")

    # 5. Non-image sidecars
    (img_dir / "info.json").write_text('{"title": "Test Manga"}', encoding="utf-8")
    (img_dir / ".mangadl-source.json").write_text('{"url": "https://example.com"}', encoding="utf-8")

    return img_dir
