from __future__ import annotations

import pytest

from cross_platform.size_utils import parse_size_to_bytes, format_bytes_binary


def test_parse_size_to_bytes_valid():
    assert parse_size_to_bytes("0") == 0
    assert parse_size_to_bytes("1K") == 1024
    assert parse_size_to_bytes("1KB") == 1024
    assert parse_size_to_bytes("1M") == 1024 ** 2
    assert parse_size_to_bytes("2GB") == 2 * (1024 ** 3)
    assert parse_size_to_bytes("1.5G") == int(1.5 * (1024 ** 3))
    assert parse_size_to_bytes(None) is None
    assert parse_size_to_bytes("") is None


def test_parse_size_to_bytes_invalid():
    with pytest.raises(ValueError):
        parse_size_to_bytes("XYZ")
    with pytest.raises(ValueError):
        parse_size_to_bytes("10QQ")


def test_format_bytes_binary():
    assert format_bytes_binary(0) == "0 B"
    assert format_bytes_binary(1024) == "1.00 KiB"
    assert format_bytes_binary(1024 ** 2) == "1.00 MiB"
    s = format_bytes_binary(5 * 1024 ** 3)
    assert s.endswith("GiB")

