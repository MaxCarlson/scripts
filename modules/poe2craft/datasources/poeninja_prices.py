#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import re
import time
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("poe2craft.datasources.poeninja")

_API_CURRENCY = "https://poe.ninja/api/data/currencyoverview"
_FALLBACK_PAGE = "https://poe.ninja/poe2/economy/{league_slug}/currency"
_POE2_LADDERS = "https://pathofexile2.com/ladders"


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")


class PoENinjaPriceProvider:
    """
    Currency prices for PoE2 via poe.ninja.
    - Primary: official API
    - Fallback: scrape economy page __NEXT_DATA__ blob
    """

    def __init__(self, session: Optional[requests.Session] = None, timeout: float = 12.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def get_currency_prices(self, league: str = "Standard") -> Dict[str, float]:
        # 1) API path
        params = {"league": league, "type": "Currency", "language": "en"}
        try:
            r = self.session.get(_API_CURRENCY, params=params, timeout=self.timeout)
            if "application/json" in r.headers.get("content-type", ""):
                data = r.json()
                result: Dict[str, float] = {}
                for line in data.get("lines", []):
                    name = line.get("currencyTypeName")
                    value = None
                    # Prefer the "receive" price if present (matches your tests)
                    receive = line.get("receive") or {}
                    if isinstance(receive, dict) and "value" in receive:
                        value = receive.get("value")
                    if value is None:
                        value = line.get("chaosEquivalent")
                    if name and isinstance(value, (int, float)):
                        result[name] = float(value)
                if result:
                    return result
        except Exception as e:
            log.warning("poe.ninja API error: %s", e)

        # 2) Fallback: scrape economy page for PoE2 (requires slugified league)
        league_slug = _slugify(league)
        url = _FALLBACK_PAGE.format(league_slug=league_slug)
        try:
            r = self.session.get(url, timeout=self.timeout)
            # Try to find __NEXT_DATA__ blob
            if "text/html" in r.headers.get("content-type", ""):
                soup = BeautifulSoup(r.text, "html.parser")
                blob = soup.find("script", id="__NEXT_DATA__")
                if not blob or not blob.string:
                    log.warning("Could not find embedded JSON on %s; returning empty price map", url)
                    return {}
                try:
                    j = json.loads(blob.string)
                    # The blob structure is not stable; attempt common shapes.
                    page_props = ((j.get("props") or {}).get("pageProps") or {})
                    arr = page_props.get("data") or page_props.get("items") or []
                    out: Dict[str, float] = {}
                    for it in arr:
                        n = it.get("name")
                        v = it.get("chaosValue")
                        if n and isinstance(v, (int, float)):
                            out[n] = float(v)
                    return out
                except Exception as e:
                    log.warning("Error parsing __NEXT_DATA__ on %s: %s", url, e)
                    return {}
        except Exception as e:
            log.warning("poe.ninja economy fallback failed for %s: %s", url, e)

        return {}

    # -------- current league detection (PoE2) --------

    def detect_current_league(self) -> Optional[str]:
        """
        Scrape PoE2 ladders page, select a challenge league name (first non-permanent).
        """
        try:
            r = self.session.get(_POE2_LADDERS, timeout=self.timeout)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            # The page lists league names as words separated by dots/links.
            txt = soup.get_text(" ", strip=True)
            # Known permanent PoE2 leagues:
            permanent = {"Standard", "Hardcore", "Solo Self-Found", "Hardcore SSF"}
            # Extract phrases that look like league names (title-case words with spaces)
            candidates = set(re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", txt))
            for name in sorted(candidates, key=lambda s: (-len(s), s)):
                if name not in permanent:
                    return name
        except Exception as e:
            log.warning("Failed to detect current league: %s", e)
        return None
