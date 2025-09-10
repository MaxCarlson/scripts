#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import re
from html import unescape
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
        NOTE: We construct the full URL string (not `params=`) so prefix stubs in tests still match.
        """
        api_url = f"{_API_CURRENCY}?league={league}&type=Currency&game=poe2"
        try:
            r = self.session.get(api_url, timeout=self.timeout)
            data = self._safe_json_from_response(r)
            if isinstance(data, dict) and "lines" in data:
                out: Dict[str, float] = {}
                for line in data.get("lines", []):
                    name = line.get("currencyTypeName")
                    val: Optional[float] = None
                    recv = line.get("receive")
                    if isinstance(recv, dict) and isinstance(recv.get("value"), (int, float)):
                        val = float(recv["value"])
                    elif isinstance(line.get("chaosEquivalent"), (int, float)):
                        val = float(line["chaosEquivalent"])
                    if name and isinstance(val, (int, float)):
                        out[name] = val
                if out:
                    return out
        except Exception as e:
            LOG.warning("poe.ninja API error: %s", e)

        # Fallback: scrape the economy page's __NEXT_DATA__ blob
        league_slug = _slugify_league(league)
        url = _FALLBACK_PAGE.format(league_slug=league_slug)
        try:
            r = self.session.get(url, timeout=self.timeout)
            if "text/html" in (r.headers.get("content-type") or "").lower():
                soup = BeautifulSoup(r.text, "html.parser")
                script = soup.find("script", id="__NEXT_DATA__")
                if not script or not script.string:
                    LOG.warning("Could not find embedded JSON on %s; returning empty price map", url)
                    return {}
                try:
                    blob = json.loads(unescape(script.string))
                    page_props = ((blob.get("props") or {}).get("pageProps") or {})
                    arr = page_props.get("data") or page_props.get("items") or []
                    out: Dict[str, float] = {}
                    for it in arr:
                        n = it.get("name") or it.get("currencyTypeName")
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

    def detect_current_league(self) -> Optional[str]:
        """
        Best-effort detection of the active PoE2 economy league display name.
        1) Try poe.ninja/poe2 landing page economy link.
        2) Fallback to pathofexile2 ladders page for a title-like league name.
        Returns display name (e.g., "Rise of the Abyssal") or None.
        """
        # Try poe.ninja landing
        try:
            r = self.session.get(_POE2_ROOT, timeout=self.timeout)
            r.raise_for_status()
            m = re.search(r"/poe2/economy/([a-z0-9\-]+)/currency", r.text, flags=re.I)
            if m:
                slug = m.group(1)
                disp = " ".join(w.capitalize() for w in slug.split("-"))
                return disp
        except Exception as e:
            LOG.debug("Active league detection via poe.ninja failed: %s", e)

        # Fallback: official ladders page (title-cased phrases excluding permanent modes)
        try:
            r = self.session.get(_POE2_LADDERS, timeout=self.timeout)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text(" ", strip=True)
            permanent = {"Standard", "Hardcore", "Solo Self-Found", "Hardcore SSF"}
            candidates = set(re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", text))
            for name in sorted(candidates, key=lambda s: (-len(s), s)):
                if name not in permanent:
                    return name
        except Exception as e:
            LOG.debug("Active league detection via ladders failed: %s", e)

        return None

    @staticmethod
    def _safe_json_from_response(r) -> Optional[dict]:
        # tolerate simple test doubles that don't define .json()
        try:
            if "application/json" in (r.headers.get("content-type") or "").lower():
                try:
                    return r.json()  # type: ignore[attr-defined]
                except Exception:
                    pass
            if getattr(r, "text", None):
                return json.loads(r.text)
            if getattr(r, "content", None):
                return json.loads(r.content.decode("utf-8"))
        except Exception:
            return None
        return None
