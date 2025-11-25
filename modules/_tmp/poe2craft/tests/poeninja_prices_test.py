#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

# Ensure package import works when repo layout is <root>/scripts/poe2craft
import sys
ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "scripts"
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))

from poe2craft.datasources.poeninja_prices import PoENinjaPriceProvider  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, headers=None, text="", content=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _SessionMock:
    def __init__(self, mapping: Dict[str, _Resp]):
        self.mapping = mapping

    def get(self, url: str, timeout: int = 20):
        # find by prefix match for convenience
        for k, v in self.mapping.items():
            if url.startswith(k):
                return v
        # default: simulate 404
        return _Resp(status_code=404, headers={"content-type": "text/html"}, text="not found")


def test_currency_api_path_parses_receive_values(monkeypatch):
    data = {
        "lines": [
            {"currencyTypeName": "Chaos Orb", "receive": {"value": 1.0}},
            {"currencyTypeName": "Exalted Orb", "receive": {"value": 120.5}},
            {"currencyTypeName": "Divine Orb", "receive": {"value": 210.0}},
        ]
    }
    api_url_prefix = "https://poe.ninja/api/data/currencyoverview"
    sess = _SessionMock(
        {
            api_url_prefix: _Resp(
                status_code=200,
                headers={"content-type": "application/json"},
                text=json.dumps(data),
                content=json.dumps(data).encode("utf-8"),
            )
        }
    )
    prov = PoENinjaPriceProvider(session=sess)
    prices = prov.get_currency_prices(league="Standard")

    assert prices["Chaos Orb"] == 1.0
    assert prices["Exalted Orb"] == 120.5
    assert prices["Divine Orb"] == 210.0


def test_currency_fallback_scrapes_next_data_blob(monkeypatch):
    # Force API path to fail (non-JSON), then economy page provides __NEXT_DATA__ blob
    api_url_prefix = "https://poe.ninja/api/data/currencyoverview"
    econ_url_prefix = "https://poe.ninja/poe2/economy/standard/currency"

    blob = {
        "props": {
            "pageProps": {
                "some": "state",
                "data": [
                    {"name": "Chaos Orb", "chaosValue": 1.0},
                    {"name": "Exalted Orb", "chaosValue": 120.0},
                ],
            }
        }
    }
    html = f'<html><head></head><body><script id="__NEXT_DATA__">{json.dumps(blob)}</script></body></html>'

    sess = _SessionMock(
        {
            api_url_prefix: _Resp(status_code=200, headers={"content-type": "text/html"}, text="not-json"),
            econ_url_prefix: _Resp(status_code=200, headers={"content-type": "text/html"}, text=html),
        }
    )

    prov = PoENinjaPriceProvider(session=sess)
    prices = prov.get_currency_prices(league="Standard")

    assert prices.get("Chaos Orb") == 1.0
    assert prices.get("Exalted Orb") == 120.0


def test_currency_fallback_when_no_blob_returns_empty(monkeypatch):
    api_url_prefix = "https://poe.ninja/api/data/currencyoverview"
    econ_url_prefix = "https://poe.ninja/poe2/economy/standard/currency"

    sess = _SessionMock(
        {
            api_url_prefix: _Resp(status_code=500, headers={"content-type": "text/html"}, text="err"),
            econ_url_prefix: _Resp(status_code=200, headers={"content-type": "text/html"}, text="<html>no data</html>"),
        }
    )
    prov = PoENinjaPriceProvider(session=sess)
    prices = prov.get_currency_prices(league="Standard")
    assert prices == {}
