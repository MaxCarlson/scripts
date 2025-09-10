#!/usr/bin/env python3
import json
import logging
import re
from typing import Dict, Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger("poe2craft.datasources.poeninja")

_API_CURRENCY = "https://poe.ninja/api/data/currencyoverview"
_FALLBACK_PAGE = "https://poe.ninja/poe2/economy/{league_slug}/currency"
_POE2_ROOT = "https://poe.ninja/poe2"


def _slugify_league(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    return s


def detect_active_league(session: Optional[requests.Session] = None) -> Optional[str]:
    """Best-effort: find an economy link on poe.ninja/poe2 and un-slug its display name."""
    sess = session or requests.Session()
    try:
        r = sess.get(_POE2_ROOT, timeout=12)
        r.raise_for_status()
        m = re.search(r"/poe2/economy/([a-z0-9\-]+)/currency", r.text, flags=re.I)
        if m:
            slug = m.group(1)
            return " ".join(w.capitalize() for w in slug.split("-"))
    except Exception as e:
        LOG.debug("Active league detection failed: %s", e)
    return None


class PoENinjaPriceProvider:
    """Currency prices for PoE2 via poe.ninja."""

    def __init__(self, session: Optional[requests.Session] = None, timeout: float = 12.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def get_currency_prices(self, league: str = "Standard") -> Dict[str, float]:
        """
        Priority:
        1) JSON API -> lines[].receive.value (preferred) or chaosEquivalent
        2) Fallback scrape __NEXT_DATA__ from the economy page
        """
        # Build URL (tests' _SessionMock.get() doesn't accept params=)
        api_url = f"{_API_CURRENCY}?league={quote_plus(league)}&type=Currency&game=poe2"
        try:
            r = self.session.get(api_url, timeout=self.timeout)
            data = None
            ct = (r.headers.get("content-type") or "").lower()
            if "application/json" in ct:
                try:
                    data = r.json()
                except Exception:
                    try:
                        data = json.loads(getattr(r, "text", "") or getattr(r, "content", b"").decode("utf-8"))
                    except Exception:
                        data = None
            if data and "lines" in data:
                out: Dict[str, float] = {}
                for line in data["lines"]:
                    name = line.get("currencyTypeName")
                    val = None
                    recv = line.get("receive")
                    if isinstance(recv, dict) and isinstance(recv.get("value"), (int, float)):
                        val = recv["value"]
                    if val is None and isinstance(line.get("chaosEquivalent"), (int, float)):
                        val = line["chaosEquivalent"]
                    if name and isinstance(val, (int, float)):
                        out[name] = float(val)
                if out:
                    return out
        except Exception as e:
            LOG.warning("poe.ninja API error: %s", e)

        # Fallback: scrape economy page
        league_slug = _slugify_league(league)
        url = _FALLBACK_PAGE.replace("{league_slug}", league_slug)
        try:
            r = self.session.get(url, timeout=self.timeout)
            ct = (r.headers.get("content-type") or "").lower()
            if "text/html" in ct:
                soup = BeautifulSoup(r.text, "html.parser")
                blob = soup.find("script", id="__NEXT_DATA__")
                if not blob or not blob.string:
                    LOG.warning("Could not find embedded JSON on %s; returning empty price map", url)
                    return {}
                try:
                    j = json.loads(blob.string)
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
                    LOG.warning("Error parsing __NEXT_DATA__ on %s: %s", url, e)
                    return {}
        except Exception as e:
            LOG.warning("poe.ninja economy fallback failed for %s: %s", url, e)

        return {}
