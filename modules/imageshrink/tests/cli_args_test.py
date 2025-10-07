#!/usr/bin/env python3
"""
Tests for CLI argument parsing and short forms.
"""

import pytest
import sys
from pathlib import Path

from imgshrink.cli import _build_legacy_parser, main


def test_all_legacy_args_have_short_forms():
    """Verify that all legacy parser arguments have short forms (except --version and --help)."""
    parser = _build_legacy_parser()

    # Collect all actions
    actions = parser._actions

    # Filter out help and version actions (these typically don't have short forms)
    optional_actions = [
        a for a in actions
        if a.option_strings and a.dest not in ['help', 'version']
    ]

    for action in optional_actions:
        # Each action should have at least one short form (single dash + single char)
        short_forms = [opt for opt in action.option_strings if len(opt) == 2 and opt.startswith('-')]
        long_forms = [opt for opt in action.option_strings if opt.startswith('--')]

        assert len(short_forms) >= 1, f"Argument {action.dest} ({long_forms}) has no short form"
        assert len(long_forms) >= 1, f"Argument {action.dest} has no long form"


def test_quality_preset_short_form():
    """Test that quality preset argument works with short form."""
    parser = _build_legacy_parser()

    # Test with short form
    args_short = parser.parse_args(['-q', '5', 'test_root'])
    assert args_short.quality_preset == 5

    # Test with long form
    args_long = parser.parse_args(['--quality-preset', '5', 'test_root'])
    assert args_long.quality_preset == 5


def test_device_args_short_forms():
    """Test that all device-related arguments have short forms."""
    parser = _build_legacy_parser()

    # Test display-res
    args = parser.parse_args(['-x', '2400x1080', 'test_root'])
    assert args.display_res == '2400x1080'

    # Test display-diagonal-in
    args = parser.parse_args(['-i', '6.8', 'test_root'])
    assert args.display_diagonal_in == 6.8

    # Test viewing-distance-cm
    args = parser.parse_args(['-c', '30', 'test_root'])
    assert args.viewing_distance_cm == 30.0

    # Test fit-mode
    args = parser.parse_args(['-F', 'fit-width', 'test_root'])
    assert args.fit_mode == 'fit-width'

    # Test ppd-photo
    args = parser.parse_args(['-p', '70', 'test_root'])
    assert args.ppd_photo == 70.0

    # Test ppd-line
    args = parser.parse_args(['-l', '85', 'test_root'])
    assert args.ppd_line == 85.0

    # Test guard-ssim
    args = parser.parse_args(['-g', '0.95', 'test_root'])
    assert args.guard_ssim == 0.95


def test_short_forms_no_conflicts():
    """Verify that no two arguments share the same short form."""
    parser = _build_legacy_parser()

    # Collect all short forms
    short_forms = {}
    for action in parser._actions:
        if action.option_strings:
            for opt in action.option_strings:
                if len(opt) == 2 and opt.startswith('-'):
                    if opt in short_forms:
                        pytest.fail(
                            f"Conflict: short form '{opt}' used by both "
                            f"{short_forms[opt]} and {action.dest}"
                        )
                    short_forms[opt] = action.dest

    # Verify we have a reasonable number of short forms (at least 15)
    assert len(short_forms) >= 15, f"Expected at least 15 short forms, got {len(short_forms)}"


def test_subcommand_help_works():
    """Test that all subcommand help works without errors."""
    subcommands = ['analyze', 'plan', 'compress', 'all', 'profile']

    for subcmd in subcommands:
        # This should not raise an exception
        try:
            main([subcmd, '-h'])
        except SystemExit as e:
            # argparse raises SystemExit(0) after printing help
            assert e.code == 0, f"Subcommand '{subcmd}' help failed with code {e.code}"
