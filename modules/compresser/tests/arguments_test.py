import argparse
from pathlib import Path

import pytest

from compresser.arguments import build_operation_parsers, normalize_compression_arguments


def _parser(owner="compresser"):
    parser = argparse.ArgumentParser(prog=owner)
    build_operation_parsers(parser, owner=owner)
    return parser


@pytest.mark.parametrize(
    "owner,target_flag,target_dest", [("compresser", "-i", "input"), ("mangadl", "-d", "destination")]
)
def test_operation_tree_and_normalized_recipe_parity(owner, target_flag, target_dest):
    parser = _parser(owner)
    namespace = parser.parse_args(
        ["plan", target_flag, "library", "-m", "lossy", "-f", "webp", "avif", "-q", "0.85", "85", "-s", "8"]
    )

    options = normalize_compression_arguments(namespace)

    assert options.operation == "plan"
    assert getattr(options, "target") == Path("library")
    assert [(recipe.format, recipe.quality) for recipe in options.recipes] == [("webp", 85), ("avif", 85)]
    assert options.max_images == 8


@pytest.mark.parametrize(
    "argv",
    [
        ["-i", "library", "-l"],
        ["analyze", "-i", "library", "-c"],
        ["compare", "-i", "library", "-b"],
        ["compare", "-i", "library", "-Q", "80"],
        ["recover", "-i", "library", "-R"],
        ["inventory", "-i", "library", "--inventory-file", "legacy.sqlite3"],
        ["preview", "-i", "library", "--output-dir", "elsewhere"],
    ],
)
def test_removed_flat_flags_are_rejected(argv):
    with pytest.raises(SystemExit):
        _parser().parse_args(argv)


def test_duplicate_formats_and_qualities_produce_one_recipe():
    namespace = _parser().parse_args(
        ["analyze", "-i", "library", "-m", "lossy", "-f", "webp", "webp", "-q", "85", "85"]
    )
    options = normalize_compression_arguments(namespace)
    assert len(options.recipes) == 1


def test_mixed_compare_keeps_png_lossless_and_other_formats_lossy():
    namespace = _parser().parse_args(["compare", "-i", "library", "-f", "png", "webp", "-m", "both", "-q", "85"])
    options = normalize_compression_arguments(namespace)
    assert [(recipe.format, recipe.mode) for recipe in options.recipes] == [
        ("png", "lossless"),
        ("webp", "lossless"),
        ("webp", "lossy"),
    ]


@pytest.mark.parametrize(
    "argv,match",
    [
        (["apply", "-i", "library"], "--write"),
        (["apply", "-i", "library", "-w", "-m", "lossy"], "--allow-lossy"),
        (["recover", "-i", "library", "-C", "token"], "--write"),
        (["recover", "-i", "library", "-w"], "--confirm"),
        (["plan", "-i", "library", "-m", "lossless", "-q", "85"], "[Qq]uality"),
        (["plan", "-i", "library", "-m", "lossy", "-f", "png", "-q", "85"], "PNG"),
    ],
)
def test_safety_and_recipe_combinations_fail_normalization(argv, match):
    namespace = _parser().parse_args(argv)
    with pytest.raises(ValueError, match=match):
        normalize_compression_arguments(namespace)


@pytest.mark.parametrize("value", ["0", "101", "1.001", "nan", "inf", "-0.1"])
def test_quality_parser_rejects_non_exact_or_non_finite_values(value):
    with pytest.raises(SystemExit):
        _parser().parse_args(["plan", "-i", "library", "-m", "lossy", "-q", value])


@pytest.mark.parametrize("value", ["0", "0s", "NaN", "inf", "5fortnights", "-1m"])
def test_duration_parser_rejects_invalid_or_non_finite_values(value):
    with pytest.raises(SystemExit):
        _parser().parse_args(["plan", "-i", "library", "-M", value])


def test_accuracy_parser_rejects_values_that_underflow_float_precision():
    with pytest.raises(SystemExit):
        _parser().parse_args(["plan", "-i", "library", "--accuracy-pp", "1e-400"])


def test_help_scopes_options_to_operation(capsys):
    parser = _parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    top = capsys.readouterr().out
    assert "inventory" in top and "estimate" in top
    assert "--allow-lossy" not in top

    with pytest.raises(SystemExit):
        parser.parse_args(["inventory", "--help"])
    inventory = capsys.readouterr().out
    assert "--depth" in inventory
    assert "--quality" not in inventory


def test_plan_and_estimate_require_an_explicit_target():
    with pytest.raises(SystemExit):
        _parser().parse_args(["plan"])


def test_allow_larger_normalizes_into_recipe_identity():
    standard = normalize_compression_arguments(_parser().parse_args(["plan", "-i", "library"]))
    growth = normalize_compression_arguments(_parser().parse_args(["plan", "-i", "library", "-F"]))
    assert growth.recipes[0].identity != standard.recipes[0].identity
    assert growth.recipes[0].retained_original_policy == "allow-larger"
