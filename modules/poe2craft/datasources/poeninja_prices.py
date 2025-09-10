#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional

import requests

from poe2craft.util.cache import SimpleCache

LOG = logging.getLogger(__name__)

NINJA_WEB_BASE = "https://poe.ninja"
NINJA_POE2_ECON = NINJA_WEB_BASE + "/poe2/economy/{league}/{category}"  # e.g., league="standard", category="currency"


class PoENinjaPriceProvider:
    """
    Fetch PoE2 economy data from poe.ninja.
    Strategy:
      1) Try documented-style API (with a 'game' dimension) if available in future.
      2) Fallback: scrape the economy page and extract embedded JSON/state.

    NOTE: We intentionally do NOT cache JSON API responses to avoid test cross-talk
    and stale data. We cache only HTML pages.
    """

    def __init__(self, session: Optional[requests.Session] = None, cache: Optional[SimpleCache] = None):
        self.sess = session or requests.Session()
        # Cache only used for HTML pages
        self.cache = cache or SimpleCache(ttl_seconds=3600)

    def get_currency_prices(self, league: str = "Standard") -> Dict[str, float]:
        api_url = f"{NINJA_WEB_BASE}/api/data/currencyoverview?league={league.title()}&type=Currency&game=poe2"
        try:
            data = self._get_json_nocache(api_url)
            if data and "lines" in data:
                out: Dict[str, float] = {}
                for line in data["lines"]:
                    name = line.get("currencyTypeName")
                    chaos_eq = None
                    receive = line.get("receive", {})
                    if isinstance(receive, dict):
                        val = receive.get("value")
                        if isinstance(val, (int, float)) and val > 0:
                            chaos_eq = val
                    if name and chaos_eq:
                        out[name] = float(chaos_eq)
                if out:
                    return out
        except Exception as e:
            LOG.debug("Currency API probe failed: %s", e)

        # Fallback to page scrape
        return self._scrape_currency_page(league)

    # -------------- internals --------------

    def _get_json_nocache(self, url: str) -> Optional[dict]:
        r = self.sess.get(url, timeout=20)
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("application/json"):
            raise RuntimeError(f"Non-JSON or bad status from {url}")
        return r.json()

    def _scrape_currency_page(self, league: str) -> Dict[str, float]:
        # Fetch economy page and try to extract a JSON blob (many modern sites embed app state in a script tag).
        url = NINJA_POE2_ECON.format(league=league.lower(), category="currency")
        cached = self.cache.get(url)
        if cached is not None:
            html = cached.decode("utf-8")
        else:
            r = self.sess.get(url, timeout=20)
            r.raise_for_status()
            html = r.text
            self.cache.put(url, html.encode("utf-8"))

        blob = self._extract_json_like_blob(html)
        if not blob:
            LOG.warning("Could not find embedded JSON on %s; returning empty price map", url)
            return {}
        prices: Dict[str, float] = {}
        # Attempt common shapes
        for item in self._walk_json_for_objects(blob):
            name = item.get("name") or item.get("currencyTypeName")
            val = item.get("chaosValue")
            if val is None and isinstance(item.get("receive"), dict):
                val = item["receive"].get("value")
            if name and isinstance(val, (int, float)):
                prices[name] = float(val)
        return prices

    def _extract_json_like_blob(self, html: str) -> Optional[dict]:
        # __NEXT_DATA__ pattern
        m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html, flags=re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        # window.__NUXT__ pattern
        m = re.search(r"window\.__NUXT__\s*=\s*(\{.*?\});", html, flags=re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        # Generic big JSON fallback
        m = re.search(r"(\{[^<>{}]{200,}\})", html, flags=re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        return None

    def _walk_json_for_objects(self, root: dict) -> List[dict]:
        out: List[dict] = []

        def rec(v):
            if isinstance(v, dict):
                out.append(v)
                for vv in v.values():
                    rec(vv)
            elif isinstance(v, list):
                for vv in v:
                    rec(vv)

        rec(root)
        return out
