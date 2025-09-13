#!/usr/bin/env python3
"""
Robust PoE2DB (poe2db.tw) scraper:

- Currencies (/us/Stackable_Currency)       → Currency[]
- Omens (/us/Omen)                          → Omen[]
- Essences (/us/Essence)                    → Essence[]
- Base items (/us/<Slug>)                   → BaseItem[]

Key improvements:
- We only keep anchors whose detail page actually matches the content type.
- Base items now include `properties` and `reqs`.
- Added `_infer_item_class_from_slug` (unknown → ItemClass.UNKNOWN).
- Lots of debug logging.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger("poe2craft.datasources.poe2db")

BASE_URL = "https://poe2db.tw"

# Heuristics
STAT_TOKENS = (
    "Requires:",
    "Armour:",
    "Evasion:",
    "Energy Shield:",
    "Physical Damage:",
    "Attacks per Second:",
)
STACK_RE = re.compile(r"Stack\s*Size:\s*(\d+)\s*/\s*(\d+)", re.I)
DROP_LEVEL_RE = re.compile(r"Drop\s*Level[:\s]+(\d+)", re.I)
MIN_MOD_RE = re.compile(r"Minimum\s+Modifier\s+Level[^0-9]*([0-9]+)", re.I)
REQ_LVL_RE = re.compile(r"Requires:\s*Level\s*(\d+)", re.I)
KV_RE = re.compile(r"^(Armour|Evasion|Energy Shield|Physical Damage|Attacks per Second):\s*(.+)$", re.I)

# Stopwords for top-nav / site chrome texts
NAV_STOPWORDS = {
    "poe2db", "item", "vendor recipes", "league", "ascendancy classes",
    "gem", "skill gems", "support gems", "spirit gems", "lineage supports",
    "unusual gems", "modifiers", "keywords", "quest", "act 1", "act 2",
    "act 3", "act 4", "interlude", "waystones", "atlas tree modifiers",
    "passive skill tree", "tools", "pob code", "flavourtext", "login",
    "patreon", "us english", "kr 한국어", "jp japanese", "ru русский",
    "cn 简体中文", "tw 正體中文", "th ภาษาไทย", "fr français", "de deutsch",
    "es spanish", "poedb",
}


# ---- Models (import real ones if available) ---------------------------------
try:
    from ..models import Currency, Omen, Essence, BaseItem, ItemClass  # type: ignore
except Exception:  # pragma: no cover (fallback for CLI running outside tests)
    from enum import Enum

    class ItemClass(Enum):
        UNKNOWN = "Unknown"

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
        item_class: Any  # may be ItemClass or str
        required_level: Optional[int] = None
        properties: Dict[str, Any] = field(default_factory=dict)
        reqs: Dict[str, Any] = field(default_factory=dict)
        meta: Dict[str, str] = field(default_factory=dict)


class Poe2DBClient:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "user-agent": "poe2craft/0.1",
                "accept-language": "en-US,en;q=0.9",
            }
        )

    # ---------------- core HTTP ----------------

    def _get(self, url_or_path: str) -> str:
        url = url_or_path if url_or_path.startswith("http") else f"{BASE_URL}{url_or_path}"
        LOG.debug("GET %s", url)
        r = self.session.get(url, timeout=20)
        r.raise_for_status()
        return r.text

    def _soup(self, path: str) -> BeautifulSoup:
        return BeautifulSoup(self._get(path), "html.parser")

    # ---------------- helpers ------------------

    @staticmethod
    def _text_lines(text: str) -> List[str]:
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    @staticmethod
    def _stack_tuple(text: str) -> Optional[tuple[int, int]]:
        m = STACK_RE.search(text)
        if not m:
            return None
        try:
            return int(m.group(1)), int(m.group(2))
        except Exception:
            return None

    @staticmethod
    def _short_desc_from_detail(text: str) -> str:
        lines = Poe2DBClient._text_lines(text)
        lines = [ln for ln in lines if not ln.lower().startswith("stack size:")]
        for ln in lines:
            if 3 <= len(ln) <= 180 and not ln.lower().startswith(
                ("image", "right click", "shift click", "name", "class", "tags", "type")
            ):
                return ln
        return lines[0] if lines else ""

    @staticmethod
    def _extract_meta_numbers(text: str) -> Dict[str, str]:
        meta: Dict[str, str] = {}
        mm = MIN_MOD_RE.search(text)
        if mm:
            meta["MinimumModifierLevel"] = mm.group(1)
        dl = DROP_LEVEL_RE.search(text)
        if dl:
            meta["DropLevel"] = dl.group(1)
        return meta

    @staticmethod
    def _parse_base_stats(text: str) -> tuple[Dict[str, Any], Dict[str, Any], Optional[int]]:
        """
        Return (properties, reqs, required_level)
        """
        props: Dict[str, Any] = {}
        reqs: Dict[str, Any] = {}
        lvl: Optional[int] = None

        for ln in Poe2DBClient._text_lines(text):
            m = KV_RE.match(ln)
            if m:
                k, v = m.group(1), m.group(2)
                if k.lower() == "attacks per second":
                    try:
                        props["Attacks per Second"] = float(v)
                    except Exception:
                        props["Attacks per Second"] = v
                else:
                    # keep as string; (Physical Damage 9-17 etc.)
                    props[k] = v
            m2 = REQ_LVL_RE.search(ln)
            if m2:
                try:
                    lvl = int(m2.group(1))
                    reqs["Level"] = lvl
                except Exception:
                    pass
        return props, reqs, lvl

    @staticmethod
    def _looks_like_nav(name: str) -> bool:
        return name.strip().lower() in NAV_STOPWORDS

    # ---------------- public API ----------------

    def fetch_stackable_currency(self) -> List[Currency]:
        soup = self._soup("/us/Stackable_Currency")
        out: List[Currency] = []
        seen: set[str] = set()

        for a in soup.find_all("a"):
            name = (a.get_text(strip=True) or "").strip()
            href = a.get("href", "")
            if not name or not href.startswith("/us/"):
                continue
            if self._looks_like_nav(name):
                continue

            # Detail gate: we only accept items whose detail page has 'Stack Size:'
            try:
                detail = self._get(href)
                if "Stack Size:" not in detail:
                    continue
                dsoup = BeautifulSoup(detail, "html.parser")
                raw = dsoup.get_text("\n", strip=True)
                stack = self._stack_tuple(raw)
                desc = self._short_desc_from_detail(raw)
                meta = self._extract_meta_numbers(raw)

                minlvl = None
                if "MinimumModifierLevel" in meta:
                    try:
                        minlvl = int(meta["MinimumModifierLevel"])
                    except Exception:
                        pass

                cur = Currency(
                    name=name,
                    stack_size=(stack[1] if stack else None),
                    description=desc,
                    min_modifier_level=minlvl,
                    meta=meta,
                )
                if name not in seen:
                    out.append(cur)
                    seen.add(name)
            except Exception as e:
                LOG.debug("currency detail failed for %s: %s", href, e)
                continue

        LOG.info("Parsed %d currencies", len(out))
        return out

    # Back-compat alias
    def fetch_currencies(self) -> List[Currency]:
        return self.fetch_stackable_currency()

    def fetch_omens(self) -> List[Omen]:
        soup = self._soup("/us/Omen")
        out: List[Omen] = []
        seen: set[str] = set()

        for a in soup.find_all("a"):
            name = (a.get_text(strip=True) or "").strip()
            href = a.get("href", "")
            if not name or "Omen" not in name or not href.startswith("/us/"):
                continue

            try:
                ds = self._get(href)
                rs = BeautifulSoup(ds, "html.parser").get_text("\n", strip=True)
                # prefer a line that looks like an effect/usage sentence
                desc = ""
                for ln in self._text_lines(rs):
                    if any(tok in ln for tok in ("Next", "Exalt", "Use", "When")) and len(ln) < 200:
                        desc = ln
                        break
                if not desc:
                    desc = self._short_desc_from_detail(rs)
                stack = self._stack_tuple(rs)
                o = Omen(name=name, description=desc, stack_size=(stack[1] if stack else None))
                if name not in seen:
                    out.append(o)
                    seen.add(name)
            except Exception as e:
                LOG.debug("omen detail failed for %s: %s", href, e)

        LOG.info("Parsed %d omens", len(out))
        return out

    def fetch_essences(self) -> List[Essence]:
        soup = self._soup("/us/Essence")
        out: List[Essence] = []
        seen: set[str] = set()

        for a in soup.find_all("a"):
            nm = (a.get_text(strip=True) or "").strip()
            if not nm or "Essence" not in nm:
                continue
            tier = None
            m = re.match(r"^(Lesser|Greater|Perfect)\b", nm)
            if m:
                tier = m.group(1)
            if nm not in seen:
                out.append(Essence(name=nm, tier=tier, description="", targets=[]))
                seen.add(nm)

        LOG.info("Parsed %d essences", len(out))
        return out

    def fetch_base_items(self, slug: str) -> List[BaseItem]:
        soup = self._soup(f"/us/{slug}")
        out: List[BaseItem] = []
        seen: set[str] = set()

        for a in soup.find_all("a"):
            name = (a.get_text(strip=True) or "").strip()
            href = a.get("href", "")
            if not name or not href.startswith("/us/"):
                continue
            if self._looks_like_nav(name):
                continue

            # First try to confirm via detail page
            included = False
            try:
                ds = self._get(href)
                raw = BeautifulSoup(ds, "html.parser").get_text("\n", strip=True)
                if any(tok in raw for tok in STAT_TOKENS):
                    props, reqs, req_lvl = self._parse_base_stats(raw)
                    bi = BaseItem(
                        name=name,
                        item_class=self._infer_item_class_from_slug(slug),
                        required_level=req_lvl,
                        properties=props,
                        reqs=reqs,
                        meta={},
                    )
                    if name not in seen:
                        out.append(bi)
                        seen.add(name)
                        included = True
            except Exception as e:
                LOG.debug("base item detail failed for %s: %s", href, e)

            if included:
                continue

            # Otherwise try in-page text around the anchor's parent
            parent = a.parent
            if not parent:
                continue
            tail = parent.get_text("\n", strip=True)
            if any(tok in tail for tok in STAT_TOKENS):
                props, reqs, req_lvl = self._parse_base_stats(tail)
                bi = BaseItem(
                    name=name,
                    item_class=self._infer_item_class_from_slug(slug),
                    required_level=req_lvl,
                    properties=props,
                    reqs=reqs,
                    meta={},
                )
                if name not in seen:
                    out.append(bi)
                    seen.add(name)

        LOG.info("Parsed %d base items for %s", len(out), slug)
        return out

    # ---------------- convenience ----------------

    def _infer_item_class_from_slug(self, slug: str):
        """
        Map a category slug to ItemClass enum when possible; unknown → ItemClass.UNKNOWN.
        """
        try:
            # If your ItemClass enum exposes exact names (e.g., Bows → BOWS), adjust here if needed.
            return ItemClass[slug.upper()]  # type: ignore[index]
        except Exception:
            return getattr(ItemClass, "UNKNOWN", "Unknown")
