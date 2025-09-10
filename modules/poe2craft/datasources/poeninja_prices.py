#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional

import requests

from poe2craft.util.cache import InMemoryCache, SimpleCache

LOG = logging.getLogger(__name__)

NINJA_WEB_BASE = "https://poe.ninja"
NINJA_POE2_ECON = NINJA_WEB_BASE + "/poe2/economy/{league}/{category}"  # league="standard", category="currency"


class PoENinjaPriceProvider:
    """
    Fetch PoE2 economy data from poe.ninja.
    Strategy:
      1) Try JSON API (with a 'game' dimension). If that fails, fall back to scraping the economy page.
    Notes:
      - We do NOT persist API responses; only HTML pages are cached (and by default, per-process InMemoryCache
        to avoid test cross-talk). In the CLI, we pass a SimpleCache for on-disk caching.
    """

    def __init__(self, session: Optional[requests.Session] = None, cache: Optional[object] = None):
        self.sess = session or requests.Session()
        # default to a per-process cache to isolate tests; CLI will pass SimpleCache() explicitly
        self.cache = cache if cache is not None else InMemoryCache(ttl_seconds=3600)

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
                    if name and chaos_eq is not None:
                        out[name] = float(chaos_eq)
                if out:
                    return out
        except Exception as e:
            LOG.debug("Currency API probe failed: %s", e)

        return self._scrape_currency_page(league)

    # -------------- internals --------------

    def _get_json_nocache(self, url: str) -> Optional[dict]:
        r = self.sess.get(url, timeout=20)
        ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        if r.status_code != 200 or not ct.startswith("application/json"):
            raise RuntimeError(f"Non-JSON or bad status from {url}")
        # Robust JSON parsing: support mocks that don't implement Response.json()
        try:
            return r.json()  # type: ignore[attr-defined]
        except Exception:
            try:
                if getattr(r, "text", None):
                    return json.loads(r.text)
                if getattr(r, "content", None):
                    return json.loads(r.content.decode("utf-8"))
            except Exception as e:
                raise RuntimeError(f"Invalid JSON body from {url}") from e
        return None

    def _scrape_currency_page(self, league: str) -> Dict[str, float]:
        url = NINJA_POE2_ECON.format(league=league.lower(), category="currency")
        cached = self.cache.get(url)
        if cached is not None:
            html = cached.decode("utf-8")
        else:
            r = self.sess.get(url, timeout=20)
            r.raise_for_status()
            html = r.text
            # only cache HTML in the provided cache
            if isinstance(self.cache, (InMemoryCache, SimpleCache)):
                self.cache.put(url, html.encode("utf-8"))

        blob = self._extract_json_like_blob(html)
        if not blob:
            LOG.warning("Could not find embedded JSON on %s; returning empty price map", url)
            return {}
        prices: Dict[str, float] = {}
        for item in self._walk_json_for_objects(blob):
            name = item.get("name") or item.get("currencyTypeName")
            val = item.get("chaosValue")
            if val is None and isinstance(item.get("receive"), dict):
                val = item["receive"].get("value")
            if name and isinstance(val, (int, float)):
                prices[name] = float(val)
        return prices

    def _extract_json_like_blob(self, html: str) -> Optional[dict]:
        m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html, flags=re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        m = re.search(r"window\.__NUXT__\s*=\s*(\{.*?\});", html, flags=re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
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
