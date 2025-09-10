#!/usr/bin/env python3
from __future__ import annotations

import logging
import re
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

# IMPORTANT: use models from the project (tests expect these)
from poe2craft.models import Currency, Essence, ItemClass, Omen, BaseItem
# Cache is optional; tests do not require it, but keep import path correct if used
from poe2craft.util.cache import SimpleCache  # noqa: F401 (kept for compatibility)

LOG = logging.getLogger(__name__)

BASE = "https://poe2db.tw"
HEADERS = {
    "User-Agent": "poe2craft/0.1 (research tool; polite)",
}

# Default slugs for CLI “all/base-items” (pluralized, valid pages)
DEFAULT_BASE_SLUGS = ["Bows", "Boots", "Gloves", "Helmets", "Body_Armours", "Quivers"]


class Poe2DBClient:
    """
    PoE2DB scraper (US English).
    Parsers here are tuned to the test fixtures and are reasonably robust for the live site.
    """

    def __init__(self, session: Optional[requests.Session] = None, cache: Optional[object] = None, delay_s: float = 0.0):
        # NOTE: we accept cache but do not require it (tests monkeypatch Poe2DBClient() zero-arg)
        self.sess = session or requests.Session()
        self.sess.headers.update(HEADERS)
        self._cache = {}  # tiny in-proc cache (string URL -> text)
        self.delay_s = delay_s

    # --------------- HTTP helpers ---------------

    def _get(self, url: str) -> str:
        if url in self._cache:
            return self._cache[url]
        LOG.debug("GET %s", url)
        r = self.sess.get(url, timeout=20)
        r.raise_for_status()
        text = r.text
        self._cache[url] = text
        if self.delay_s:
            time.sleep(self.delay_s)
        return text

    def _soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self._get(url), "html.parser")

    # --------------- Parsers ---------------

    def fetch_stackable_currency(self) -> List[Currency]:
        """
        Parse https://poe2db.tw/us/Stackable_Currency.
        Strategy: iterate <a> anchors that look like real items, then scan a few following <div>s
        for 'Stack Size:' and a short description. This matches the test HTML fixtures closely.
        """
        url = f"{BASE}/us/Stackable_Currency"
        soup = self._soup(url)
        results: List[Currency] = []

        anchors = soup.find_all("a", href=True)
        seen = set()
        for a in anchors:
            name = a.get_text(strip=True)
            href = a.get("href", "")
            if not name or not href.startswith("/us/"):
                continue
            if name in {"Reset", "Edit"}:
                continue

            # Look for a near sibling div containing "Stack Size"
            stack_div = self._find_next_div(a, pattern=r"Stack Size:\s*\d+\s*/\s*\d+", max_steps=3)
            if not stack_div:
                continue

            stack_size = None
            m = re.search(r"Stack Size:\s*(\d+\s*/\s*\d+)", stack_div.get_text(" ", strip=True), flags=re.I)
            if m:
                stack_size = m.group(1)

            # Description is typically the next non-stack-size div
            desc_div = self._find_next_div(stack_div, skip_if_contains="Stack Size:", max_steps=2)
            desc = desc_div.get_text(" ", strip=True) if desc_div else ""

            # Min modifier level can be read from the detail page (best-effort)
            min_mod_level = None
            try:
                detail_html = self._get(urljoin(BASE, href))
                mm = re.search(r"Minimum Modifier Level\D+(\d+)", detail_html, re.I)
                if mm:
                    min_mod_level = int(mm.group(1))
            except Exception:
                pass

            if name in seen:
                continue
            seen.add(name)
            results.append(
                Currency(
                    name=name,
                    stack_size=stack_size,
                    description=desc or None,
                    min_modifier_level=min_mod_level,
                    meta={},
                )
            )
            if len(results) > 200:  # guard
                break

        return results

    def _find_next_div(self, node: Tag, pattern: Optional[str] = None, skip_if_contains: Optional[str] = None, max_steps: int = 6) -> Optional[Tag]:
        steps = 0
        sib = node
        while steps < max_steps:
            sib = sib.find_next_sibling()
            if sib is None:
                return None
            if isinstance(sib, Tag) and sib.name == "div":
                txt = sib.get_text(" ", strip=True)
                if skip_if_contains and skip_if_contains in txt:
                    steps += 1
                    continue
                if pattern:
                    if re.search(pattern, txt, flags=re.I):
                        return sib
                else:
                    return sib
            steps += 1
        return None

    def fetch_omens(self) -> List[Omen]:
        """
        Parse https://poe2db.tw/us/Omen.
        Accept anchors with '/us/...' and text that looks like an Omen entry; extract a nearby description.
        """
        url = f"{BASE}/us/Omen"
        soup = self._soup(url)
        out: List[Omen] = []

        anchors = soup.find_all("a", href=True)
        seen = set()
        for a in anchors:
            href = a.get("href", "")
            if "/us/" not in href:
                continue
            name = a.get_text(strip=True)
            if not name or name in {"Reset", "Edit"}:
                continue
            if name in seen:
                continue
            seen.add(name)

            # Find a brief description after the anchor
            desc_div = self._find_next_div(a, skip_if_contains="Stack Size:", max_steps=4)
            desc = desc_div.get_text(" ", strip=True) if desc_div else ""
            if not desc:
                continue

            stack = None
            stack_div = self._find_next_div(a, pattern=r"Stack Size:\s*\d+\s*/\s*\d+", max_steps=3)
            if stack_div:
                m = re.search(r"Stack Size:\s*(\d+\s*/\s*\d+)", stack_div.get_text(" ", strip=True), flags=re.I)
                if m:
                    stack = m.group(1)

            out.append(Omen(name=name, description=desc, stack_size=stack))
            if len(out) > 150:
                break

        return out

    def fetch_essences(self) -> List[Essence]:
        """
        Parse https://poe2db.tw/us/Essence.
        Filter out known navigation/summary anchors and collect likely essence entries.
        """
        url = f"{BASE}/us/Essence"
        soup = self._soup(url)
        out: List[Essence] = []

        reject_terms = {" /", "Ref", "Stash Tab", "Acronym", "Essences", "Chance"}
        anchors = soup.find_all("a", href=True)
        seen = set()
        for a in anchors:
            name = a.get_text(strip=True)
            href = a.get("href", "")
            if not name or "/us/" not in href:
                continue
            if any(term in name for term in reject_terms):
                continue
            if "Essence" not in name:
                continue
            if name in seen:
                continue
            seen.add(name)

            tier = None
            m = re.match(r"(Lesser|Greater|Perfect)\s+Essence", name, re.I)
            if m:
                tier = m.group(1).title()

            desc_div = self._find_next_div(a, skip_if_contains="Stack Size:", max_steps=3)
            desc = desc_div.get_text(" ", strip=True) if desc_div else ""

            out.append(Essence(name=name, tier=tier, description=desc, targets=[]))
            if len(out) > 300:
                break

        return out

    def fetch_base_items(self, item_class_page_slug: str) -> List[BaseItem]:
        """
        Parse a base-item listing page (e.g., 'Bows', 'Helmets', 'Body_Armours', 'Boots', 'Gloves', 'Quivers').
        """
        url = f"{BASE}/us/{item_class_page_slug}"
        soup = self._soup(url)
        out: List[BaseItem] = []

        anchors = soup.find_all("a", href=True)
        for a in anchors:
            name = a.get_text(strip=True)
            href = a.get("href", "")
            if not name or not href.startswith("/us/"):
                continue
            # Look ahead for a small block with known base-item properties; this filters nav
            divs: List[str] = []
            sib = a
            for _ in range(10):
                sib = sib.find_next_sibling()
                if sib is None:
                    break
                if isinstance(sib, Tag) and sib.name == "div":
                    divs.append(sib.get_text(" ", strip=True))
                if isinstance(sib, Tag) and sib.name == "a":
                    break

            block = " ".join(divs)
            if not any(k in block for k in ("Physical Damage", "Evasion Rating", "Energy Shield", "Requires:")):
                continue

            props: Dict[str, object] = {}
            reqs: Dict[str, object] = {}

            m_phys = re.search(r"Physical Damage:\s*([0-9]+-?[0-9]*)", block, re.I)
            if m_phys:
                props["Physical Damage"] = m_phys.group(1)
            m_crit = re.search(r"Critical Hit Chance:\s*([0-9.]+)%", block, re.I)
            if m_crit:
                try:
                    props["Critical Hit Chance"] = float(m_crit.group(1))
                except ValueError:
                    pass
            m_aps = re.search(r"Attacks per Second:\s*([0-9.]+)", block, re.I)
            if m_aps:
                try:
                    props["Attacks per Second"] = float(m_aps.group(1))
                except ValueError:
                    pass
            m_ev = re.search(r"Evasion Rating:\s*([0-9]+)", block, re.I)
            if m_ev:
                props["Evasion Rating"] = int(m_ev.group(1))

            m_req = re.search(r"Requires:\s*Level\s*([0-9]+)(?:,\s*(Str|Dex|Int)\s*([0-9]+))?", block, re.I)
            if m_req:
                reqs["Level"] = int(m_req.group(1))
                if m_req.group(2) and m_req.group(3):
                    reqs[m_req.group(2).title()] = int(m_req.group(3))

            ic = self._infer_item_class_from_slug(item_class_page_slug)
            out.append(BaseItem(name=name, item_class=ic, reqs=reqs, properties=props))

        # de-dup by name
        uniq: Dict[str, BaseItem] = {}
        for b in out:
            if b.name not in uniq:
                uniq[b.name] = b
        return list(uniq.values())

    def _infer_item_class_from_slug(self, slug: str) -> ItemClass:
        s = slug.lower()
        if "bow" in s:
            return ItemClass.BOW
        if "boots" in s:
            return ItemClass.BOOTS
        if "gloves" in s:
            return ItemClass.GLOVES
        if "helmet" in s:
            return ItemClass.HELMET
        if "body" in s or "armour" in s or "armor" in s:
            return ItemClass.BODY_ARMOUR
        if "quiver" in s:
            return ItemClass.QUIVER
        return ItemClass.UNKNOWN
