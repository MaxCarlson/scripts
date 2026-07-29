"""Tests for the unified backup CLI command and audit contract."""

from __future__ import annotations

import pytest

from rrbackup.command_contract import (
    AUDIT_SECTIONS,
    AUDIT_SECTION_NAMES,
    CANONICAL_PROGRAM,
    COMMAND_ALIASES,
    COMPATIBILITY_PROGRAMS,
    MAJOR_COMMANDS,
    OPTIONAL_AUDIT_SECTIONS,
    SENSITIVE_AUDIT_SECTIONS,
    VIEW_SECTIONS,
    get_audit_section,
    resolve_major_command,
)


@pytest.mark.unit
def test_canonical_and_compatibility_programs() -> None:
    assert CANONICAL_PROGRAM == "backup"
    assert COMPATIBILITY_PROGRAMS == ("backup_module",)


@pytest.mark.unit
def test_exact_seven_major_command_areas() -> None:
    assert MAJOR_COMMANDS == (
        "create",
        "run",
        "view",
        "schedule",
        "restore",
        "repo",
        "config",
    )
    assert len(MAJOR_COMMANDS) == len(set(MAJOR_COMMANDS)) == 7


@pytest.mark.unit
def test_task_oriented_view_sections() -> None:
    assert VIEW_SECTIONS == (
        "overview",
        "backups",
        "history",
        "repository",
        "schedules",
        "diagnostics",
        "audit",
    )


@pytest.mark.unit
def test_command_aliases_resolve() -> None:
    assert COMMAND_ALIASES == {"edit": "config", "repository": "repo"}
    assert resolve_major_command("edit") == "config"
    assert resolve_major_command("repository") == "repo"
    assert resolve_major_command(" CONFIG ") == "config"


@pytest.mark.unit
def test_unknown_major_command_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported backup command area"):
        resolve_major_command("unknown")


@pytest.mark.unit
def test_audit_sections_are_unique_and_complete() -> None:
    assert len(AUDIT_SECTION_NAMES) == len(set(AUDIT_SECTION_NAMES))
    assert {section.name for section in AUDIT_SECTIONS} == set(AUDIT_SECTION_NAMES)
    assert {
        "commands",
        "runtime",
        "configuration",
        "environment",
        "config-files",
        "paths",
        "inputs",
        "repository",
        "keys",
        "snapshots",
        "runs",
        "logs",
        "locks",
        "schedules",
        "schedule-history",
        "launchers",
        "health",
        "provenance",
        "legacy-evidence",
        "recommendations",
    } == set(AUDIT_SECTION_NAMES)


@pytest.mark.unit
def test_sensitive_and_optional_audit_sections_are_explicit() -> None:
    assert SENSITIVE_AUDIT_SECTIONS == {
        "environment",
        "paths",
        "keys",
        "legacy-evidence",
    }
    assert OPTIONAL_AUDIT_SECTIONS == {
        "schedule-history",
        "launchers",
        "legacy-evidence",
    }


@pytest.mark.unit
def test_get_audit_section_normalizes_names() -> None:
    section = get_audit_section(" SNAPSHOTS ")

    assert section.name == "snapshots"
    assert section.sensitive is False
    assert section.optional is False


@pytest.mark.unit
def test_unknown_audit_section_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported audit section"):
        get_audit_section("unknown")
