#!/usr/bin/env python3
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger("poe2craft.datasources.poe2db")

BASE_URL = "https://poe2db.tw"

# Default curated categories for base items
DEFAULT_BASE_SLUGS: List[str] = ["Bows", "Boots", "Gloves", "Helmets", "Body_Armours", "Quivers"]


# ---- Minimal models (kept here so this module is self-contained for tests) ----

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
    targets: List[str] = field(default_factory=list)


@dataclass
class BaseItem:
    name: str
    item_class: str
    required_level: Optional[int] = None
    meta: Dict[str, str] = field(default_factory=dict)


class Poe2DBClient:
    """
    Lightweight scraper tailored to PoE2DB test fixtures and site:
    - /us/Stackable_Currency -> Currency list (deduped)
    - /us/Omen               -> Omens
    - /us/Essence            -> Essences
    - /us/<Slug>             -> Base items (Bows, Boots, etc.)
    """

    _STACK_RE = re.compile(r"Stack\s*Size:\s*(\d+)\s*/\s*(\d+)", re.I)
    _DROP_LEVEL_RE = re.compile(r"\bDrop\s*Level[:\s]+(\d+)\b", re.I)
    _MIN_MOD_RE = re.compile(r"\bMinimum\s+Modifier\s+Level[^0-9]*([0-9]+)", re.I)
    _REQ_LEVEL_RE = re.compile(r"\bRequires:\s*Level\s*(\d+)\b", re.I)

    def __init__(self, session: Optional[requests.Session] = None):
        self.sess = session or requests.Session()
        self.sess.headers.update(
            {
                "user-agent": "poe2craft/0.1 (+local)",
                "accept-language": "en-US,en;q=0.9",
            }
        )

    # --------------- HTTP helpers ---------------

    def _get(self, url_or_path: str) -> str:
        if url_or_path.startswith("http"):
            url = url_or_path
        else:
            # Always allow test fixtures that pass "/us/..." as exact keys.
            url = BASE_URL + url_or_path
        LOG.debug("GET %s", url)
        r = self.sess.get(url, timeout=20)
        r.raise_for_status()
        return r.text

    def _soup(self, path: str) -> BeautifulSoup:
        return BeautifulSoup(self._get(path), "html.parser")

    # --------------- Common parsing helpers ---------------

    @staticmethod
    def _text_lines(text: str) -> List[str]:
        return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]

    @classmethod
    def _parse_stack_size(cls, text: str) -> Optional[Tuple[int, int]]:
        m = cls._STACK_RE.search(text or "")
        if not m:
            return None
        try:
            return int(m.group(1)), int(m.group(2))
        except Exception:
            return None

    @classmethod
    def _extract_min_modifier_level(cls, text: str) -> Optional[int]:
        m = cls._MIN_MOD_RE.search(text or "")
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
        return None

    @classmethod
    def _extract_required_level(cls, text: str) -> Optional[int]:
        m = cls._REQ_LEVEL_RE.search(text or "")
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
        return None

    @classmethod
    def _extract_meta(cls, text: str) -> Dict[str, str]:
        meta: Dict[str, str] = {}
        mm = cls._MIN_MOD_RE.search(text or "")
        if mm:
            meta["MinimumModifierLevel"] = mm.group(1)
        dl = cls._DROP_LEVEL_RE.search(text or "")
        if dl:
            meta["DropLevel"] = dl.group(1)
        return meta

    @staticmethod
    def _short_desc_from_lines(lines: List[str]) -> str:
        for ln in lines:
            low = ln.lower()
            if low.startswith(("stack size:", "image", "right click", "shift click", "class", "tags", "type")):
                continue
            if 0 < len(ln) <= 160:
                return ln
        return lines[0] if lines else ""

    # --------------- Public fetchers ---------------

    def fetch_stackable_currency(self) -> List[Currency]:
        soup = self._soup("/us/Stackable_Currency")
        out: List[Currency] = []
        seen_names: set[str] = set()

        for a in soup.find_all("a"):
            name = (a.get_text(strip=True) or "").strip()
            href = a.get("href", "")
            if not name or not href or not href.startswith("/us/"):
                continue
            if name.lower() in {"image", "edit", "reset"}:
                continue

            # Fetch detail page to enrich
            try:
                ds = self._soup(href)
            except Exception:
                continue

            raw = ds.get_text("\n", strip=True)
            lines = self._text_lines(raw)
            desc = self._short_desc_from_lines(lines)
            stack = self._parse_stack_size(raw)
            minlvl = self._extract_min_modifier_level(raw)
            meta = self._extract_meta(raw)

            cur = Currency(
                name=name,
                stack_size=(stack[1] if stack else None),  # max stack
                description=desc,
                min_modifier_level=minlvl,
                meta=meta,
            )

            if name not in seen_names:
                out.append(cur)
                seen_names.add(name)

        LOG.info("Parsed %d currencies", len(out))
        return out

    # Alias for older naming
    def fetch_currencies(self) -> List[Currency]:
        return self.fetch_stackable_currency()

    def fetch_omens(self) -> List[Omen]:
        # Try locale path first (fixtures use /us/Omen)
        soup = self._soup("/us/Omen")
        out: List[Omen] = []
        seen: set[str] = set()

        for a in soup.find_all("a"):
            name = (a.get_text(strip=True) or "").strip()
            href = a.get("href", "")
            if not name or "Omen" not in name or not href.startswith("/us/"):
                continue
            try:
                ds = self._soup(href)
            except Exception:
                continue

            raw = ds.get_text("\n", strip=True)
            lines = self._text_lines(raw)
            desc = self._short_desc_from_lines(lines)
            stack = self._parse_stack_size(raw)

            omen = Omen(name=name, description=desc, stack_size=(stack[1] if stack else None))
            if name not in seen:
                out.append(omen)
                seen.add(name)

        LOG.info("Parsed %d omens", len(out))
        return out

    def fetch_essences(self) -> List[Essence]:
        """Parse from /us/Essence only (do NOT depend on currencies page; matches tests)."""
        soup = self._soup("/us/Essence")
        out: List[Essence] = []
        seen: set[str] = set()

        for a in soup.find_all("a"):
            nm = (a.get_text(strip=True) or "").strip()
            if not nm or "Essence" not in nm:
                continue

            tier = None
            m = re.match(r"^(Lesser|Greater|Perfect)\s+", nm)
            if m:
                tier = m.group(1)

            if nm not in seen:
                out.append(Essence(name=nm, tier=tier, description="", targets=[]))
                seen.add(nm)

        LOG.info("Parsed %d essences", len(out))
        return out

    def fetch_base_items(self, slug: str) -> List[BaseItem]:
        soup = self._soup(f"/us/{slug}")
        items: List[BaseItem] = []
        seen: set[str] = set()

        for a in soup.find_all("a"):
            name = (a.get_text(strip=True) or "").strip()
            href = a.get("href", "")
            if not name or name.lower() in {"image", "edit", "reset"}:
                continue
            if not href.startswith("/us/"):
                continue

            # Try in-page neighborhood text, else follow detail when looks like a specific base page
            parent_text = a.parent.get_text("\n", strip=True) if a.parent else ""
            has_stats = any(k in parent_text for k in ("Requires:", "Armour:", "Evasion:", "Energy Shield:", "Physical Damage:", "Attacks per Second:"))

            required_level = None
            if not has_stats and any(tok in href for tok in ("_Bow", "_Boots", "_Gloves", "_Helmet", "_Body", "_Quiver")):
                try:
                    ds = self._soup(href)
                    raw = ds.get_text("\n", strip=True)
                    if any(k in raw for k in ("Requires:", "Physical Damage:", "Attacks per Second:", "Armour:", "Evasion:", "Energy Shield:")):
                        required_level = self._extract_required_level(raw)
                        if name not in seen:
                            items.append(BaseItem(name=name, item_class=slug, required_level=required_level, meta={}))
                            seen.add(name)
                        continue
                except Exception:
                    pass

            if required_level is None:
                required_level = self._extract_required_level(parent_text)

            if name not in seen:
                items.append(BaseItem(name=name, item_class=slug, required_level=required_level, meta={}))
                seen.add(name)

        LOG.info("Parsed %d base items for %s", len(items), slug)
        return items
