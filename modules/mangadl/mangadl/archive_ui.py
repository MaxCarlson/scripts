from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from termdash import utils as td_utils

from .ui import clip, fit_field


@dataclass(frozen=True, slots=True)
class ArchiveRecord:
    rowid: int
    values: dict[str, Any]

    def searchable_text(self) -> str:
        return " ".join(str(value) for value in self.values.values() if value is not None).casefold()


@dataclass(frozen=True, slots=True)
class ArchiveSnapshot:
    path: Path
    tables: tuple[str, ...]
    columns: tuple[str, ...]
    records: tuple[ArchiveRecord, ...]


def load_archive(path: Path) -> ArchiveSnapshot:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"archive does not exist: {resolved}")

    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        )
        if "archive" not in tables:
            return ArchiveSnapshot(resolved, tables, (), ())
        columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(archive)"))
        rows = connection.execute("SELECT rowid AS __rowid__, * FROM archive ORDER BY rowid").fetchall()
    finally:
        connection.close()

    records = tuple(
        ArchiveRecord(
            rowid=int(row["__rowid__"]),
            values={column: row[column] for column in columns},
        )
        for row in rows
    )
    return ArchiveSnapshot(resolved, tables, columns, records)


def filter_records(records: tuple[ArchiveRecord, ...], query: str) -> tuple[ArchiveRecord, ...]:
    normalized = query.strip().casefold()
    if not normalized:
        return records
    terms = normalized.split()
    return tuple(record for record in records if all(term in record.searchable_text() for term in terms))


def _preferred_columns(columns: tuple[str, ...], maximum: int = 4) -> tuple[str, ...]:
    preferred = (
        "extractor",
        "category",
        "subcategory",
        "directory",
        "filename",
        "id",
    )
    selected = [column for column in preferred if column in columns]
    selected.extend(column for column in columns if column not in selected)
    return tuple(selected[:maximum])


def render_archive_browser(
    snapshot: ArchiveSnapshot,
    records: tuple[ArchiveRecord, ...],
    *,
    selected: int,
    query: str,
    width: int,
    height: int,
) -> str:
    width = max(50, width)
    height = max(12, height)
    selected = max(0, min(selected, max(0, len(records) - 1)))
    columns = _preferred_columns(snapshot.columns)
    header_rows = 5
    detail_rows = min(max(4, len(snapshot.columns) + 1), max(4, height // 3))
    page_size = max(1, height - header_rows - detail_rows - 2)
    page_start = (selected // page_size) * page_size
    page = records[page_start : page_start + page_size]

    lines = [
        clip(f"{td_utils.color_text('mangadl archive', 'bright')} | {snapshot.path}", width),
        clip(
            f"Records {len(records)}/{len(snapshot.records)} | "
            f"Selected {selected + 1 if records else 0} | Filter {query or '-'}",
            width,
        ),
        clip("j/k or arrows Move | PgUp/PgDn Page | Home/End | / Filter | c Clear | e Export JSON | q Quit", width),
        "-" * width,
    ]

    if not records:
        lines.append(clip("No archive records match the current filter.", width))
    else:
        row_prefix = 8
        available = max(1, width - row_prefix - max(0, len(columns) - 1) * 3)
        column_width = max(8, available // max(1, len(columns)))
        for offset, record in enumerate(page):
            absolute = page_start + offset
            marker = td_utils.color_text(">", "cyan") if absolute == selected else " "
            fields = [fit_field(str(record.values.get(column, "") or ""), column_width) for column in columns]
            lines.append(clip(f"{marker}{record.rowid:06d} " + " | ".join(fields), width))

    lines.append("-" * width)
    if records:
        record = records[selected]
        lines.append(clip(f"Record rowid={record.rowid}", width))
        for column in snapshot.columns[: max(1, detail_rows - 1)]:
            lines.append(clip(f"{fit_field(column, 18)} : {record.values.get(column, '')}", width))
    else:
        lines.append("No selected record.")

    return "\n".join(lines[:height])


class ArchiveBrowser:
    def __init__(self, snapshot: ArchiveSnapshot) -> None:
        self.snapshot = snapshot
        self.query = ""
        self.records = snapshot.records
        self.selected = 0

    def set_filter(self, query: str) -> None:
        self.query = query.strip()
        self.records = filter_records(self.snapshot.records, self.query)
        self.selected = 0

    def move(self, amount: int) -> None:
        if not self.records:
            self.selected = 0
            return
        self.selected = max(0, min(len(self.records) - 1, self.selected + amount))

    def export(self, path: Path) -> None:
        payload = {
            "archive": str(self.snapshot.path),
            "filter": self.query,
            "columns": list(self.snapshot.columns),
            "records": [
                {"rowid": record.rowid, **record.values}
                for record in self.records
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=4, default=str) + "\n", encoding="utf-8")

    def run(self) -> int:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print(f"{self.snapshot.path}: {len(self.snapshot.records)} archive records")
            return 0

        while True:
            terminal = os.get_terminal_size()
            print(
                "\x1b[H\x1b[2J"
                + render_archive_browser(
                    self.snapshot,
                    self.records,
                    selected=self.selected,
                    query=self.query,
                    width=min(200, terminal.columns),
                    height=terminal.lines,
                ),
                end="",
                flush=True,
            )
            key = _read_key()
            page = max(1, terminal.lines - 12)
            if key in {"q", "Q", "\x03"}:
                return 0
            if key in {"j", "DOWN"}:
                self.move(1)
            elif key in {"k", "UP"}:
                self.move(-1)
            elif key == "PGDN":
                self.move(page)
            elif key == "PGUP":
                self.move(-page)
            elif key == "HOME":
                self.selected = 0
            elif key == "END":
                self.selected = max(0, len(self.records) - 1)
            elif key == "c":
                self.set_filter("")
            elif key == "/":
                print("\x1b[H\x1b[2JFilter: ", end="", flush=True)
                self.set_filter(input())
            elif key == "e":
                default = self.snapshot.path.with_name(self.snapshot.path.stem + "-filtered.json")
                print(f"\x1b[H\x1b[2JExport path [{default}]: ", end="", flush=True)
                value = input().strip()
                self.export(Path(value).expanduser().resolve() if value else default)


def _read_key() -> str:
    if os.name == "nt":
        import msvcrt

        key = msvcrt.getwch()
        if key in {"\x00", "\xe0"}:
            return {
                "H": "UP",
                "P": "DOWN",
                "I": "PGUP",
                "Q": "PGDN",
                "G": "HOME",
                "O": "END",
            }.get(msvcrt.getwch(), "")
        return key

    import termios
    import tty

    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        tty.setraw(descriptor)
        key = sys.stdin.read(1)
        if key == "\x1b":
            sequence = sys.stdin.read(2)
            return {"[A": "UP", "[B": "DOWN", "[H": "HOME", "[F": "END"}.get(sequence, "")
        return key
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)
