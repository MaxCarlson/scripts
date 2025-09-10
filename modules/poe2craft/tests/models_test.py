#!/usr/bin/env python3
import json

from poe2craft.models import (
    ItemClass,
    Modifier,
    AffixType,
    ValueRange,
    BaseItem,
    Item,
    Currency,
    Omen,
    Essence,
    ModTag,
)


def test_modifier_serialization_roundtrip():
    m = Modifier(
        id_hint="t1_as",
        text="(16–18)% increased Attack Speed",
        tier=1,
        affix_type=AffixType.PREFIX,
        tags=[ModTag.SPEED, ModTag.ATTACK],
        values={"Attack Speed %": ValueRange(16, 18)},
    )
    s = m.to_json()
    data = json.loads(s)
    assert data["tier"] == 1
    assert data["affix_type"] == "prefix"
    assert "Attack Speed %" in data["values"]


def test_item_open_slots():
    base = BaseItem(name="Recurve Bow", item_class=ItemClass.BOW, reqs={"Level": 16, "Dex": 31})
    it = Item(base=base, ilvl=70)
    assert it.has_open_prefix()
    assert it.has_open_suffix()


def test_currency_basic():
    c = Currency(name="Chaos Orb", stack_size=20, description="Removes a random modifier and augments a Rare item")
    assert "Chaos Orb" in c.to_json()


def test_omen_basic():
    o = Omen(name="Omen of Greater Exaltation", description="Your next Exalted Orb will add two random modifiers")
    data = json.loads(o.to_json())
    assert "Exalted" in data["description"]


def test_essence_basic():
    e = Essence(name="Perfect Essence of Haste", tier="Perfect", description="(x–y)% increased Attack Speed")
    assert e.tier == "Perfect"
