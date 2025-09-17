#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Try common layouts so this test can run if ytaedl is present, otherwise skip.
UI_CANDIDATES = [
    ROOT / "yt_ae_dl" / "yt_ae_dl" / "ui.py",  # old layout
    ROOT / "ytaedl" / "ui.py",                 # new/simple layout
]

UI_PATH = next((p for p in UI_CANDIDATES if p.is_file()), None)

# ------------------------ Fake TermDash for tests ------------------------

class _FakeLine:
    def __init__(self, name: str, stats: list[Any], style: str | None = None):
        self.name = name
        self.stats = stats
        self.style = style

class _FakeStat:
    def __init__(self, name, value, prefix="", format_string="{}", unit="", **kw):
        self.name = name
        self.value = value

class _FakeDash:
    def __init__(self, **_):
        self.lines: dict[str, dict[str, Any]] = {}
        self.seps = 0

    def __enter__(self): return self
    def __exit__(self, *_): return False

    def add_line(self, name: str, line: _FakeLine):
        self.lines[name] = {}
        for s in line.stats:
            self.lines[name][s.name] = s.value

    def add_separator(self):
        self.seps += 1

    def update_stat(self, line: str, stat: str, value: Any):
        self.lines.setdefault(line, {})
        self.lines[line][stat] = value

    def read_stat(self, line: str, stat: str):
        return self.lines.get(line, {}).get(stat, None)


def _install_fake_termdash():
    mod = ModuleType("termdash")
    mod.TermDash = _FakeDash
    mod.Line = _FakeLine
    mod.Stat = _FakeStat

    utils = ModuleType("termdash.utils")
    def fmt_hms(seconds: float) -> str:
        s = int(seconds)
        h, r = divmod(s, 3600)
        m, s = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    def bytes_to_mib(b: float) -> float:
        return float(b) / (1024.0 * 1024.0)
    utils.fmt_hms = fmt_hms
    utils.bytes_to_mib = bytes_to_mib

    sys.modules["termdash"] = mod
    sys.modules["termdash.utils"] = utils


def _import_ui():
    if not UI_PATH:
        pytest.skip(
            "ytaedl UI not found in this repo. "
            "Move this test into the ytaedl repo or vendor ytaedl next to termdash."
        )
    spec = importlib.util.spec_from_file_location("yt_ui", UI_PATH)
    assert spec and spec.loader, f"Cannot load ui.py from {UI_PATH}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["yt_ui"] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


# ------------------------------ tests -----------------------------------

def test_header_and_workers_wired_test():
    _install_fake_termdash()
    ui_mod = _import_ui()

    ui = ui_mod.TermdashUI(num_workers=2, total_urls=10)

    # initial header state
    assert ui.dash.read_stat("overall2", "urls") == (0, 10)

    # begin scan creates scan section
    ui.begin_scan(num_workers=2, total_files=5)
    assert ui.dash.read_stat("scan:hdr", "files") == (0, 5)
    ui.set_scan_slot(0, "main:alpha")
    assert ui.dash.read_stat("scan:0", "label") == "main:alpha"
    ui.advance_scan(2)
    assert ui.dash.read_stat("scan:hdr", "files") == (2, 5)

    # simulate StartEvent/FinishEvent via duck types
    class StartEvent:
        def __init__(self, id: int, url: str, stem: str):
            class _Src:  # minimal source stub
                def __init__(self, file): self.file = file
            class _Item:
                def __init__(self, id, url, stem):
                    self.id, self.url = id, url
                    self.source = _Src(stem + ".txt")
            self.item = _Item(id, url, stem)

    class FinishEvent:
        def __init__(self, id: int, status_value: str):
            class _Status:
                def __init__(self, v): self.value = v
            class _Res:
                def __init__(self, v): self.status = _Status(v)
            class _Item:
                def __init__(self, id): self.id = id; self.url = "u"
            self.item = _Item(id)
            self.result = _Res(status_value)

    ui.handle_event(StartEvent(1, "http://x", "set1"))
    # urls counter on worker 2 (id 1 -> slot 1)
    assert ui.dash.read_stat("w2:main", "set") == "set1"
    assert ui.dash.read_stat("w2:main", "urls")[0] >= 1

    ui.handle_event(FinishEvent(1, "already_exists"))
    assert ui.dash.read_stat("w2:s3", "already") == 1
    assert ui.dash.read_stat("overall2", "already") == 0  # header updated in pump()

    ui.pump()  # header tick & propagation
    assert ui.dash.read_stat("overall2", "already") == 1

    ui.end_scan()
    assert ui.dash.read_stat("scan:0", "status") == "done"
