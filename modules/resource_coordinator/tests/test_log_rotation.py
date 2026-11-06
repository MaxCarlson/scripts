from pathlib import Path

from resource_coordinator.core.processes import _rotate_log_file


def test_rotate_log_file_preserves_existing_bytes_and_bounds_archives(tmp_path: Path):
    log = tmp_path / "miner.log"
    log.write_bytes(b"0123456789")

    _rotate_log_file(log, max_bytes=8, backups=2)

    assert log.read_bytes() == b""
    assert log.with_name("miner.log.1").read_bytes() == b"0123456789"

    log.write_bytes(b"abcdefghij")
    _rotate_log_file(log, max_bytes=8, backups=2)

    assert log.with_name("miner.log.1").read_bytes() == b"abcdefghij"
    assert log.with_name("miner.log.2").read_bytes() == b"0123456789"

    log.write_bytes(b"klmnopqrst")
    _rotate_log_file(log, max_bytes=8, backups=2)

    assert log.with_name("miner.log.1").read_bytes() == b"klmnopqrst"
    assert log.with_name("miner.log.2").read_bytes() == b"abcdefghij"
    assert not log.with_name("miner.log.3").exists()


def test_rotate_log_file_does_not_change_small_existing_file(tmp_path: Path):
    log = tmp_path / "miner.log"
    log.write_bytes(b"keep me")

    _rotate_log_file(log, max_bytes=8, backups=2)

    assert log.read_bytes() == b"keep me"
    assert not log.with_name("miner.log.1").exists()
