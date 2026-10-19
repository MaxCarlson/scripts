from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import List, Optional, Sequence


@dataclass(slots=True)
class PreviewVariant:
    recipe: str
    path: Path
    size_bytes: int
    original_size_bytes: int
    format: str
    quality: Optional[int] = None
    mode: str = "lossy"

    @property
    def savings_percent(self) -> float:
        if self.original_size_bytes <= 0:
            return 0.0
        return round(
            ((self.original_size_bytes - self.size_bytes) / self.original_size_bytes)
            * 100.0,
            1,
        )


@dataclass(slots=True)
class PreviewItem:
    source_path: Path
    size_bytes: int
    variants: List[PreviewVariant] = field(default_factory=list)


class PreviewSet:
    """Manages an ordered collection of preview items and variant selections."""

    def __init__(self, items: Sequence[PreviewItem]) -> None:
        self.items = list(items)
        self.item_index: int = 0
        self.variant_index: int = 0

    @property
    def current_item(self) -> Optional[PreviewItem]:
        if not self.items:
            return None
        return self.items[self.item_index]

    @property
    def current_variant(self) -> Optional[PreviewVariant]:
        item = self.current_item
        if not item or not item.variants:
            return None
        safe_idx = self.variant_index % len(item.variants)
        return item.variants[safe_idx]

    def next_image(self) -> None:
        if self.items:
            self.item_index = (self.item_index + 1) % len(self.items)

    def prev_image(self) -> None:
        if self.items:
            self.item_index = (self.item_index - 1 + len(self.items)) % len(self.items)

    def next_variant(self) -> None:
        item = self.current_item
        if item and item.variants:
            self.variant_index = (self.variant_index + 1) % len(item.variants)

    def prev_variant(self) -> None:
        item = self.current_item
        if item and item.variants:
            self.variant_index = (self.variant_index - 1 + len(item.variants)) % len(
                item.variants
            )


_CANONICAL_FORMAT_NAMES = {
    "webp": "WebP",
    "jpeg": "JPEG",
    "jpg": "JPEG",
    "avif": "AVIF",
    "png": "PNG",
    "auto": "AUTO",
}


def _format_recipe_name(name: str, fmt: str, mode: str, quality: Optional[int]) -> str:
    fmt_lower = fmt.lower() if fmt else ""
    fmt_display = _CANONICAL_FORMAT_NAMES.get(
        fmt_lower, fmt.upper() if fmt else "UNKNOWN"
    )
    if mode == "lossless":
        return f"{fmt_display} lossless"
    if quality is not None:
        return f"{fmt_display} {mode} {quality}"
    return f"{fmt_display} {mode}"


def scan_preview_directory(directory: Path | str) -> PreviewSet:
    """Scan a target or workspace directory and return a populated PreviewSet."""
    path = Path(directory).expanduser().resolve()

    manifest_path: Optional[Path] = None

    if path.is_file() and path.name == "manifest.json":
        manifest_path = path
    elif (path / "manifest.json").is_file():
        manifest_path = path / "manifest.json"
    else:
        # Check standard locations: <dir>/.mangadl/previews, <dir>/previews, or search subdirs
        search_roots = [
            path / ".mangadl" / "previews",
            path / "previews",
            path,
        ]
        candidate_runs: List[Path] = []
        for s_root in search_roots:
            if s_root.is_dir():
                for sub in s_root.iterdir():
                    if sub.is_dir() and (sub / "manifest.json").is_file():
                        candidate_runs.append(sub / "manifest.json")

        if candidate_runs:
            # Sort by modification time, newest first
            candidate_runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            manifest_path = candidate_runs[0]

    if manifest_path and manifest_path.is_file():
        return _load_from_manifest(manifest_path)

    # Fallback: scan loose image files if no manifest found
    return _scan_loose_images(path)


def _load_from_manifest(manifest_path: Path) -> PreviewSet:
    run_dir = manifest_path.parent
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return PreviewSet([])

    items: List[PreviewItem] = []
    for img_entry in data.get("images", []):
        source_str = img_entry.get("source", "")
        source_path = Path(source_str)
        if not source_path.is_absolute() and not source_path.exists():
            source_path = run_dir / source_path

        orig_size = 0
        if source_path.exists():
            orig_size = source_path.stat().st_size

        variants: List[PreviewVariant] = []
        for var in img_entry.get("variants", []):
            out_str = var.get("output", "")
            out_path = Path(out_str)
            if not out_path.is_absolute() and not out_path.exists():
                out_path = run_dir / out_path

            var_fmt = str(var.get("format", "webp"))
            var_mode = str(var.get("mode", "lossy"))
            var_q = var.get("quality")
            var_size = var.get("bytes")
            if var_size is None and out_path.exists():
                var_size = out_path.stat().st_size
            var_size = int(var_size or 0)

            orig_bytes = var.get("original_bytes", orig_size)

            recipe_name = _format_recipe_name(
                var.get("name", ""), var_fmt, var_mode, var_q
            )
            variants.append(
                PreviewVariant(
                    recipe=recipe_name,
                    path=out_path,
                    size_bytes=var_size,
                    original_size_bytes=int(orig_bytes or 0),
                    format=var_fmt,
                    quality=var_q,
                    mode=var_mode,
                )
            )

        items.append(
            PreviewItem(
                source_path=source_path,
                size_bytes=orig_size,
                variants=variants,
            )
        )

    return PreviewSet(items)


def _scan_loose_images(path: Path) -> PreviewSet:
    if not path.is_dir():
        return PreviewSet([])

    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".avif"}
    all_images = [
        p for p in path.iterdir() if p.is_file() and p.suffix.lower() in image_exts
    ]
    if not all_images:
        return PreviewSet([])

    items = [
        PreviewItem(
            source_path=img,
            size_bytes=img.stat().st_size,
            variants=[
                PreviewVariant(
                    recipe=f"{img.suffix.lstrip('.').upper()}",
                    path=img,
                    size_bytes=img.stat().st_size,
                    original_size_bytes=img.stat().st_size,
                    format=img.suffix.lstrip(".").lower(),
                )
            ],
        )
        for img in sorted(all_images)
    ]
    return PreviewSet(items)
