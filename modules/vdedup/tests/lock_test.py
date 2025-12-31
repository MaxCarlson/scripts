import logging
import os
import time
from pathlib import Path

from vdedup import video_dedupe


def _make_logger() -> logging.Logger:
    logger = logging.getLogger("vdedup-lock-test")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger


def test_acquire_lock_respects_existing_file(tmp_path: Path) -> None:
    logger = _make_logger()
    lock = tmp_path / ".vdedup.lock"
    assert video_dedupe._acquire_output_lock(lock, resume=False, logger=logger) is True
    assert lock.exists()
    assert video_dedupe._acquire_output_lock(lock, resume=False, logger=logger) is False
    assert video_dedupe._acquire_output_lock(lock, resume=True, logger=logger) is True
    assert lock.exists()
    video_dedupe._release_output_lock(lock, logger)
    assert not lock.exists()


def test_acquire_lock_removes_stale(tmp_path: Path) -> None:
    logger = _make_logger()
    lock = tmp_path / ".vdedup.lock"
    assert video_dedupe._acquire_output_lock(lock, resume=False, logger=logger) is True
    os.utime(lock, (time.time() - (video_dedupe._LOCK_STALE_SECONDS + 10),) * 2)
    assert video_dedupe._acquire_output_lock(lock, resume=False, logger=logger) is True
    video_dedupe._release_output_lock(lock, logger)
