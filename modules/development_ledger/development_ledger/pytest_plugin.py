"""Pytest plugin that exports development-ledger item IDs to JUnit properties."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

MARKER_NAME = "ledger_item"


def pytest_configure(config: Any) -> None:
    """Register the strict-marker-compatible ledger item marker."""

    config.addinivalue_line(
        "markers",
        "ledger_item(*ids): associate this test with development-ledger feature/requirement/criterion IDs",
    )


def pytest_collection_modifyitems(items: Iterable[Any]) -> None:
    """Copy marker IDs into JUnit-compatible user properties."""

    for item in items:
        existing = {(str(name), str(value)) for name, value in getattr(item, "user_properties", [])}
        for marker in item.iter_markers(name=MARKER_NAME):
            for item_id in _marker_ids(marker):
                property_pair = ("item", item_id)
                if property_pair not in existing:
                    item.user_properties.append(property_pair)
                    existing.add(property_pair)


def _marker_ids(marker: Any) -> list[str]:
    values = list(marker.args)
    keyword_value = marker.kwargs.get("ids")
    if isinstance(keyword_value, str):
        values.append(keyword_value)
    elif isinstance(keyword_value, (list, tuple, set)):
        values.extend(keyword_value)
    return [str(value).strip() for value in values if str(value).strip()]
