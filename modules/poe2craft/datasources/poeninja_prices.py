# File: poe2craft/datasources/poeninja_prices.py
from __future__ import annotations

import logging
import os
import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger("poe2craft.datasources.poeninja")

_POE2_ROOT = "https://poe.ninja/poe2"
_API_BASE = "https://poe.ninja/api/data"


def _slugify_league(name: str) -> str:
    return name.strip().lower().replace(" ", "-")


def _env_or_settings_default() -> Optional[str]:
    """
    Escape hatch when front page parsing changes. Tests or callers can set POE2_LEAGUE.
    """
    env = os.getenv("POE2_LEAGUE")
    if env:
        return env
    return None


def detect_active_league(session: Optional[requests.Session] = None) -> Optional[str]:
    """
    Heuristic: read poe.ninja/poe2 landing for a /poe2/economy/<slug>/currency link
    and return a display name ("Slug Words") for the current economy.
    """
    sess = session or requests.Session()
    try:
        r = sess.get(_POE2_ROOT, timeout=10)
        r.raise_for_status()
        m = re.search(r"/poe2/economy/([a-z0-9\-]+)/currency", r.text, flags=re.I)
        if m:
            slug = m.group(1)
            disp = " ".join(w.capitalize() for w in slug.split("-"))
            return disp
    except Exception as e:
        LOG.debug("Active league detection failed: %s", e)
    return _env_or_settings_default()


class PoENinjaPriceProvider:
    """
    Tiny wrapper for poe.ninja price endpoints we use in tests/CLI.
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    def fetch_prices(self, league: str) -> Dict[str, float]:
        """
        Pulls a merged map of currency-like prices for the given league.
        We primarily need a dense currency set; item classes can be added similarly.
        """
        league_slug = _slugify_league(league)
        prices: Dict[str, float] = {}

        # Currency overview
        cur_url = f"{_API_BASE}/currencyoverview?league={league_slug}&type=Currency"
        try:
            data = self._json(cur_url)
            for line in data.get("lines", []):
                n = line.get("currencyTypeName") or line.get("typeLine")
                val = None
                # prefer gold-equivalent
                chaos_equiv = (line.get("receive", {}) or {}).get("value")
                if chaos_equiv is None:
                    chaos_equiv = (line.get("pay", {}) or {}).get("value")
                # poe2 uses Gold, but poe.ninja returns its standard "chaos" field name in many places;
                # treat it as our base unit either way.
                val = chaos_equiv
                if n and isinstance(val, (int, float)):
                    prices[n] = float(val)
        except Exception as e:
            LOG.debug("currencyoverview failed: %s", e)

        # Item categories we often treat as currency-like (e.g., Catalysts, etc.)
        for type_name in ("Fragment", "Oil", "Incubator", "Fossil", "Resonator", "Scarab", "DeliriumOrb"):
            url = f"{_API_BASE}/itemoverview?league={league_slug}&type={type_name}"
            try:
                data = self._json(url)
                for line in data.get("lines", []):
                    n = line.get("name") or line.get("typeLine")
                    val = line.get("chaosValue") or line.get("goldValue")
                    if n and isinstance(val, (int, float)):
                        prices[n] = float(val)
            except Exception:
                # Not all categories are always present for PoE2; ignore missing.
                continue

        return prices

    # ------------------ http helpers ------------------
    def _json(self, url: str) -> dict:
        r = self.session.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
