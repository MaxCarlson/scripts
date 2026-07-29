from __future__ import annotations

import sys
from types import ModuleType

import pytest

from rrbackup import compatibility


@pytest.mark.parametrize(
    "arguments",
    [
        ["backup", "--set", "daily"],
        ["list"],
        ["list", "--tag", "local-main"],
        ["ls", "--path", "C:\\"],
        ["snapshots", "--host", "Xeres"],
        ["setup"],
        ["prune"],
        ["config", "init"],
        ["--config", "settings.toml", "backup", "--set", "daily"],
    ],
)
def test_commands_with_unmigrated_semantics_use_legacy(arguments: list[str]) -> None:
    assert compatibility.should_use_legacy(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--help"],
        ["run", "local-main"],
        ["view"],
        ["view", "audit"],
        ["config", "effective"],
        ["schedule", "discover"],
        ["restore", "preview", "latest", "--target", "restore"],
        ["repository", "status"],
        ["stats"],
        ["check"],
        ["progress"],
    ],
)
def test_migrated_or_canonical_commands_use_application(arguments: list[str]) -> None:
    assert not compatibility.should_use_legacy(arguments)


def test_main_delegates_legacy_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cli = ModuleType("rrbackup.cli")
    captured: list[list[str]] = []

    def fake_main(arguments: list[str]) -> int:
        captured.append(arguments)
        return 17

    fake_cli.main = fake_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rrbackup.cli", fake_cli)

    result = compatibility.main(["backup", "--set", "daily"])

    assert result == 17
    assert captured == [["backup", "--set", "daily"]]


def test_main_delegates_canonical_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_main(arguments: list[str]) -> int:
        captured.append(arguments)
        return 23

    monkeypatch.setattr(compatibility.application, "main", fake_main)

    result = compatibility.main(["view", "audit"])

    assert result == 23
    assert captured == [["view", "audit"]]
