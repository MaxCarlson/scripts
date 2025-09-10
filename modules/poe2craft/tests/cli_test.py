#!/usr/bin/env python3
from __future__ import annotations

import io
import json
from pathlib import Path

# Ensure package import works when repo layout is <root>/scripts/poe2craft
import sys
ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "scripts"
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))

from poe2craft import __init__ as _pkg  # noqa: F401, E402
from poe2craft.cli import main  # noqa: E402
from poe2craft.models import Currency, Omen, Essence, BaseItem, ItemClass  # noqa: E402


class _FakeClient:
    def fetch_stackable_currency(self):
        return [
            Currency(name="Chaos Orb", stack_size=20, description="Reroll rare"),
            Currency(name="Exalted Orb", stack_size=10, description="Add random mod"),
        ]

    def fetch_omens(self):
        return [
            Omen(name="Omen of Dextral Erasure", description="Next Chaos removes suffixes"),
            Omen(name="Omen of Greater Exaltation", description="Next Exalt adds two modifiers"),
        ]

    def fetch_essences(self):
        return [
            Essence(name="Perfect Essence of Haste", tier="Perfect", description="+AS"),
            Essence(name="Lesser Essence of Greed", tier="Lesser", description="+Life"),
        ]

    def fetch_base_items(self, slug: str):
        return [
            BaseItem(name="Recurve Bow", item_class=ItemClass.BOW, reqs={"Level": 16}, properties={"Attacks per Second": 1.1}),
        ]


class _FakePrices:
    def get_currency_prices(self, league="Standard"):
        return {"Chaos Orb": 1.0, "Exalted Orb": 120.0}


def _monkey_cli_deps(monkeypatch):
    # Replace real network-bound classes with fakes
    import poe2craft.cli as cli_mod

    monkeypatch.setattr(cli_mod, "Poe2DBClient", lambda: _FakeClient())
    monkeypatch.setattr(cli_mod, "PoENinjaPriceProvider", lambda: _FakePrices())


def test_cli_currencies_stdout(monkeypatch, capsys):
    _monkey_cli_deps(monkeypatch)
    rc = main(["-v", "currencies", "--format", "stdout"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    names = {d["name"] for d in data}
    assert "Chaos Orb" in names and "Exalted Orb" in names


def test_cli_currencies_json_file(monkeypatch, tmp_path: Path):
    _monkey_cli_deps(monkeypatch)
    out_file = tmp_path / "cur.json"
    rc = main(["currencies", "--format", "json", "-o", str(out_file)])
    assert rc == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data and data[0]["name"] == "Chaos Orb"


def test_cli_omens_and_essences(monkeypatch, capsys):
    _monkey_cli_deps(monkeypatch)

    rc1 = main(["omens", "--format", "stdout"])
    assert rc1 == 0
    out1 = json.loads(capsys.readouterr().out)
    assert any("Exalt" in o["description"] for o in out1)

    rc2 = main(["essences", "--format", "stdout"])
    assert rc2 == 0
    out2 = json.loads(capsys.readouterr().out)
    assert any(e["name"].startswith("Perfect Essence") for e in out2)


def test_cli_base_items_stdout(monkeypatch, capsys):
    _monkey_cli_deps(monkeypatch)
    rc = main(["base-items", "Bows", "--format", "stdout"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["name"] == "Recurve Bow"
    assert data[0]["properties"]["Attacks per Second"] == 1.1


def test_cli_prices_stdout(monkeypatch, capsys):
    _monkey_cli_deps(monkeypatch)
    rc = main(["prices", "--league", "Standard", "--format", "stdout"])
    assert rc == 0
    prices = json.loads(capsys.readouterr().out)
    assert prices["Chaos Orb"] == 1.0
    assert prices["Exalted Orb"] == 120.0


def test_cli_error_path_returns_nonzero(monkeypatch):
    # Force provider to raise inside command to exercise exception handling -> exit code 2
    import poe2craft.cli as cli_mod

    class _Boom:
        def get_currency_prices(self, league="Standard"):
            raise RuntimeError("boom")

    monkeypatch.setattr(cli_mod, "PoENinjaPriceProvider", lambda: _Boom())

    rc = main(["prices", "--league", "Standard", "--format", "stdout"])
    assert rc == 2
