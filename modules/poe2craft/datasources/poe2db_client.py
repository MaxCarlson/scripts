#!/usr/bin/env python3
from __future__ import annotations

import logging
import re
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from poe2craft.models import Currency, Essence, ItemClass, Omen, BaseItem
from poe2craft.util.cache import SimpleCache

LOG = logging.getLogger(__name__)

BASE = "https://poe2db.tw"
HEADERS = {
    "User-Agent": "poe2craft/0.1 (+https://example.local; research use; polite rate limiting)"
}


class Poe2DBClient:
    """
    PoE2DB scraper (US English locale).
    Scrapes:
      - Stackable Currency
      - Omens
      - Essences
      - Base items for a given class-page slug (e.g., 'Bows', 'Boots_dex')
    """

    def __init__(self, session: Optional[requests.Session] = None, cache: Optional[SimpleCache] = None, delay_s: float = 0.8):
        self.sess = session or requests.Session()
        self.sess.headers.update(HEADERS)
        self.cache = cache or SimpleCache()
        self.delay_s = delay_s

    # --------------- HTTP helpers ---------------

    def _get(self, url: str) -> str:
        cached = self.cache.get(url)
        if cached is not None:
            return cached.decode("utf-8")

        LOG.debug("GET %s", url)
        r = self.sess.get(url, timeout=20)
        r.raise_for_status()
        text = r.text
        self.cache.put(url, text.encode("utf-8"))
        time.sleep(self.delay_s)
        return text

    def _soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self._get(url), "html.parser")

    # --------------- Parsers ---------------

    def fetch_stackable_currency(self) -> List[Currency]:
        url = f"{BASE}/us/Stackable_Currency"
        soup = self._soup(url)
        results: List[Currency] = []

        header = soup.find(string=re.compile(r"Stackable Currency", re.I))
        anchors = header.find_all_next("a", href=True) if header else soup.find_all("a", href=True)

        seen = set()
        for a in anchors:
            name = a.get_text(strip=True)
            href = a.get("href", "")
            if not name or not href.startswith("/us/"):
                continue
            if name in seen:
                continue
            seen.add(name)

            stack_size = None
            desc = None

            stack_div = self._find_next_div(a, pattern=r"Stack Size:\s*\d+\s*/\s*(\d+)")
            if stack_div:
                m = re.search(r"Stack Size:\s*\d+\s*/\s*(\d+)", stack_div.get_text(" ", strip=True), flags=re.I)
                if m:
                    stack_size = int(m.group(1))
            desc_div = self._find_next_div(a, skip_if_contains="Stack Size:")
            if desc_div:
                desc = desc_div.get_text(" ", strip=True)

            meta, min_mod_level = self._currency_detail_meta(urljoin(BASE, href))
            cur = Currency(name=name, stack_size=stack_size, description=desc, min_modifier_level=min_mod_level, meta=meta)
            if desc or meta:
                results.append(cur)

            if len(results) > 90:
                break

        uniq: Dict[str, Currency] = {}
        for c in results:
            if c.name not in uniq:
                uniq[c.name] = c
        return list(uniq.values())

    def _find_next_div(self, anchor: Tag, pattern: Optional[str] = None, skip_if_contains: Optional[str] = None) -> Optional[Tag]:
        sib = anchor
        for _ in range(10):
            sib = sib.find_next_sibling()
            if sib is None:
                return None
            if isinstance(sib, Tag) and sib.name == "div":
                txt = sib.get_text(" ", strip=True)
                if skip_if_contains and skip_if_contains in txt:
                    continue
                if pattern:
                    if re.search(pattern, txt, flags=re.I):
                        return sib
                else:
                    return sib
        return None

    def _currency_detail_meta(self, detail_url: str) -> Tuple[Dict[str, str], Optional[int]]:
        soup = self._soup(detail_url)
        meta: Dict[str, str] = {}
        min_level = None

        text = soup.get_text("\n", strip=True)
        m_min = re.search(r"Minimum Modifier Level\D+(\d+)", text, re.I)
        if m_min:
            min_level = int(m_min.group(1))

        for m in re.finditer(r"(DropLevel|Drop Level|BaseType)\s*:\s*([^\n]+)", text, flags=re.I):
            k, v = m.group(1), m.group(2).strip()
            meta[k.replace(" ", "")] = v

        return meta, min_level

    def fetch_omens(self) -> List[Omen]:
        url = f"{BASE}/us/Omen"
        soup = self._soup(url)
        out: List[Omen] = []

        header = soup.find(string=re.compile(r"Omens", re.I))
        anchors = header.find_all_next("a", href=True) if header else soup.find_all("a", href=True)
        seen = set()
        for a in anchors:
            name = a.get_text(strip=True)
            href = a.get("href", "")
            if not name or not href.startswith("/us/"):
                continue
            if name in seen:
                continue
            seen.add(name)

            stack = None
            stack_div = self._find_next_div(a, pattern=r"Stack Size:\s*\d+\s*/\s*(\d+)")
            if stack_div:
                m = re.search(r"Stack Size:\s*\d+\s*/\s*(\d+)", stack_div.get_text(" ", strip=True), flags=re.I)
                if m:
                    stack = int(m.group(1))

            desc_div = self._find_next_div(a, skip_if_contains="Stack Size:")
            desc = desc_div.get_text(" ", strip=True) if desc_div else ""

            if name and desc:
                out.append(Omen(name=name, description=desc, stack_size=stack))

            if len(out) > 60:
                break

        uniq: Dict[str, Omen] = {}
        for o in out:
            if o.name not in uniq:
                uniq[o.name] = o
        return list(uniq.values())

    def fetch_essences(self) -> List[Essence]:
        url = f"{BASE}/us/Essence"
        soup = self._soup(url)
        out: List[Essence] = []

        anchors = soup.find_all("a", href=True)
        seen = set()
        for a in anchors:
            name = a.get_text(strip=True)
            if not name or "Essence" not in name:
                continue
            if name in seen:
                continue
            seen.add(name)

            tier = None
            m = re.match(r"(Lesser|Perfect)\s+(Essence.*)", name, re.I)
            if m:
                tier = m.group(1).title()

            desc_div = self._find_next_div(a, skip_if_contains="Stack Size:")
            desc = desc_div.get_text(" ", strip=True) if desc_div else ""

            out.append(Essence(name=name, tier=tier, description=desc))
            if len(out) > 100:
                break

        return out

    def fetch_base_items(self, item_class_page_slug: str) -> List[BaseItem]:
        url = f"{BASE}/us/{item_class_page_slug}"
        soup = self._soup(url)
        out: List[BaseItem] = []

        anchors = soup.find_all("a", href=True)
        for a in anchors:
            name = a.get_text(strip=True)
            href = a.get("href", "")
            if not name or not href.startswith("/us/"):
                continue

            divs: List[str] = []
            sib = a
            for _ in range(12):
                sib = sib.find_next_sibling()
                if sib is None:
                    break
                if isinstance(sib, Tag) and sib.name == "div":
                    divs.append(sib.get_text(" ", strip=True))
                if isinstance(sib, Tag) and sib.name == "a":
                    break

            block = " ".join(divs)
            if not any(key in block for key in ("Physical Damage", "Evasion Rating", "Energy Shield", "Requires:")):
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
        if "body" in s or "armour" in s or "armor" in s or "armors" in s:
            return ItemClass.BODY_ARMOUR
        if "staff" in s:
            return ItemClass.STAFF
        if "sword" in s and "two" in s:
            return ItemClass.TWO_HAND_SWORD
        if "axe" in s and "two" in s:
            return ItemClass.TWO_HAND_AXE
        if "mace" in s and "two" in s:
            return ItemClass.TWO_HAND_MACE
        if "crossbow" in s:
            return ItemClass.CROSSBOW
        if "quiver" in s:
            return ItemClass.QUIVER
        if "ring" in s:
            return ItemClass.RING
        if "amulet" in s:
            return ItemClass.AMULET
        if "belt" in s:
            return ItemClass.BELT
        return ItemClass.UNKNOWN
