#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger("poe2craft.datasources.poeninja")

_API_CURRENCY = "https://poe.ninja/api/data/currencyoverview"
_FALLBACK_PAGE = "https://poe.ninja/poe2/economy/{league_slug}/currency"
_POE2_LADDERS = "https://pathofexile2.com/ladders"
_POE2_ROOT = "https://poe.ninja/poe2"


def _slugify_league(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    return s


def detect_active_league(session: Optional[requests.Session] = None) -> Optional[str]:
    """
    Best-effort current league detection:
      1) pathofexile2.com/ladders – pick first non-permanent league name.
      2) poe.ninja/poe2 – parse economy link slug and de-slug.
    """
    sess = session or requests.Session()
    permanent = {"Standard", "Hardcore", "Solo Self-Found", "Hardcore SSF"}

    try:
        r = sess.get(_POE2_LADDERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        txt = soup.get_text(" ", strip=True)
        candidates = set(re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", txt))
        for name in sorted(candidates, key=lambda s: (-len(s), s)):
            if name not in permanent:
                return name
    except Exception as e:
        LOG.debug("League detect (ladders) failed: %s", e)

    try:
        r = sess.get(_POE2_ROOT, timeout=12)
        r.raise_for_status()
        m = re.search(r"/poe2/economy/([a-z0-9\-]+)/currency", r.text, flags=re.I)
        if m:
            slug = m.group(1)
            return " ".join(w.capitalize() for w in slug.split("-"))
    except Exception as e:
        LOG.debug("League detect (ninja) failed: %s", e)

    return None


class PoENinjaPriceProvider:
    """
    PoE2 currency prices via poe.ninja.
    Primary: JSON API
    Fallback: scrape economy page __NEXT_DATA__.
    """

    def __init__(self, session: Optional[requests.Session] = None, cache: Optional[object] = None):
        self.sess = session or requests.Session()

    def get_currency_prices(self, league: str = "Standard") -> Dict[str, float]:
        # API path
        try:
            params = {"league": league, "type": "Currency", "language": "en"}
            r = self.sess.get(_API_CURRENCY, params=params, timeout=20)
            ct = (r.headers.get("content-type") or "").lower()
            if r.status_code == 200 and "application/json" in ct:
                data = r.json()
                out: Dict[str, float] = {}
                for line in data.get("lines", []):
                    name = line.get("currencyTypeName")
                    val = None
                    rec = line.get("receive") or {}
                    if isinstance(rec, dict) and isinstance(rec.get("value"), (int, float)):
                        val = rec["value"]
                    if val is None and isinstance(line.get("chaosEquivalent"), (int, float)):
                        val = line["chaosEquivalent"]
                    if name and isinstance(val, (int, float)):
                        out[name] = float(val)
                if out:
                    return out
        except Exception as e:
            LOG.debug("poe.ninja API failed: %s", e)

        # Fallback via economy page
        try:
            slug = _slugify_league(league)
            url = _FALLBACK_PAGE.format(league_slug=slug)
            r = self.sess.get(url, timeout=20)
            if r.status_code != 200:
                return {}
            soup = BeautifulSoup(r.text, "html.parser")
            node = soup.find("script", id="__NEXT_DATA__")
            if not node or not node.string:
                LOG.warning("Could not find embedded JSON on %s; returning empty price map", url)
                return {}
            blob = json.loads(node.string)
            page_props = ((blob.get("props") or {}).get("pageProps") or {})
            arr = page_props.get("data") or page_props.get("items") or []
            out: Dict[str, float] = {}
            for it in arr:
                name = it.get("name")
                val = it.get("chaosValue")
                if name and isinstance(val, (int, float)):
                    out[name] = float(val)
            return out
        except Exception as e:
            LOG.warning("poe.ninja fallback failed: %s", e)

        return {}
