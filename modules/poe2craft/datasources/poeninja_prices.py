#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("poe2craft.datasources.poeninja")

_API = "https://poe.ninja/api/data/currencyoverview"
_FALLBACK_PAGE = "https://poe.ninja/poe2/economy/{league_slug}/currency"
_POE2_LADDERS = "https://pathofexile2.com/ladders"


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")


def _safe_json_from_response(r: requests.Response) -> Optional[dict]:
    # Some mocks don't implement .json(); be liberal.
    try:
        return r.json()  # type: ignore[attr-defined]
    except Exception:
        try:
            if getattr(r, "text", None):
                return json.loads(r.text)
            if getattr(r, "content", None):
                return json.loads(r.content.decode("utf-8"))
        except Exception:
            return None
    return None


def detect_active_league(session: Optional[requests.Session] = None) -> Optional[str]:
    """
    Best-effort current challenge league detection for PoE2.
    Strategy:
      1) Scrape PoE2 ladders page and pick the first non-permanent league name.
      2) If that fails, try to infer a league-like phrase from the page text.
      3) Else None.
    """
    sess = session or requests.Session()
    try:
        r = sess.get(_POE2_LADDERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        txt = soup.get_text(" ", strip=True)
        # These are permanent; skip them.
        permanent = {"Standard", "Hardcore", "Solo Self-Found", "Hardcore SSF"}
        # Find capitalized phrases (2+ words) that look like a league name.
        candidates = set(re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", txt))
        for name in sorted(candidates, key=lambda s: (-len(s), s)):
            if name not in permanent and len(name) >= 6:
                return name
    except Exception as e:
        log.debug("active league detection failed: %s", e)
    return None


class PoENinjaPriceProvider:
    """
    Currency prices for PoE2 via poe.ninja.
    - Primary: official API
    - Fallback: scrape economy page __NEXT_DATA__ blob
    """

    def __init__(self, session: Optional[requests.Session] = None, timeout: float = 15.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def get_currency_prices(self, league: str = "Standard") -> Dict[str, float]:
        # 1) API path
        params = {"league": league, "type": "Currency", "game": "poe2", "language": "en"}
        try:
            r = self.session.get(_API, params=params, timeout=self.timeout)
            data = _safe_json_from_response(r)
            if data and isinstance(data, dict):
                out: Dict[str, float] = {}
                for line in data.get("lines", []):
                    name = line.get("currencyTypeName")
                    val = None
                    rec = line.get("receive")
                    if isinstance(rec, dict) and isinstance(rec.get("value"), (int, float)):
                        val = rec["value"]
                    if val is None and isinstance(line.get("chaosEquivalent"), (int, float)):
                        val = line["chaosEquivalent"]
                    if name and isinstance(val, (int, float)):
                        out[name] = float(val)
                if out:
                    return out
        except Exception as e:
            log.info("poe.ninja API error: %s", e)

        # 2) Fallback: scrape economy page
        league_slug = _slugify(league)
        url = _FALLBACK_PAGE.format(league_slug=league_slug)
        try:
            r = self.session.get(url, timeout=self.timeout)
            soup = BeautifulSoup(r.text, "html.parser")
            blob = soup.find("script", id="__NEXT_DATA__")
            if not blob or not blob.string:
                log.warning("Could not find embedded JSON on %s; returning empty price map", url)
                return {}
            try:
                j = json.loads(blob.string)
                page_props = ((j.get("props") or {}).get("pageProps") or {})
                arr = page_props.get("data") or page_props.get("items") or []
                out: Dict[str, float] = {}
                for it in arr:
                    n = it.get("name") or it.get("currencyTypeName")
                    v = it.get("chaosValue")
                    if n and isinstance(v, (int, float)):
                        out[n] = float(v)
                return out
            except Exception as e:
                log.warning("Error parsing __NEXT_DATA__ on %s: %s", url, e)
                return {}
        except Exception as e:
            log.info("poe.ninja economy fallback failed for %s: %s", url, e)
        return {}
