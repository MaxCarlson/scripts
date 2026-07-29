"""Authoritative command and audit-section contract for the merged backup CLI."""

from __future__ import annotations

from dataclasses import dataclass


CANONICAL_PROGRAM = "backup"
COMPATIBILITY_PROGRAMS = ("rrb", "rrbackup", "backup_module")
MAJOR_COMMANDS = (
    "run",
    "view",
    "config",
    "schedule",
    "restore",
    "repository",
)
COMMAND_ALIASES = {"edit": "config"}


@dataclass(frozen=True, slots=True)
class AuditSection:
    """Describe one read-only section emitted by ``backup view audit``."""

    name: str
    description: str
    optional: bool = False
    sensitive: bool = False


AUDIT_SECTIONS = (
    AuditSection("commands", "CLI, executable, wrapper, and version resolution."),
    AuditSection("runtime", "Runtime, package, operating-system, host, and user information."),
    AuditSection(
        "configuration",
        "Effective configuration values and the source of every resolved value.",
    ),
    AuditSection(
        "environment",
        "Relevant process, user, and machine environment-variable definitions.",
        sensitive=True,
    ),
    AuditSection("config-files", "Canonical, legacy, and discovered configuration files."),
    AuditSection(
        "paths",
        "Safe metadata for repository, credential, source, exclusion, status, log, and lock paths.",
        sensitive=True,
    ),
    AuditSection("inputs", "Resolved source and exclusion entries."),
    AuditSection("repository", "Repository availability, format, version, and backend information."),
    AuditSection("keys", "Repository key metadata without key or password material.", sensitive=True),
    AuditSection("snapshots", "Snapshot count, IDs, times, hosts, users, tags, paths, parents, and versions."),
    AuditSection("runs", "Local run records, state transitions, and scheduler correlation IDs."),
    AuditSection("logs", "Recent module logs with configured redaction."),
    AuditSection("locks", "Active and stale process locks."),
    AuditSection("schedules", "Configured schedule definitions and backend details."),
    AuditSection("schedule-history", "Scheduler execution and event history when supported.", optional=True),
    AuditSection(
        "launchers",
        "Task Scheduler, services, startup commands, systemd timers, and cron launchers.",
        optional=True,
    ),
    AuditSection("health", "Missed-backup, overdue, configuration, repository, and scheduler health."),
    AuditSection("provenance", "Evidence-backed backup lineage and execution provenance."),
    AuditSection(
        "legacy-evidence",
        "Opt-in historical shell-command evidence for pre-module backup activity.",
        optional=True,
        sensitive=True,
    ),
    AuditSection("recommendations", "Warnings and ordered next actions."),
)


AUDIT_SECTION_NAMES = tuple(section.name for section in AUDIT_SECTIONS)
SENSITIVE_AUDIT_SECTIONS = frozenset(
    section.name for section in AUDIT_SECTIONS if section.sensitive
)
OPTIONAL_AUDIT_SECTIONS = frozenset(
    section.name for section in AUDIT_SECTIONS if section.optional
)


def resolve_major_command(name: str) -> str:
    """Resolve a major command or alias, raising for unsupported names."""
    normalized = name.strip().lower()
    resolved = COMMAND_ALIASES.get(normalized, normalized)
    if resolved not in MAJOR_COMMANDS:
        raise ValueError(f"Unsupported backup command area: {name!r}")
    return resolved


def get_audit_section(name: str) -> AuditSection:
    """Return one audit section by normalized name."""
    normalized = name.strip().lower()
    for section in AUDIT_SECTIONS:
        if section.name == normalized:
            return section
    raise ValueError(f"Unsupported audit section: {name!r}")
