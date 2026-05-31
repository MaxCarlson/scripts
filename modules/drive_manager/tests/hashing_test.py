"""Tests for hashing.py."""
from __future__ import annotations

import hashlib

import pytest

from drive_manager.hashing import hash_file, parse_checksum_spec, verify_checksum


def test_parse_checksum_spec_sha256():
    algo, expected = parse_checksum_spec("sha256:abc123")
    assert algo == "sha256"
    assert expected == "abc123"


def test_parse_checksum_spec_md5():
    algo, expected = parse_checksum_spec("md5:deadbeef")
    assert algo == "md5"
    assert expected == "deadbeef"


def test_parse_checksum_spec_sha512():
    algo, expected = parse_checksum_spec("sha512:feedcafe")
    assert algo == "sha512"
    assert expected == "feedcafe"


def test_parse_checksum_spec_no_prefix_defaults_sha256():
    algo, expected = parse_checksum_spec("abc123")
    assert algo == "sha256"
    assert expected == "abc123"


def test_hash_file_sha256(tmp_path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"hello world")
    result = hash_file(f, "sha256")
    assert result == hashlib.sha256(b"hello world").hexdigest()


def test_hash_file_md5(tmp_path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"test data")
    assert hash_file(f, "md5") == hashlib.md5(b"test data").hexdigest()


def test_hash_file_empty(tmp_path):
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    assert hash_file(f, "sha256") == hashlib.sha256(b"").hexdigest()


def test_hash_file_large_data(tmp_path):
    data = b"x" * (4 * 1024 * 1024)
    f = tmp_path / "large.bin"
    f.write_bytes(data)
    assert hash_file(f, "sha256") == hashlib.sha256(data).hexdigest()


def test_verify_checksum_match(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello")
    spec = f"sha256:{hashlib.sha256(b'hello').hexdigest()}"
    assert verify_checksum(f, spec) is True


def test_verify_checksum_mismatch(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello")
    assert verify_checksum(f, "sha256:deadbeef") is False


def test_verify_checksum_case_insensitive(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello")
    digest = hashlib.sha256(b"hello").hexdigest().upper()
    assert verify_checksum(f, f"sha256:{digest}") is True
