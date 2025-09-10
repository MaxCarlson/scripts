#!/usr/bin/env python3
from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from poe2craft.models import Currency, Essence, ItemClass, Omen, BaseItem, Modifier, AffixType
from poe2craft.util.cache import SimpleCache

LOG = logging.getLogger(__name__)

BASE = "https://poe2db.tw"
HEADERS = {
    "User-Agent": "poe2craft/0.1 (+https://example.local; research use; polite rate limiting)"
}


class Poe2DBClient:
    """
    Lightweight PoE2DB scraper (US English locale by default).
    It scrapes *public* pages we verified exist for PoE2:

      - Stackable Currency list & per-item pages
      - Omens list
      - Essences list (guaranteed-mod descriptions)
      - Base items (e.g., Bows page) — basic props + implicits text

    All requests go through a small on-disk cache to avoid repeated hits.
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
        """
        Scrapes the Stackable Currency grid for name/description/stack size,
        and enriches with min modifier level when present.
        """
        url = f"{BASE}/us/Stackable_Currency"
        soup = self._soup(url)
        # Strategy: iterate through images + following name anchors and text blocks
        results: List[Currency] = []

        # The page repeats blocks that look like:
        # [Image] [Name link]  "Stack Size: 1 / 20"  [Optional "Minimum Modifier Level: 50"]  [Description lines]
        # We'll parse by looking for anchors that link to detail pages and are immediately followed by text nodes.
        content = soup.get_text("\n", strip=False)

        # A more robust method: iterate anchors in the currency section:
        # The section anchor text "Stackable Currency Item" is present, so slice the document.
        header = soup.find(string=re.compile(r"Stackable Currency Item", re.I))
        if not header:
            LOG.warning("Stackable Currency section not found, page structure may have changed.")
            return results

        # find all links below header to detail pages (they tend to be /us/<Name_with_underscores>)
        anchors = header.find_all_next("a", href=True)
        visited = set()
        for a in anchors:
            name = a.get_text(strip=True)
            href = a["href"]
            if not name or not href or not href.startswith("/us/"):
                continue
            # skip non-currency categories; Currency pages tend to have Stack Size on their detail pages
            if name in visited:
                continue
            visited.add(name)

            # Fetch the immediate context text block to grab Stack Size & description on the list page
            # We will also visit detail page to capture "key val" meta if available.
            stack_size = None
            desc = None
            # Heuristic: search forward for "Stack Size:" lines
            ctx = a.find_parent()
            txt_block = []
            # Accumulate next ~6 siblings' text to find size/min level/description
            sib = a.parent
            hops = 0
            while sib and hops < 6:
                if getattr(sib, "get_text", None):
                    txt_block.append(sib.get_text(" ", strip=True))
                sib = sib.next_sibling
                hops += 1
            block = " ".join(txt_block)
            m_size = re.search(r"Stack Size:\s*([0-9]+)\s*/\s*([0-9]+)", block, flags=re.I)
            if m_size:
                # we only care about the max stack size (the second number)
                stack_size = int(m_size.group(2))
            # remove noisy repeated phrasing
            desc = self._first_sentence_after(a)

            # Enrich from detail page
            meta, min_mod_level = self._currency_detail_meta(urljoin(BASE, href))
            cur = Currency(name=name, stack_size=stack_size, description=desc, min_modifier_level=min_mod_level, meta=meta)
            # Filter obvious non-currency entries by requiring either description or meta
            if desc or meta:
                results.append(cur)

            # Stop once we hit other sections (essences/splinters/catalysts are separate calls)
            if len(results) > 0 and len(results) > 70:
                # 73 on the page at time of writing; leave some slack
                break

        # Deduplicate by name while preserving first occurrence
        uniq: Dict[str, Currency] = {}
        for c in results:
            if c.name not in uniq:
                uniq[c.name] = c
        return list(uniq.values())

    def _first_sentence_after(self, link_tag) -> Optional[str]:
        """
        Attempt to capture a brief description line that follows the anchor on list pages.
        """
        # Find the next <br> or next tag that contains a sentence.
        node = link_tag.parent
        collected = []
        # Gather limited next siblings
        for _ in range(5):
            if not node:
                break
            node = node.next_sibling
            if not node:
                break
            text = getattr(node, "get_text", lambda *a, **k: "")(" ", strip=True)
            if text:
                collected.append(text)
            if "Stack Size:" in text:
                # description may be on next sibling(s)
                continue
            if len(" ".join(collected)) > 10:
                break
        out = " ".join(collected).strip() or None
        if out:
            # trim repeated phrases like "Stack Size ..." at front
            out = re.sub(r"^Stack Size:\s*\d+\s*/\s*\d+\s*", "", out, flags=re.I).strip()
        return out or None

    def _currency_detail_meta(self, detail_url: str) -> Tuple[Dict[str, str], Optional[int]]:
        """
        For /us/<Currency_Name> pages, capture the small 'key val' meta table if present and
        parse 'Minimum Modifier Level' if shown on list/detail pages.
        """
        soup = self._soup(detail_url)
        meta: Dict[str, str] = {}
        min_level = None
        # capture stack size & min modifier level if present
        text = soup.get_text("\n", strip=True)
        m_min = re.search(r"Minimum Modifier Level\D+(\d+)", text, re.I)
        if m_min:
            min_level = int(m_min.group(1))

        # Parse the small "key val" table (appears under headings like Chance Shard etc.)
        # Look for the 'key val' phrase and then parse table-ish following lines
        kv_anchor = soup.find(string=re.compile(r"key\s+val", re.I))
        if kv_anchor:
            # The immediate following block has key/value rows until the edit/footer.
            # We'll walk next elements and extract "key value" pairs separated by whitespace.
            for row in kv_anchor.find_all_next():
                if row.name == "a" and "Edit" in row.get_text():
                    break
                txt = row.get_text(" ", strip=True)
                if not txt:
                    continue
                # stop if we reach site footer
                if "Wikis Content is available under" in txt:
                    break
                # naive split on colon or spaces
                if ":" in txt:
                    # e.g., "DropLevel: 1"
                    k, v = txt.split(":", 1)
                    meta[k.strip()] = v.strip()
                else:
                    # allow 'Base.tag currency, default' style lines
                    parts = txt.split(None, 1)
                    if len(parts) == 2 and parts[0][0].isupper():
                        meta[parts[0]] = parts[1]

        return meta, min_level

    def fetch_omens(self) -> List[Omen]:
        url = f"{BASE}/us/Omen"
        soup = self._soup(url)
        text = soup.get_text("\n", strip=False)
        # Omens are listed with repeating pattern: [Name] "Stack Size: ..." followed by description lines.
        out: List[Omen] = []
        # find the "Omens are Currency items..." section and iterate anchors
        header = soup.find(string=re.compile(r"Omens are Currency items", re.I))
        if not header:
            header = soup.find(string=re.compile(r"Omens", re.I))
        anchors = header.find_all_next("a", href=True) if header else soup.find_all("a", href=True)
        seen = set()
        for a in anchors:
            name = a.get_text(strip=True)
            href = a["href"]
            if not name or not href.startswith("/us/"):
                continue
            if name in seen:
                continue
            seen.add(name)
            # collect stack size and description from sibling text
            desc = self._first_sentence_after(a)
            stack = None
            ctx = a.parent.get_text(" ", strip=True) if a.parent else ""
            m = re.search(r"Stack Size:\s*\d+\s*/\s*(\d+)", ctx, flags=re.I)
            if m:
                stack = int(m.group(1))
            if desc:
                out.append(Omen(name=name, description=desc, stack_size=stack))
            if len(out) > 44:  # ~44 items reported currently
                break
        # de-dup
        uniq: Dict[str, Omen] = {}
        for o in out:
            if o.name not in uniq:
                uniq[o.name] = o
        return list(uniq.values())

    def fetch_essences(self) -> List[Essence]:
        url = f"{BASE}/us/Essence"
        soup = self._soup(url)
        # Entries appear with "[Tier] Essence of X" then description lines
        out: List[Essence] = []
        anchors = soup.find_all("a", href=True)
        for a in anchors:
            name = a.get_text(strip=True)
            if not name or "Essence" not in name:
                continue
            # Description often lives in following siblings
            desc = self._first_sentence_after(a) or ""
            tier = None
            m = re.match(r"(Lesser|Perfect)\s+(Essence.*)", name, re.I)
            if m:
                tier = m.group(1).title()
            out.append(Essence(name=name, tier=tier, description=desc))
            if len(out) > 81:  # reported ~81 essences
                break
        # dedupe
        seen = set()
        uniq: List[Essence] = []
        for e in out:
            if e.name in seen:
                continue
            seen.add(e.name)
            uniq.append(e)
        return uniq

    def fetch_base_items(self, item_class_page_slug: str) -> List[BaseItem]:
        """
        Fetch base items for a given item-class page slug (e.g., 'Bows', 'Boots_dex', etc.)
        Returns parsed name, basic properties, requirements, and implicit text (if inline).
        """
        url = f"{BASE}/us/{item_class_page_slug}"
        soup = self._soup(url)
        # Strategy: the page shows a "Bows Item /N" or "Boots BaseItem /N" section; entries follow "Image + Name" then property lines.
        out: List[BaseItem] = []
        section_text = soup.get_text("\n", strip=False)
        # Collect item blocks by heuristics: anchors after "Reset" line then block texts until next image/name
        anchors = soup.find_all("a", href=True)
        for a in anchors:
            name = a.get_text(strip=True)
            if not name or name in ("Reset",):
                continue
            # Recognize a base item block by the presence of characteristic properties: "Physical Damage", "Evasion Rating", "Requires:"
            block_txt = []
            sib = a.parent
            hops = 0
            while sib and hops < 8:
                sib = sib.next_sibling
                if sib and getattr(sib, "get_text", None):
                    block_txt.append(sib.get_text(" ", strip=True))
                hops += 1
            block = " ".join(block_txt)
            if any(key in block for key in ("Physical Damage", "Evasion Rating", "Energy Shield", "Requires:")):
                props: Dict[str, any] = {}
                reqs: Dict[str, any] = {}
                # Extract properties
                m_phys = re.search(r"Physical Damage:\s*([0-9]+-?[0-9]*)", block, re.I)
                if m_phys:
                    props["Physical Damage"] = m_phys.group(1)
                m_crit = re.search(r"Critical Hit Chance:\s*([0-9.]+)%", block, re.I)
                if m_crit:
                    props["Critical Hit Chance"] = float(m_crit.group(1))
                m_aps = re.search(r"Attacks per Second:\s*([0-9.]+)", block, re.I)
                if m_aps:
                    props["Attacks per Second"] = float(m_aps.group(1))
                m_ev = re.search(r"Evasion Rating:\s*([0-9]+)", block, re.I)
                if m_ev:
                    props["Evasion Rating"] = int(m_ev.group(1))

                # Requirements
                m_req = re.search(r"Requires:\s*Level\s*([0-9]+).*?(Str|Dex|Int)\s*([0-9]+)?", block, re.I)
                if m_req:
                    reqs["Level"] = int(m_req.group(1))
                    attr = m_req.group(2).title()
                    val = m_req.group(3)
                    if val:
                        reqs[attr] = int(val)

                # ItemClass inference from page slug
                ic = self._infer_item_class_from_slug(item_class_page_slug)
                out.append(BaseItem(name=name, item_class=ic, reqs=reqs, properties=props))
        # de-dup
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
        if "body" in s or "armour" in s or "armors" in s:
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
