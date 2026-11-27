"""Run scheduled notification commands without relying on a console."""

from __future__ import annotations

import contextlib
import logging
import sys
import traceback
from collections.abc import Sequence
from logging.handlers import RotatingFileHandler
from pathlib import Path


def scheduled_runner(executable: Path, *, windows: bool) -> tuple[Path, str]:
    """Choose the windowless sibling when using a standard Windows interpreter."""
    if windows and executable.name.lower() in {"python.exe", "pythonw.exe"}:
        windowless = executable.with_name("pythonw.exe")
        if windowless.is_file():
            return windowless, "notifications.headless_task"
    return executable, "notifications.cli"


class _LogStream:
    """Adapt a rotating handler to the text streams expected by the CLI."""

    encoding = "utf-8"

    def __init__(self, handler: RotatingFileHandler) -> None:
        self.handler = handler
        self.pending = ""

    def write(self, text: str) -> int:
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            self._emit(line)
        return len(text)

    def _emit(self, text: str) -> None:
        record = logging.LogRecord(
            "notifications.headless", logging.INFO, "", 0, text, (), None
        )
        self.handler.emit(record)

    def flush(self) -> None:
        if self.pending:
            self._emit(self.pending)
            self.pending = ""
        self.handler.flush()

    def isatty(self) -> bool:
        return False


def run(argv: Sequence[str], *, log_directory: Path | None = None) -> int:
    if not argv or argv[0] not in {"outbox", "coordinator"}:
        raise ValueError("Expected an outbox or coordinator scheduled command")
    log_dir = log_directory or Path.home() / ".scripts" / "Notifications" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / f"{argv[0]}.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    stream = _LogStream(handler)
    try:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            try:
                from notifications.cli import main

                return int(main(argv))
            except SystemExit as exc:
                if isinstance(exc.code, int):
                    return exc.code
                if exc.code is not None:
                    print(exc.code, file=sys.stderr)
                    return 1
                return 0
            except Exception:
                traceback.print_exc()
                return 1
            finally:
                stream.flush()
    finally:
        handler.close()


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
