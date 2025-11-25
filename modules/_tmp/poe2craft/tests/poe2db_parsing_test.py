#!/usr/bin/env python3
from bs4 import BeautifulSoup

from poe2craft.datasources.poe2db_client import Poe2DBClient
from poe2craft.util.cache import SimpleCache


class _FakeClient(Poe2DBClient):
    """Override HTTP to use embedded HTML fixtures."""

    def __init__(self, html_map):
        super().__init__()
        self._html_map = html_map

    def _get(self, url: str) -> str:
        # pick a page based on suffix
        for key, html in self._html_map.items():
            if url.endswith(key):
                return html
        raise AssertionError(f"Fixture not found for {url}")


STACKABLE_CURRENCY_HTML = """
<html><body>
<h5>Stackable Currency Item /73</h5>
<img/><a href="/us/Chaos_Orb">Chaos Orb</a>
<div>Stack Size: 1 / 20</div>
<div>Removes a random modifier and augments a Rare item with a new random modifier</div>
<img/><a href="/us/Hinekora%27s_Lock">Hinekora's Lock</a>
<div>Stack Size: 1 / 10</div>
<div>Allows an item to foresee the result of the next Currency item used on it Modifying the item in any way removes the ability to foresee</div>
</body></html>
"""

CHAOS_ORB_DETAIL_HTML = """
<html><body>
<h1>Chaos Orb</h1>
<div>Stack Size: 1 / 20</div>
<div>key val</div>
<div>DropLevel: 1</div>
<div>BaseType Chaos Orb</div>
<a>Edit</a>
</body></html>
"""

LOCK_DETAIL_HTML = """
<html><body>
<h1>Hinekora's Lock</h1>
<div>Stack Size: 1 / 10</div>
<div>key val</div>
<div>DropLevel: 1</div>
<a>Edit</a>
</body></html>
"""

OMEN_HTML = """
<html><body>
<h5>Omens</h5>
<img/><a href="/us/Omen_of_Greater_Exaltation">Omen of Greater Exaltation</a>
<div>Stack Size: 1 / 10</div>
<div>While this item is active in your inventory your next Exalted Orb will add two random modifiers</div>
</body></html>
"""

ESSENCE_HTML = """
<html><body>
<h5>Essence /81</h5>
<img/><a href="/us/Perfect_Essence_of_Haste">Perfect Essence of Haste</a>
<div>Stack Size: 1 / 10</div>
<div>Upgrades a Magic item to a Rare item, adding a guaranteed modifier Martial Weapon: (15–17)% increased Attack Speed</div>
</body></html>
"""

BOWS_HTML = """
<html><body>
<h5>Bows Item /26</h5>
<img/><a href="/us/Recurve_Bow">Recurve Bow</a>
<div>Physical Damage: 15-31</div>
<div>Critical Hit Chance: 5%</div>
<div>Attacks per Second: 1.1</div>
<div>Requires: Level 16, 31 Dex</div>
</body></html>
"""


def test_parse_stackable_currencies():
    c = _FakeClient(
        {
            "/us/Stackable_Currency": STACKABLE_CURRENCY_HTML,
            "/us/Chaos_Orb": CHAOS_ORB_DETAIL_HTML,
            "/us/Hinekora%27s_Lock": LOCK_DETAIL_HTML,
        }
    )
    out = c.fetch_stackable_currency()
    names = {x.name for x in out}
    assert "Chaos Orb" in names
    assert "Hinekora's Lock" in names
    chaos = [x for x in out if x.name == "Chaos Orb"][0]
    assert chaos.stack_size == 20
    assert chaos.meta.get("DropLevel") == "1"


def test_parse_omens():
    c = _FakeClient({"/us/Omen": OMEN_HTML})
    out = c.fetch_omens()
    assert any("Exalted" in o.description for o in out)


def test_parse_essences():
    c = _FakeClient({"/us/Essence": ESSENCE_HTML})
    out = c.fetch_essences()
    assert any(e.name.startswith("Perfect Essence") for e in out)


def test_parse_bows_base_items():
    c = _FakeClient({"/us/Bows": BOWS_HTML})
    out = c.fetch_base_items("Bows")
    assert any(b.name == "Recurve Bow" for b in out)
    rb = [b for b in out if b.name == "Recurve Bow"][0]
    assert rb.properties.get("Attacks per Second") == 1.1
    assert rb.reqs.get("Level") == 16
