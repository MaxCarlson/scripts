#!/usr/bin/env python3
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Iterable, Tuple

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

from ..cache import SimpleCache

log = logging.getLogger("poe2craft.datasources.poe2db")

_POE2DB = "https://poe2db.tw"


@dataclass
class Currency:
    name: str
    stack_size: Optional[str]
    description: str
    min_modifier_level: Optional[int]
    meta: Dict[str, str]


@dataclass
class Omen:
    name: str
    description: str
    stack_size: Optional[str]


@dataclass
class Essence:
    name: str
    tier: Optional[str]
    description: str
    targets: List[str]


@dataclass
class BaseItem:
    name: str
    item_class: str
    url: str


def _slugify_path_segment(s: str) -> str:
    # For PoE2DB page segments we need exact case/underscores, so only trim spaces.
    return s.strip()


def _text(s: Optional[str]) -> str:
    return (s or "").strip()


def _first(it: Iterable[str]) -> Optional[str]:
    for x in it:
        if x:
            return x
    return None


def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


class Poe2DBClient:
    """
    Minimal PoE2DB scraper for PoE2. Designed to be resilient to their markup,
    avoiding brittle tag chains and instead scanning textual siblings.
    """

    def __init__(
        self,
        base_url: str = _POE2DB,
        locale: Optional[str] = "us",
        session: Optional[requests.Session] = None,
        cache: Optional[SimpleCache] = None,
        timeout: float = 12.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.locale = locale
        self.session = session or requests.Session()
        self.cache = cache or SimpleCache()
        self.timeout = timeout

    # ---------- HTTP helpers ----------

    def _url(self, path: str) -> str:
        path = path.lstrip("/")
        if self.locale:
            return f"{self.base_url}/{self.locale}/{path}"
        return f"{self.base_url}/{path}"

    def _get(self, url: str) -> str:
        cached = self.cache.get(url)
        if cached is not None:
            return cached
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        self.cache.set(url, r.text)
        return r.text

    def _soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self._get(url), "html.parser")

    # ---------- Parsing utilities ----------

    _re_stack = re.compile(r"\bStack Size:\s*(.+)", re.I)
    _re_minmlvl = re.compile(r"\bMinimum Modifier Level:\s*(\d+)", re.I)

    def _scan_following_text(self, anchor: Tag) -> Tuple[Optional[str], Optional[int], Optional[str]]:
        """
        From an <a> (item name), walk through its following siblings until the next <a> or 'Image'
        marker, and extract:
          - stack size (text like 'Stack Size: 1 / 20')
          - min modifier level (if present)
          - first non-empty descriptive text (not stack size or min level)
        """
        stack: Optional[str] = None
        minlvl: Optional[int] = None
        description: Optional[str] = None

        for sib in anchor.next_siblings:
            if isinstance(sib, Tag) and sib.name == "a":
                break  # next item
            text = ""
            if isinstance(sib, NavigableString):
                text = str(sib)
            elif isinstance(sib, Tag):
                # Ignore image anchors; often the word "Image" is a link or plain text
                if sib.get_text(strip=True) == "Image":
                    break
                text = sib.get_text(" ", strip=True)
            text = _norm_space(text)
            if not text:
                continue

            m = self._re_stack.search(text)
            if m and not stack:
                stack = m.group(1).strip()
                continue

            m2 = self._re_minmlvl.search(text)
            if m2 and not minlvl:
                try:
                    minlvl = int(m2.group(1))
                except ValueError:
                    pass
                continue

            # first non-empty meaningful description
            if description is None and not text.lower().startswith(("stack size:", "minimum modifier level:", "name", "drop level")):
                description = text

        return stack, minlvl, description

    # ---------- Public APIs ----------

    def fetch_currencies(self) -> List[Currency]:
        """
        Parse https://poe2db.tw/us/Stackable_Currency (US locale) and capture
        name, stack size, description, and min modifier level if present.
        """
        url = self._url("Stackable_Currency")
        soup = self._soup(url)

        results: List[Currency] = []
        # Heuristic: valid item anchors on this page link to concrete item pages, not headers.
        for a in soup.find_all("a", href=True):
            name = _norm_space(a.get_text())
            href = a["href"]
            if not name or name in {"Reset", "Edit"}:
                continue
            # PoE2DB item detail links often look like "/us/Gemcutters_Prism" or "/Gemcutters_Prism"
            if not re.match(r"^/(?:[a-z]{2}/)?[A-Za-z0-9][A-Za-z0-9_%-]+$", href):
                continue

            stack, minlvl, desc = self._scan_following_text(a)

            # Require at least name + one of stack/desc for it to be a currency row
            if stack or desc:
                results.append(
                    Currency(
                        name=name,
                        stack_size=_text(stack),
                        description=_text(desc),
                        min_modifier_level=minlvl,
                        meta={},
                    )
                )

        log.info("Parsed %d currencies from %s", len(results), url)
        return results

    def fetch_omens(self) -> List[Omen]:
        """
        Parse https://poe2db.tw/Omens (no locale is more reliable for this page).
        """
        # Prefer root page. If user changed locale, fall back to that.
        root_url = f"{self.base_url}/Omens"
        try:
            soup = BeautifulSoup(self._get(root_url), "html.parser")
        except Exception:
            soup = self._soup("Omen")

        out: List[Omen] = []
        for a in soup.find_all("a", href=True):
            name = _norm_space(a.get_text())
            href = a["href"]
            if not name or name in {"Reset", "Edit"}:
                continue
            if not re.match(r"^/(?:[a-z]{2}/)?[A-Za-z0-9][A-Za-z0-9_%-]+$", href):
                continue
            if "Omen" not in name and "Omen" not in href:
                # avoid random anchors
                continue

            stack, _minlvl, desc = self._scan_following_text(a)
            if stack or desc:
                out.append(Omen(name=name, description=_text(desc), stack_size=_text(stack)))

        log.info("Parsed %d omens", len(out))
        return out

    def fetch_essences(self) -> List[Essence]:
        """
        Parse https://poe2db.tw/Essence (root path works best).
        """
        url = f"{self.base_url}/Essence"
        soup = BeautifulSoup(self._get(url), "html.parser")
        res: List[Essence] = []
        for a in soup.find_all("a", href=True):
            name = _norm_space(a.get_text())
            href = a["href"]
            if not name or name in {"Reset", "Edit"}:
                continue
            if "Essence" not in name and "Essence" not in href:
                continue
            if not re.match(r"^/(?:[a-z]{2}/)?[A-Za-z0-9][A-Za-z0-9_%-]+$", href):
                continue

            stack, _minlvl, desc = self._scan_following_text(a)

            # Attempt a tier from the name prefix (Lesser/Greater/Perfect/etc.)
            tier = None
            m = re.match(r"^(Lesser|Greater|Perfect)\s+Essence", name)
            if m:
                tier = m.group(1)

            res.append(Essence(name=name, tier=tier, description=_text(desc), targets=[]))

        log.info("Parsed %d essences", len(res))
        return res

    def fetch_base_items(self, slug: str) -> List[BaseItem]:
        """
        Parse a base-item listing page (e.g., 'Bows', 'Helmets', 'Body_Armours', 'Boots', 'Gloves', 'Quivers').
        """
        slug = _slugify_path_segment(slug)
        url = self._url(slug)
        soup = self._soup(url)

        items: List[BaseItem] = []
        # Strategy: find anchors that link to detail base items under this category.
        for a in soup.find_all("a", href=True):
            name = _norm_space(a.get_text())
            href = a["href"]
            if not name or name in {"Reset", "Edit"}:
                continue
            # Typical base item detail urls look like /us/Recurve_Bow etc.
            if not re.match(r"^/(?:[a-z]{2}/)?[A-Za-z0-9][A-Za-z0-9_%-]+$", href):
                continue

            # Guard against clear non-item navigation anchors by requiring mixed-case-ish names
            if len(name) < 3 or name.lower() == name:
                continue

            items.append(BaseItem(name=name, item_class=self.infer_item_class_from_slug(slug), url=self._absolute(href)))

        log.info("Parsed %d base items from slug '%s'", len(items), slug)
        return items

    def _absolute(self, href: str) -> str:
        if href.startswith("http"):
            return href
        href = href.lstrip("/")
        # keep or remove locale component
        if self.locale:
            if re.match(r"^[a-z]{2}/", href):
                return f"{self.base_url}/{href}"
            return f"{self.base_url}/{self.locale}/{href}"
        return f"{self.base_url}/{href}"

    # ---------- Helpers ----------

    @staticmethod
    def infer_item_class_from_slug(slug: str) -> str:
        s = slug.lower()
        if "bow" in s:
            return "Bows"
        if "boots" in s:
            return "Boots"
        if "gloves" in s:
            return "Gloves"
        if "helmet" in s or "helmets" in s:
            return "Helmets"
        if "body_armour" in s or "body_armours" in s or "armour" in s:
            return "Body Armours"
        if "quiver" in s or "quivers" in s:
            return "Quivers"
        return slug

    # Reasonable defaults for "download all base items"
    @staticmethod
    def default_base_slugs() -> List[str]:
        return ["Bows", "Quivers", "Boots", "Gloves", "Helmets", "Body_Armours"]
