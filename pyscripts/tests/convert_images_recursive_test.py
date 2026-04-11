from __future__ import annotations

from pathlib import Path

from PIL import Image

from convert_images_recursive import (
    build_argument_parser,
    build_config,
    build_tasks,
    main,
    parse_background_color,
    process_tasks,
    summarize_results,
)


def make_png(
    path: Path,
    color: tuple[int, int, int, int] = (255, 0, 0, 255),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), color).save(path, format="PNG")


def make_webp(
    path: Path,
    color: tuple[int, int, int, int] = (0, 0, 255, 128),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), color).save(path, format="WEBP")


def parse_args(*args: str):
    return build_argument_parser().parse_args(list(args))


def test_parse_background_color_hex() -> None:
    assert parse_background_color("#112233") == (17, 34, 51)


def test_build_tasks_adds_collision_suffixes(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    make_png(input_root / "photo.png")
    Image.new("RGB", (8, 8), (0, 255, 0)).save(input_root / "photo.jpg", format="JPEG")

    args = parse_args("-i", str(input_root), "-m", "to-webp")
    config = build_config(args)
    tasks = build_tasks(config)

    target_names = sorted(task.target_path.name for task in tasks)
    assert target_names == ["photo__from_jpg.webp", "photo__from_png.webp"]


def test_main_converts_png_to_webp_in_place(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    make_png(input_root / "nested" / "frame.png")

    exit_code = main(
        [
            "-i",
            str(input_root),
            "-m",
            "to-webp",
        ]
    )

    assert exit_code == 0
    assert (input_root / "nested" / "frame.webp").exists()
    assert (input_root / "nested" / "frame.png").exists()


def test_main_converts_webp_to_jpg_with_output_root(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    make_webp(input_root / "sub" / "image.webp")

    exit_code = main(
        [
            "-i",
            str(input_root),
            "-o",
            str(output_root),
            "-m",
            "to-jpg",
            "-b",
            "#FFFFFF",
        ]
    )

    assert exit_code == 0
    output_file = output_root / "sub" / "image.jpg"
    assert output_file.exists()

    with Image.open(output_file) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"


def test_process_tasks_dry_run_writes_nothing(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    make_png(input_root / "sample.png")

    args = parse_args("-i", str(input_root), "-m", "to-webp", "-n")
    config = build_config(args)
    tasks = build_tasks(config)
    results = process_tasks(tasks, config)

    converted, skipped, failed, dry_run = summarize_results(results)

    assert converted == 0
    assert skipped == 0
    assert failed == 0
    assert dry_run == 1
    assert not (input_root / "sample.webp").exists()
