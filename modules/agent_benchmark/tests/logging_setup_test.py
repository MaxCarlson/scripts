from __future__ import annotations

import logging

from agent_benchmark.logging_setup import close_run_logging, configure_run_logging


def test_run_logging_writes_utf8_and_can_be_closed(tmp_path) -> None:
    path = tmp_path / "EXP_test" / "benchmark.log"
    handler = configure_run_logging(path)
    logger = logging.getLogger("agent_benchmark.scheduler")

    try:
        logger.info("transition target=%s", "muse-glimmer ✓")
    finally:
        close_run_logging(handler)

    assert "muse-glimmer ✓" in path.read_text(encoding="utf-8")
    assert handler not in logging.getLogger("agent_benchmark").handlers


def test_run_logging_replaces_existing_run_handler_without_duplicates(tmp_path) -> None:
    first = configure_run_logging(tmp_path / "first.log")
    second = configure_run_logging(tmp_path / "second.log")
    logger = logging.getLogger("agent_benchmark")

    try:
        assert first not in logger.handlers
        assert second in logger.handlers
        logger.info("only second handler")
    finally:
        close_run_logging(second)

    assert "only second handler" not in (tmp_path / "first.log").read_text(encoding="utf-8")
    assert "only second handler" in (tmp_path / "second.log").read_text(encoding="utf-8")
