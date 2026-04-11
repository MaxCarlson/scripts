#!/usr/bin/env python3
"""
Recursively convert image files to WebP or convert WebP files to JPG.

By default, this script writes converted files next to the originals and keeps
the source files intact. It can also mirror the directory tree into a separate
output root, overwrite existing targets, and optionally delete the original
files after a successful conversion.

Examples:
    python convert_images_recursive.py -i ./media -m to-webp
    python convert_images_recursive.py -i ./media -m to-webp -q 90 -l
    python convert_images_recursive.py -i ./media -m to-jpg -o ./converted
    python convert_images_recursive.py -i ./media -m to-jpg -x -b "#FFFFFF"
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from PIL import Image, ImageColor, UnidentifiedImageError

SUPPORTED_TO_WEBP_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
}
SUPPORTED_TO_JPG_SUFFIXES = {
    ".webp",
}
JPEG_SUFFIX = ".jpg"
WEBP_SUFFIX = ".webp"


@dataclass(frozen=True)
class ConversionConfig:
    input_root: Path
    output_root: Path | None
    mode: str
    quality: int
    lossless: bool
    overwrite: bool
    delete_originals: bool
    dry_run: bool
    verbose: bool
    workers: int
    background_color: tuple[int, int, int]


@dataclass(frozen=True)
class ConversionTask:
    source_path: Path
    relative_source_path: Path
    target_path: Path


@dataclass(frozen=True)
class ConversionResult:
    source_path: Path
    target_path: Path
    status: str
    message: str = ""


class ConversionError(RuntimeError):
    """Raised when a conversion operation fails."""


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recursively convert images to WebP or convert WebP images to JPG. "
            "By default, converted files are written next to the originals."
        )
    )
    parser.add_argument(
        "-i",
        "--input-root",
        required=True,
        help="Root directory to scan recursively for input images.",
    )
    parser.add_argument(
        "-o",
        "--output-root",
        default=None,
        help=(
            "Optional output root. When omitted, converted files are written next "
            "to the originals. When provided, the directory tree is mirrored under "
            "this location."
        ),
    )
    parser.add_argument(
        "-m",
        "--mode",
        required=True,
        choices=("to-webp", "to-jpg"),
        help="Conversion direction: 'to-webp' or 'to-jpg'.",
    )
    parser.add_argument(
        "-q",
        "--quality",
        type=int,
        default=92,
        help="Target quality from 0 to 100. Default: 92.",
    )
    parser.add_argument(
        "-l",
        "--lossless",
        action="store_true",
        help="Use lossless WebP when mode is to-webp.",
    )
    parser.add_argument(
        "-w",
        "--overwrite",
        action="store_true",
        help="Overwrite existing target files.",
    )
    parser.add_argument(
        "-x",
        "--delete-originals",
        action="store_true",
        help="Delete each source file after a successful conversion.",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be converted without writing any files.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print detailed progress information.",
    )
    parser.add_argument(
        "-k",
        "--workers",
        type=int,
        default=max(1, min(32, (os.cpu_count() or 1) + 4)),
        help="Number of worker threads to use. Default: a sensible CPU-based value.",
    )
    parser.add_argument(
        "-b",
        "--background-color",
        default="#FFFFFF",
        help=(
            "Background color used when converting transparent images to JPG. "
            "Accepts values like '#FFFFFF' or 'white'."
        ),
    )
    return parser


def validate_arguments(args: argparse.Namespace) -> None:
    if not 0 <= args.quality <= 100:
        raise ValueError("--quality must be between 0 and 100.")
    if args.workers < 1:
        raise ValueError("--workers must be at least 1.")
    if args.lossless and args.mode != "to-webp":
        raise ValueError("--lossless can only be used with --mode to-webp.")


def parse_background_color(color_text: str) -> tuple[int, int, int]:
    parsed = ImageColor.getrgb(color_text)
    if len(parsed) != 3:
        raise ValueError(f"Background color must resolve to RGB, got: {color_text}")
    return parsed


def build_config(args: argparse.Namespace) -> ConversionConfig:
    input_root = Path(args.input_root).expanduser().resolve()
    output_root = None
    if args.output_root:
        output_root = Path(args.output_root).expanduser().resolve()

    if not input_root.exists():
        raise FileNotFoundError(f"Input root does not exist: {input_root}")
    if not input_root.is_dir():
        raise NotADirectoryError(f"Input root is not a directory: {input_root}")

    if output_root is not None and output_root == input_root:
        raise ValueError("--output-root must be different from --input-root.")

    return ConversionConfig(
        input_root=input_root,
        output_root=output_root,
        mode=args.mode,
        quality=args.quality,
        lossless=args.lossless,
        overwrite=args.overwrite,
        delete_originals=args.delete_originals,
        dry_run=args.dry_run,
        verbose=args.verbose,
        workers=args.workers,
        background_color=parse_background_color(args.background_color),
    )


def iter_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def is_supported_source(path: Path, mode: str) -> bool:
    suffix = path.suffix.lower()
    if mode == "to-webp":
        return suffix in SUPPORTED_TO_WEBP_SUFFIXES
    if mode == "to-jpg":
        return suffix in SUPPORTED_TO_JPG_SUFFIXES
    raise ValueError(f"Unsupported mode: {mode}")


def collect_candidate_sources(config: ConversionConfig) -> list[Path]:
    return sorted(
        path
        for path in iter_files(config.input_root)
        if is_supported_source(path, config.mode)
    )


def target_suffix_for_mode(mode: str) -> str:
    if mode == "to-webp":
        return WEBP_SUFFIX
    if mode == "to-jpg":
        return JPEG_SUFFIX
    raise ValueError(f"Unsupported mode: {mode}")


def build_relative_output_path(source_path: Path, input_root: Path, mode: str) -> Path:
    relative_source = source_path.relative_to(input_root)
    return relative_source.with_suffix(target_suffix_for_mode(mode))


def sanitize_suffix_for_name(path: Path) -> str:
    return path.suffix.lower().lstrip(".") or "source"


def build_tasks(config: ConversionConfig) -> list[ConversionTask]:
    sources = collect_candidate_sources(config)
    target_suffix = target_suffix_for_mode(config.mode)

    preliminary_relatives: dict[Path, Path] = {}
    collision_groups: dict[Path, list[Path]] = defaultdict(list)

    for source_path in sources:
        relative_target = build_relative_output_path(
            source_path=source_path,
            input_root=config.input_root,
            mode=config.mode,
        )
        preliminary_relatives[source_path] = relative_target
        collision_groups[relative_target].append(source_path)

    final_relative_paths: dict[Path, Path] = {}
    for relative_target, grouped_sources in collision_groups.items():
        if len(grouped_sources) == 1:
            only_source = grouped_sources[0]
            final_relative_paths[only_source] = relative_target
            continue

        for source_path in grouped_sources:
            adjusted_relative = relative_target.with_name(
                f"{relative_target.stem}__from_"
                f"{sanitize_suffix_for_name(source_path)}"
                f"{target_suffix}"
            )
            final_relative_paths[source_path] = adjusted_relative

    tasks: list[ConversionTask] = []
    for source_path in sources:
        relative_source = source_path.relative_to(config.input_root)
        final_relative = final_relative_paths[source_path]
        if config.output_root is None:
            target_path = source_path.with_name(final_relative.name)
        else:
            target_path = config.output_root / final_relative
        tasks.append(
            ConversionTask(
                source_path=source_path,
                relative_source_path=relative_source,
                target_path=target_path,
            )
        )
    return tasks


def remove_metadata_none_values(values: dict[str, object | None]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None}


def normalize_for_webp(image: Image.Image) -> Image.Image:
    if image.mode in {"RGB", "RGBA"}:
        return image.copy()
    if image.mode in {"P", "LA"}:
        return image.convert("RGBA")
    return image.convert("RGB")


def normalize_for_jpg(
    image: Image.Image,
    background_color: tuple[int, int, int],
) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, background_color)
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    if image.mode != "RGB":
        return image.convert("RGB")
    return image.copy()


def save_as_webp(source_path: Path, target_path: Path, config: ConversionConfig) -> None:
    with Image.open(source_path) as image:
        metadata = remove_metadata_none_values(
            {
                "icc_profile": image.info.get("icc_profile"),
                "exif": image.info.get("exif"),
            }
        )
        save_kwargs: dict[str, object] = {
            "format": "WEBP",
            "quality": config.quality,
            "method": 6,
            **metadata,
        }
        if config.lossless:
            save_kwargs["lossless"] = True

        if getattr(image, "is_animated", False) and getattr(image, "n_frames", 1) > 1:
            frames: list[Image.Image] = []
            try:
                for frame_index in range(image.n_frames):
                    image.seek(frame_index)
                    frames.append(normalize_for_webp(image))
                duration = image.info.get("duration")
                loop = image.info.get("loop", 0)
                frames[0].save(
                    target_path,
                    save_all=True,
                    append_images=frames[1:],
                    duration=duration,
                    loop=loop,
                    **save_kwargs,
                )
            finally:
                for frame in frames:
                    frame.close()
            return

        converted = normalize_for_webp(image)
        try:
            converted.save(target_path, **save_kwargs)
        finally:
            converted.close()


def save_as_jpg(source_path: Path, target_path: Path, config: ConversionConfig) -> None:
    with Image.open(source_path) as image:
        if getattr(image, "is_animated", False) and getattr(image, "n_frames", 1) > 1:
            image.seek(0)

        converted = normalize_for_jpg(
            image=image,
            background_color=config.background_color,
        )
        try:
            save_kwargs = remove_metadata_none_values(
                {
                    "format": "JPEG",
                    "quality": config.quality,
                    "optimize": True,
                    "progressive": True,
                    "icc_profile": image.info.get("icc_profile"),
                    "exif": image.info.get("exif"),
                }
            )
            converted.save(target_path, **save_kwargs)
        finally:
            converted.close()


def ensure_parent_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def convert_one(task: ConversionTask, config: ConversionConfig) -> ConversionResult:
    if task.target_path.exists() and not config.overwrite:
        return ConversionResult(
            source_path=task.source_path,
            target_path=task.target_path,
            status="skipped",
            message="target already exists",
        )

    if config.dry_run:
        return ConversionResult(
            source_path=task.source_path,
            target_path=task.target_path,
            status="dry-run",
            message="planned conversion",
        )

    ensure_parent_directory(task.target_path)

    try:
        if config.mode == "to-webp":
            save_as_webp(
                source_path=task.source_path,
                target_path=task.target_path,
                config=config,
            )
        elif config.mode == "to-jpg":
            save_as_jpg(
                source_path=task.source_path,
                target_path=task.target_path,
                config=config,
            )
        else:
            raise ConversionError(f"Unsupported mode: {config.mode}")
    except UnidentifiedImageError as exc:
        return ConversionResult(
            source_path=task.source_path,
            target_path=task.target_path,
            status="failed",
            message=f"unrecognized image: {exc}",
        )
    except Exception as exc:
        return ConversionResult(
            source_path=task.source_path,
            target_path=task.target_path,
            status="failed",
            message=str(exc),
        )

    if config.delete_originals and task.source_path != task.target_path:
        task.source_path.unlink()

    return ConversionResult(
        source_path=task.source_path,
        target_path=task.target_path,
        status="converted",
        message="",
    )


def process_tasks(
    tasks: Sequence[ConversionTask],
    config: ConversionConfig,
) -> list[ConversionResult]:
    if not tasks:
        return []

    results: list[ConversionResult] = []
    with ThreadPoolExecutor(max_workers=config.workers) as executor:
        futures = [executor.submit(convert_one, task, config) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda result: str(result.source_path))


def summarize_results(results: Iterable[ConversionResult]) -> tuple[int, int, int, int]:
    converted = 0
    skipped = 0
    failed = 0
    dry_run = 0

    for result in results:
        if result.status == "converted":
            converted += 1
        elif result.status == "skipped":
            skipped += 1
        elif result.status == "failed":
            failed += 1
        elif result.status == "dry-run":
            dry_run += 1

    return converted, skipped, failed, dry_run


def print_results(results: Sequence[ConversionResult], verbose: bool) -> None:
    for result in results:
        if verbose or result.status in {"failed", "skipped"}:
            message = f" [{result.message}]" if result.message else ""
            print(f"{result.status}: {result.source_path} -> {result.target_path}{message}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        validate_arguments(args)
        config = build_config(args)
        tasks = build_tasks(config)

        if config.verbose:
            print(f"Discovered {len(tasks)} candidate file(s).")

        results = process_tasks(tasks, config)
        print_results(results, config.verbose)

        converted, skipped, failed, dry_run = summarize_results(results)
        print(
            "Summary: "
            f"converted={converted} "
            f"dry_run={dry_run} "
            f"skipped={skipped} "
            f"failed={failed}"
        )
        return 1 if failed else 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
