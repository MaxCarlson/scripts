#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import json

from poe2craft.util.serde import as_serializable


class AffixType(Enum):
    PREFIX = "prefix"
    SUFFIX = "suffix"
    IMPLICIT = "implicit"
    ENCHANT = "enchant"
    UNKNOWN = "unknown"


class ItemClass(Enum):
    # Weapons
    BOW = "Bow"
    STAFF = "Staff"
    TWO_HAND_SWORD = "Two Hand Sword"
    TWO_HAND_AXE = "Two Hand Axe"
    TWO_HAND_MACE = "Two Hand Mace"
    QUARTERSTAFF = "Quarterstaff"
    CROSSBOW = "Crossbow"
    SPEAR = "Spear"
    FLAIL = "Flail"
    ONE_HAND_SWORD = "One Hand Sword"
    ONE_HAND_AXE = "One Hand Axe"
    ONE_HAND_MACE = "One Hand Mace"
    CLAW = "Claw"
    DAGGER = "Dagger"
    WAND = "Wand"
    SCEPTRE = "Sceptre"
    TRAP = "Trap"

    # Armour
    GLOVES = "Gloves"
    BOOTS = "Boots"
    BODY_ARMOUR = "Body Armour"
    HELMET = "Helmet"
    SHIELD = "Shield"
    BUCKLER = "Buckler"
    FOCUS = "Focus"
    QUIVER = "Quiver"

    # Jewellery
    RING = "Ring"
    AMULET = "Amulet"
    BELT = "Belt"

    # Flasks / Charms
    LIFE_FLASK = "Life Flask"
    MANA_FLASK = "Mana Flask"
    FLASK = "Flask"
    CHARM = "Charm"

    # Other (keep extendable)
    UNKNOWN = "Unknown"


class ModTag(str, Enum):
    ATTACK = "attack"
    CASTER = "caster"
    SPEED = "speed"
    CRITICAL = "critical"
    FIRE = "fire"
    COLD = "cold"
    LIGHTNING = "lightning"
    CHAOS = "chaos"
    LIFE = "life"
    DEFENCES = "defences"
    MINION = "minion"
    ATTRIBUTE = "attribute"
    RESISTANCE = "resistance"
    MOVEMENT = "movement"
    BOW = "bow"
    GENERIC = "generic"


@dataclass(frozen=True)
class ValueRange:
    min: Optional[float] = None
    max: Optional[float] = None

    def __bool__(self) -> bool:
        return self.min is not None or self.max is not None

    def to_json(self) -> str:
        return json.dumps(as_serializable(asdict(self)), ensure_ascii=False)


@dataclass
class Modifier:
    """Represents an affix-like modifier."""
    id_hint: Optional[str]
    text: str
    tier: Optional[int] = None
    affix_type: AffixType = AffixType.UNKNOWN
    tags: List[ModTag] = field(default_factory=list)
    values: Dict[str, ValueRange] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(as_serializable(asdict(self)), ensure_ascii=False)


@dataclass
class BaseItem:
    name: str
    item_class: ItemClass
    reqs: Dict[str, Union[int, str]] = field(default_factory=dict)
    implicits: List[Modifier] = field(default_factory=list)
    properties: Dict[str, Union[int, float, str]] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(as_serializable(asdict(self)), ensure_ascii=False)


@dataclass
class Currency:
    name: str
    stack_size: Optional[int] = None
    description: Optional[str] = None
    min_modifier_level: Optional[int] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(as_serializable(asdict(self)), ensure_ascii=False)


@dataclass
class Omen:
    name: str
    description: str
    stack_size: Optional[int] = None

    def to_json(self) -> str:
        return json.dumps(as_serializable(asdict(self)), ensure_ascii=False)


@dataclass
class Essence:
    name: str
    tier: Optional[str] = None
    description: str = ""
    targets: List[ItemClass] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(as_serializable(asdict(self)), ensure_ascii=False)


@dataclass
class Item:
    """Runtime representation of a craftable item."""
    base: BaseItem
    ilvl: int
    prefixes: List[Modifier] = field(default_factory=list)
    suffixes: List[Modifier] = field(default_factory=list)
    corrupted: bool = False
    fractured_ids: List[str] = field(default_factory=list)

    def has_open_prefix(self) -> bool:
        return len(self.prefixes) < 3

    def has_open_suffix(self) -> bool:
        return len(self.suffixes) < 3

    @property
    def all_mods(self) -> List[Modifier]:
        return self.base.implicits + self.prefixes + self.suffixes

    def to_json(self) -> str:
        return json.dumps(as_serializable(asdict(self)), ensure_ascii=False)
