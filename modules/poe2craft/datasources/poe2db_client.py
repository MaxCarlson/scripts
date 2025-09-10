#!/usr/bin/env python3
from __future__ import annotations

import logging
import re
from dataclasses import asdict
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# Models are assumed to exist in your project as used in tests.
# We keep names/fields stable: Currency, Omen, Essence, BaseItem (or similar).
try:
    from ..models import Currency, Omen, Essence, BaseItem
except Exception:  # pragma: no cover - tests use their own fakes sometimes
    # Minimal fallbacks so the CLI can still run if models are thin.
    from dataclasses import dataclass, field

    @dataclass
    class Currency:
        name: str
        stack_size: Optional[int] = None
        description: str = ""
        min_modifier_level: Optional[int] = None
        meta: Dict[str, str] = field(default_factory=dict)

    @dataclass
    class Omen:
        name: str
        description: str = ""
        stack_size: Optional[int] = None

    @dataclass
    class Essence:
        name: str
        tier: Optional[str] = None
        description: str = ""
        targets: List[str] = None

    @dataclass
    class BaseItem:
        name: str
        item_class: str
        required_level: Optional[int] = None
        meta: Dict[str, str] = None


log = logging.getLogger("poe2craft.datasources.poe2db")

_BASE = "https://poe2db.tw"
_LOCALE = "us"

DEFAULT_BASE_SLUGS: List[str] = [
    "Bows",
    "Boots",
    "Gloves",
    "Helmets",
    "Body_Armours",
    "Quivers",
]


def _url(path: str) -> str:
    if path.startswith("http"):
        return path
    if path.startswith("/"):
        return f"{_BASE}{path}"
    return f"{_BASE}/{_LOCALE}/{path}"


_STACK_SIZE_RE = re.compile(r"Stack\s*Size:\s*(\d+)\s*/\s*(\d+)", re.I)
_MIN_MOD_LVL_RE = re.compile(r"Minimum\s+Modifier\s+Level\D+(\d+)", re.I)
_DROP_LEVEL_RE = re.compile(r"DropLevel\s+(\d+)", re.I)


class Poe2DBClient:
    """
    Robust HTML scrapers for PoE2DB (poe2db.tw) with conservative parsing:
    - Follows each item/omen/essence link and reads adjacent text blocks.
    - For currencies, also fetches the detail page to enrich metadata (DropLevel, etc).
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "user-agent": "poe2craft/0.1 (+https://github.com/your/local/tool)",
                "accept-language": "en-US,en;q=0.9",
            }
        )

    # ---------------- helpers ----------------

    def _get(self, path: str) -> str:
        url = _url(path)
        log.debug("GET %s", url)
        r = self.session.get(url, timeout=20)
        r.raise_for_status()
        return r.text

    def _soup(self, path: str) -> BeautifulSoup:
        return BeautifulSoup(self._get(path), "html.parser")

    @staticmethod
    def _text_after(anchor: Tag, max_steps: int = 80) -> str:
        """
        Gather a compact text block from elements following the given <a> until the next item anchor.
        """
        texts: List[str] = []
        steps = 0
        node = anchor
        while node is not None and steps < max_steps:
            node = node.next_element  # includes text nodes
            if node is None:
                break
            steps += 1
            # Stop if we hit another anchor that looks like a new item
            if isinstance(node, Tag) and node.name == "a" and node.get("href", "").startswith("/us/"):
                break
            if isinstance(node, NavigableString):
                t = str(node).strip()
                if t:
                    texts.append(t)
            elif isinstance(node, Tag):
                t = node.get_text(" ", strip=True)
                if t:
                    texts.append(t)
        # Join and normalize whitespace
        out = " ".join(texts)
        out = re.sub(r"\s+", " ", out)
        return out

    @staticmethod
    def _parse_stack_and_desc(block: str) -> Tuple[Optional[int], str, Optional[int]]:
        """
        From a text block, extract:
          - stack_size (max, e.g. 20 from "Stack Size: 1 / 20")
          - description (first useful line after stack size)
          - min_modifier_level (if present)
        """
        stack_size: Optional[int] = None
        m = _STACK_SIZE_RE.search(block)
        if m:
            try:
                stack_size = int(m.group(2))  # store max stack
            except Exception:
                stack_size = None

        min_mod: Optional[int] = None
        mm = _MIN_MOD_LVL_RE.search(block)
        if mm:
            try:
                min_mod = int(mm.group(1))
            except Exception:
                pass

        # Description: take first non-meta sentence-like chunk after stack text
        desc = block
        if m:
            desc = block[m.end() : ].strip()
        # Trim obvious boilerplate words
        # Keep to a reasonable length
        desc = re.sub(r"(Right click.*?unstack\.)", "", desc, flags=re.I)
        desc = desc.strip()
        # If still too long, keep the first sentence
        if ". " in desc:
            desc = desc.split(". ")[0].strip()
        return stack_size, desc, min_mod

    def _fetch_drop_level_and_minmod(self, item_href: str) -> Dict[str, str | int]:
        """
        Detail pages often contain 'DropLevel 5' lines and sometimes 'Minimum Modifier Level ...'.
        """
        meta: Dict[str, str | int] = {}
        try:
            detail = self._soup(item_href)
            raw = detail.get_text(" ", strip=True)
            dm = _DROP_LEVEL_RE.search(raw)
            if dm:
                meta["DropLevel"] = dm.group(1)  # tests expect string
            mm = _MIN_MOD_LVL_RE.search(raw)
            if mm:
                meta["MinimumModifierLevel"] = mm.group(1)
        except Exception as e:
            log.debug("detail fetch failed for %s: %s", item_href, e)
        return meta

    # ---------------- public fetchers ----------------

    def fetch_stackable_currency(self) -> List[Currency]:
        """
        Scrape /us/Stackable_Currency and produce a deduped list of Currency.
        """
        soup = self._soup("/us/Stackable_Currency")
        anchors = [a for a in soup.find_all("a") if a.get("href", "").startswith("/us/")]
        seen: Dict[str, Currency] = {}

        for a in anchors:
            name = (a.get_text(strip=True) or "").strip()
            if not name or name.lower() in {"image", "reset", "edit"}:
                continue

            block = self._text_after(a)
            if "Stack Size" not in block:
                continue  # skip non-items

            stack_size, desc, min_mod = self._parse_stack_and_desc(block)
            cur = Currency(name=name, stack_size=stack_size, description=desc or "", min_modifier_level=min_mod, meta={})

            # Enrich from detail page:
            href = a.get("href", "")
            if href:
                meta = self._fetch_drop_level_and_minmod(href)
                cur.meta.update({k: str(v) for k, v in meta.items() if v is not None})
                # Prefer stricter min mod level from detail if not present yet
                if cur.min_modifier_level is None and "MinimumModifierLevel" in cur.meta:
                    try:
                        cur.min_modifier_level = int(cur.meta["MinimumModifierLevel"])
                    except Exception:
                        pass

            if name in seen:
                # keep the one with more info (min level / meta)
                old = seen[name]
                def score(c: Currency) -> int:
                    return (1 if c.min_modifier_level is not None else 0) + (1 if c.meta else 0)
                if score(cur) > score(old):
                    seen[name] = cur
            else:
                seen[name] = cur

        out = list(seen.values())
        log.info("Parsed %d currencies", len(out))
        return out

    # For compatibility with earlier CLI/tests
    def fetch_currencies(self) -> List[Currency]:
        return self.fetch_stackable_currency()

    def fetch_omens(self) -> List[Omen]:
        """
        Scrape /Omen (no locale path) or /us/Omen if the first fails.
        """
        try_paths = ["/Omen", "/us/Omen"]
        soup: Optional[BeautifulSoup] = None
        for p in try_paths:
            try:
                soup = self._soup(p)
                break
            except Exception:
                continue
        if soup is None:
            return []

        out: List[Omen] = []
        anchors = [a for a in soup.find_all("a") if a.get("href", "").startswith("/us/")]
        for a in anchors:
            name = (a.get_text(strip=True) or "").strip()
            if not name or "Omen" not in name or name.lower() in {"image", "reset", "edit"}:
                continue
            block = self._text_after(a)
            stack_size, desc, _ = self._parse_stack_and_desc(block)
            out.append(Omen(name=name, description=desc or "", stack_size=stack_size))

        log.info("Parsed %d omens", len(out))
        return out

    def fetch_essences(self) -> List[Essence]:
        """
        Essences also appear on the currency page; we filter names containing 'Essence'.
        We still try dedicated detail pages to confirm/clean descriptions.
        """
        currencies = self.fetch_stackable_currency()
        out: List[Essence] = []
        for c in currencies:
            if "Essence" in c.name:
                out.append(Essence(name=c.name, tier=self._classify_essence_tier(c.name), description=c.description or "", targets=[]))
        log.info("Parsed %d essences", len(out))
        return out

    @staticmethod
    def _classify_essence_tier(name: str) -> Optional[str]:
        for tier in ("Lesser", "Greater", "Perfect"):
            if name.startswith(tier):
                return tier
        return None

    def fetch_base_items(self, slug: str) -> List[BaseItem]:
        """
        Parse base items from a category page (e.g., 'Boots', 'Bows', 'Helmets', 'Body_Armours', 'Quivers').
        We look for 'Item /NN' sections and read name + the following few lines for minimal metadata.
        """
        soup = self._soup(f"/us/{slug}")
        text = soup.get_text("\n", strip=True)

        # Fast path: “<Category> Item /NN” section exists (Boots shows that shape)
        # We will scan anchors within the page and pick ones whose immediate following text has 'Requires:' or basic stat lines.
        anchors = [a for a in soup.find_all("a") if a.get("href", "").startswith("/us/")]
        items: List[BaseItem] = []
        seen: set[str] = set()

        for a in anchors:
            name = (a.get_text(strip=True) or "").strip()
            if not name or name.lower() in {"image", "edit", "reset"}:
                continue
            block = self._text_after(a)
            if not block:
                continue
            # Heuristic: base items typically show basic stat lines or "Requires:"
            if not any(k in block for k in ("Requires:", "Armour:", "Evasion:", "Energy Shield:", "Physical Damage:", "Attacks per Second:")):
                # On pages like Bows the base types are linked to standalone pages (e.g., Crude_Bow).
                # For those anchors, follow the detail page to confirm base metadata.
                href = a.get("href", "")
                if href and "/Bow" in href:
                    try:
                        ds = self._soup(href)
                        raw = ds.get_text("\n", strip=True)
                        if any(k in raw for k in ("Requires:", "Physical Damage:", "Attacks per Second:")):
                            if name not in seen:
                                items.append(BaseItem(name=name, item_class=slug, required_level=self._extract_required_level(raw), meta={}))
                                seen.add(name)
                    except Exception:
                        pass
                continue

            if name not in seen:
                items.append(BaseItem(name=name, item_class=slug, required_level=self._extract_required_level(block), meta={}))
                seen.add(name)

        log.info("Parsed %d base items for %s", len(items), slug)
        return items

    @staticmethod
    def _extract_required_level(block: str) -> Optional[int]:
        m = re.search(r"Requires:\s*Level\s*(\d+)", block)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
        return None

    @staticmethod
    def default_base_slugs() -> List[str]:
        return list(DEFAULT_BASE_SLUGS)
