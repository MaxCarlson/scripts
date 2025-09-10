#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

# Ensure package import works when repo layout is <root>/scripts/poe2craft
import sys
ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "scripts"
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))

from poe2craft.datasources.poe2db_client import Poe2DBClient  # noqa: E402
from poe2craft.models import ItemClass  # noqa: E402


class _FakeClient(Poe2DBClient):
    """Override HTTP to use embedded HTML fixtures."""

    def __init__(self, html_map):
        super().__init__()
        self._html_map = html_map

    def _get(self, url: str) -> str:
        for key, html in self._html_map.items():
            if url.endswith(key):
                return html
        raise AssertionError(f"Fixture not found for {url}")


STACKABLE_DUP_HTML = """
<html><body>
<h5>Stackable Currency Item /73</h5>
<img/><a href="/us/Chaos_Orb">Chaos Orb</a>
<div>Stack Size: 1 / 20</div>
<div>Reroll rare</div>
<img/><a href="/us/Chaos_Orb">Chaos Orb</a>
<div>Stack Size: 1 / 20</div>
<div>Duplicate listing</div>
</body></html>
"""

CHAOS_DETAIL_WITH_MINLVL = """
<html><body>
<h1>Chaos Orb</h1>
<div>Stack Size: 1 / 20</div>
<div>Minimum Modifier Level: 50</div>
<div>key val</div>
<div>DropLevel: 1</div>
<a>Edit</a>
</body></html>
"""

ESSENCE_DUPS_HTML = """
<html><body>
<h5>Essence /81</h5>
<img/><a href="/us/Perfect_Essence_of_Haste">Perfect Essence of Haste</a>
<div>Upgrades...</div>
<img/><a href="/us/Perfect_Essence_of_Haste">Perfect Essence of Haste</a>
<div>Duplicate...</div>
</body></html>
"""

BASE_MISC_HTML = """
<html><body>
<h5>Foobars</h5>
<img/><a href="/us/Foobar">Foobar</a>
<div>Requires: Level 5</div>
</body></html>
"""


def test_stackable_currency_dedup_and_min_mod_level():
    c = _FakeClient(
        {
            "/us/Stackable_Currency": STACKABLE_DUP_HTML,
            "/us/Chaos_Orb": CHAOS_DETAIL_WITH_MINLVL,
        }
    )
    out = c.fetch_stackable_currency()
    assert len([x for x in out if x.name == "Chaos Orb"]) == 1
    chaos = [x for x in out if x.name == "Chaos Orb"][0]
    assert chaos.min_modifier_level == 50
    assert chaos.meta.get("DropLevel") == "1"


def test_essence_dedup_keeps_single_entry():
    c = _FakeClient({"/us/Essence": ESSENCE_DUPS_HTML})
    out = c.fetch_essences()
    names = [e.name for e in out]
    assert names.count("Perfect Essence of Haste") == 1


def test_infer_item_class_from_unknown_slug():
    c = _FakeClient({"/us/Foobars": BASE_MISC_HTML})
    items = c.fetch_base_items("Foobars")
    assert items  # parsed some entry
    ic = c._infer_item_class_from_slug("Foobars")
    assert ic == ItemClass.UNKNOWN
