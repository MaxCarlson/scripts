from __future__ import annotations

from types import SimpleNamespace

from development_ledger.pytest_plugin import _marker_ids, pytest_collection_modifyitems, pytest_configure


class DummyConfig:
    def __init__(self):
        self.lines = []

    def addinivalue_line(self, name, value):
        self.lines.append((name, value))


class DummyItem:
    def __init__(self, markers):
        self.markers = markers
        self.user_properties = []

    def iter_markers(self, name):
        assert name == "ledger_item"
        return self.markers


def test_pytest_plugin_registers_marker_and_exports_properties():
    config = DummyConfig()
    marker = SimpleNamespace(args=("AC-1",), kwargs={"ids": ["AC-2"]})
    item = DummyItem([marker])

    pytest_configure(config)
    pytest_collection_modifyitems([item])

    assert config.lines[0][0] == "markers"
    assert item.user_properties == [("item", "AC-1"), ("item", "AC-2")]


def test_marker_ids_ignores_empty_values():
    marker = SimpleNamespace(args=("", "AC-1"), kwargs={})
    assert _marker_ids(marker) == ["AC-1"]
