"""Interactive, preview-first creation and schedule editing workflows."""

from __future__ import annotations

import copy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import (
    BackupSet,
    Repo,
    RetentionPolicy,
    Schedule,
    Settings,
    load_config,
    resolve_config_path,
    save_config,
)
from .inventory import (
    BackupDefinition,
    BackupInventoryRecord,
    load_definitions,
    settings_from_definitions,
    upsert_backup_set,
)
from .presentation import Palette, browse_backups, palette, render_backup_table
from .profile import DEFAULT_PASSWORD_FILE, DEFAULT_REPOSITORY
from .schedule_math import describe_retention, describe_schedule, normalize_schedule_type
from .scheduler_management import (
    ScheduleApplyResult,
    SchedulePlan,
    apply_schedule_plan,
    build_schedule_plan,
)


class WizardCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class ScheduleWizardSelection:
    backup_names: Tuple[str, ...]
    schedule: Schedule
    retention: RetentionPolicy

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backup_names": list(self.backup_names),
            "schedule": self.schedule.to_dict(),
            "schedule_text": describe_schedule(self.schedule),
            "retention": self.retention.to_dict(),
            "retention_text": describe_retention(self.retention),
        }


@dataclass(frozen=True)
class CreateWizardSelection:
    backup_set: BackupSet
    repository: str
    password_file: str
    config_path: Path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.backup_set.name,
            "sources": list(self.backup_set.include),
            "excludes": list(self.backup_set.exclude),
            "tags": list(self.backup_set.tags),
            "repository": self.repository,
            "password_file": self.password_file,
            "schedule": self.backup_set.schedule.to_dict(),
            "schedule_text": describe_schedule(self.backup_set.schedule),
            "retention": (
                None
                if self.backup_set.retention is None
                else self.backup_set.retention.to_dict()
            ),
            "retention_text": describe_retention(self.backup_set.retention),
            "config_path": str(self.config_path),
            "use_fs_snapshot": self.backup_set.use_fs_snapshot,
            "exclude_caches": self.backup_set.exclude_caches,
        }


def _require_tty() -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ValueError("The interactive wizard requires a terminal. Use explicit CLI options or JSON input in automation.")


def _prompt(text: str, *, default: Optional[str] = None, required: bool = False) -> str:
    suffix = "" if default is None else " [{0}]".format(default)
    while True:
        value = input("{0}{1}: ".format(text, suffix)).strip()
        if not value and default is not None:
            return default
        if value or not required:
            return value
        print("A value is required.", file=sys.stderr)


def _prompt_choice(
    text: str,
    choices: Sequence[str],
    *,
    default: str,
    colors: Palette,
) -> str:
    normalized = {value.lower(): value for value in choices}
    print(colors.heading(text))
    print("  " + "  ".join("{0}:{1}".format(index + 1, value) for index, value in enumerate(choices)))
    while True:
        raw = input("Choice [{0}]: ".format(default)).strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        if raw.lower() in normalized:
            return normalized[raw.lower()]
        print("Choose one of: {0}".format(", ".join(choices)), file=sys.stderr)


def _prompt_int(
    text: str,
    *,
    default: Optional[int],
    minimum: int = 0,
    maximum: Optional[int] = None,
) -> Optional[int]:
    suffix = "" if default is None else " [{0}]".format(default)
    while True:
        raw = input("{0}{1}: ".format(text, suffix)).strip()
        if not raw:
            return default
        if raw.lower() in {"none", "off", "-"}:
            return None
        try:
            value = int(raw)
        except ValueError:
            print("Enter an integer, 'none', or press Enter for the default.", file=sys.stderr)
            continue
        if value < minimum or (maximum is not None and value > maximum):
            print("Value must be between {0} and {1}.".format(minimum, maximum or "unbounded"), file=sys.stderr)
            continue
        return value


def _prompt_paths(text: str, *, default: Sequence[str] = ()) -> List[str]:
    shown = "; ".join(default)
    raw = _prompt(text + " (semicolon-separated)", default=shown)
    values = [value.strip() for value in raw.split(";") if value.strip()]
    if not values:
        raise ValueError("At least one source path is required.")
    return list(dict.fromkeys(values))


def prompt_schedule(
    *,
    default: Optional[Schedule] = None,
    colors: Optional[Palette] = None,
) -> Schedule:
    theme = colors or palette()
    current = default or Schedule()
    choices = ("manual", "minute", "hourly", "daily", "weekly", "monthly", "yearly")
    kind = _prompt_choice(
        "Schedule frequency",
        choices,
        default=normalize_schedule_type(current.type) if normalize_schedule_type(current.type) in choices else "manual",
        colors=theme,
    )
    if kind == "manual":
        return Schedule(type="manual", description="Run manually")
    interval = _prompt_int("Run every N {0}(s)".format(kind.rstrip("ly")), default=max(1, current.interval), minimum=1) or 1
    time_value = current.time or "03:00"
    if kind == "minute":
        time_value = None
    elif kind == "hourly":
        minute = _prompt_int("Minute within the hour", default=int(time_value.split(":")[-1]), minimum=0, maximum=59) or 0
        time_value = "00:{0:02d}".format(minute)
    else:
        time_value = _prompt("Time of day (HH:MM)", default=time_value, required=True)

    day_of_week = current.day_of_week
    day_of_month = current.day_of_month
    month_of_year = current.month_of_year
    if kind == "weekly":
        day_of_week = _prompt("Weekday", default=day_of_week or "Sunday", required=True)
    if kind in {"monthly", "yearly"}:
        day_of_month = _prompt_int("Day of month", default=day_of_month or 1, minimum=1, maximum=31)
    if kind == "yearly":
        month_of_year = _prompt_int("Month number", default=month_of_year or 1, minimum=1, maximum=12)
    return Schedule(
        type=kind,
        time=time_value,
        interval=interval,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
    )


def prompt_retention(
    *,
    default: Optional[RetentionPolicy] = None,
    colors: Optional[Palette] = None,
) -> RetentionPolicy:
    theme = colors or palette()
    current = default or RetentionPolicy()
    print(theme.heading("Retention policy"))
    print(theme.muted("Configure counts only. No snapshots are forgotten or pruned by this wizard."))
    return RetentionPolicy(
        keep_last=_prompt_int("Keep latest", default=current.keep_last, minimum=0),
        keep_hourly=_prompt_int("Keep hourly", default=current.keep_hourly, minimum=0),
        keep_daily=_prompt_int("Keep daily", default=current.keep_daily, minimum=0),
        keep_weekly=_prompt_int("Keep weekly", default=current.keep_weekly, minimum=0),
        keep_monthly=_prompt_int("Keep monthly", default=current.keep_monthly, minimum=0),
        keep_yearly=_prompt_int("Keep yearly", default=current.keep_yearly, minimum=0),
        max_total_size=current.max_total_size,
        max_total_size_bytes=current.max_total_size_bytes,
    )


def _plain_select_records(
    records: Sequence[BackupInventoryRecord],
    *,
    colors: Palette,
    multiple: bool,
) -> List[BackupInventoryRecord]:
    print(render_backup_table(records, colors=colors, include_repository=True))
    raw = _prompt(
        "Backup name{0}".format("s (comma-separated)" if multiple else ""),
        required=True,
    )
    names = [value.strip().lower() for value in raw.split(",") if value.strip()]
    selected = [record for record in records if record.definition.name.lower() in names]
    if not selected:
        raise ValueError("No configured backup matched the selection.")
    if not multiple and len(selected) != 1:
        raise ValueError("Select exactly one backup.")
    return selected


def select_records(
    records: Sequence[BackupInventoryRecord],
    *,
    title: str,
    multiple: bool,
    action_key: str,
    action_label: str,
    colors: Optional[Palette] = None,
) -> List[BackupInventoryRecord]:
    theme = colors or palette()
    selected = browse_backups(
        records,
        title=title,
        multi_select=multiple,
        action_key=action_key,
        action_label=action_label,
    )
    if selected:
        return selected
    return _plain_select_records(records, colors=theme, multiple=multiple)


def _settings_for_records(records: Sequence[BackupInventoryRecord]) -> Settings:
    definitions = [record.definition for record in records]
    existing = next(
        (definition.settings for definition in definitions if definition.settings is not None),
        None,
    )
    return settings_from_definitions(definitions, existing=copy.deepcopy(existing))


def run_schedule_wizard(
    records: Sequence[BackupInventoryRecord],
    *,
    config_path: Optional[str],
    names: Sequence[str] = (),
    apply: bool = False,
    colors: Optional[Palette] = None,
) -> Dict[str, Any]:
    """Edit schedule/retention, preview plans, and optionally apply."""

    _require_tty()
    theme = colors or palette()
    if names:
        wanted = {value.lower() for value in names}
        selected = [record for record in records if record.definition.name.lower() in wanted]
        if len(selected) != len(wanted):
            raise ValueError("One or more requested backup names were not found.")
    else:
        selected = select_records(
            records,
            title="RRBackup Schedule Editor",
            multiple=True,
            action_key="e",
            action_label="edit selected backups",
            colors=theme,
        )

    default_schedule = selected[0].definition.schedule
    default_retention = selected[0].definition.retention
    schedule = prompt_schedule(default=default_schedule, colors=theme)
    retention = prompt_retention(default=default_retention, colors=theme)
    selection = ScheduleWizardSelection(
        backup_names=tuple(record.definition.name for record in selected),
        schedule=schedule,
        retention=retention,
    )

    all_definitions, _ = load_definitions(config_path)
    selected_names = {record.definition.name.lower() for record in selected}
    for definition in all_definitions:
        if definition.name.lower() in selected_names:
            definition.schedule = schedule
            definition.retention = retention
    target = resolve_config_path(config_path)
    if target.suffix.lower() == ".json":
        target = resolve_config_path(None)
    settings = settings_from_definitions(all_definitions)
    plans = [
        build_schedule_plan(
            definition,
            config_path=str(target),
        )
        for definition in all_definitions
        if definition.name.lower() in selected_names
    ]

    print(theme.heading("Schedule change preview"))
    print("  Backups:   {0}".format(", ".join(selection.backup_names)))
    print("  Schedule:  {0}".format(describe_schedule(schedule)))
    print("  Retention: {0}".format(describe_retention(retention)))
    print("  Config:    {0}".format(target))
    for plan in plans:
        print("  Scheduler: {0}".format(plan.render_scheduler_command()))
    print(theme.warning("No retention action is executed by this workflow."))

    results: List[ScheduleApplyResult] = []
    if apply:
        save_config(settings, target, overwrite=True)
        results = [apply_schedule_plan(plan, apply=True) for plan in plans]
    return {
        "mode": "apply" if apply else "preview",
        "selection": selection.to_dict(),
        "config_path": str(target),
        "plans": [plan.to_dict() for plan in plans],
        "results": [result.to_dict() for result in results],
    }


def prompt_create_selection(
    *,
    config_path: Optional[str],
    colors: Optional[Palette] = None,
) -> CreateWizardSelection:
    _require_tty()
    theme = colors or palette()
    target = resolve_config_path(config_path)
    if target.suffix.lower() == ".json":
        target = resolve_config_path(None)

    print(theme.heading("Create backup"))
    print(theme.muted("Nothing is written or scheduled until the final explicit apply step."))
    name = _prompt("Backup name", required=True)
    sources = _prompt_paths("Source paths")
    excludes_raw = _prompt("Exclusions (semicolon-separated)", default="")
    excludes = [value.strip() for value in excludes_raw.split(";") if value.strip()]
    repository = _prompt("Repository target", default=DEFAULT_REPOSITORY, required=True)
    password_file = _prompt("Restic password file", default=DEFAULT_PASSWORD_FILE, required=True)
    tag = _prompt("Snapshot tag", default=name, required=True)
    schedule = prompt_schedule(colors=theme)
    retention = prompt_retention(colors=theme)
    backup_set = BackupSet(
        name=name,
        include=sources,
        exclude=excludes,
        tags=[tag],
        schedule=schedule,
        retention=retention,
        use_fs_snapshot=True,
        exclude_caches=True,
    )
    return CreateWizardSelection(
        backup_set=backup_set,
        repository=repository,
        password_file=password_file,
        config_path=target,
    )


def run_create_wizard(
    *,
    config_path: Optional[str],
    apply: bool = False,
    colors: Optional[Palette] = None,
) -> Dict[str, Any]:
    """Create or update a canonical backup definition with preview-first safety."""

    theme = colors or palette()
    selection = prompt_create_selection(config_path=config_path, colors=theme)
    target = selection.config_path
    if target.exists():
        settings = load_config(target, expand=False)
        if settings.repo and settings.repo.url != selection.repository:
            raise ValueError(
                "This configuration currently supports one repository. The selected repository "
                "does not match the existing configuration."
            )
    else:
        settings = Settings(
            repo=Repo(
                url=selection.repository,
                password_file=selection.password_file,
            )
        )
    if settings.repo is None:
        settings.repo = Repo(
            url=selection.repository,
            password_file=selection.password_file,
        )
    upsert_backup_set(settings, selection.backup_set)

    print(theme.heading("Backup creation preview"))
    for key, value in selection.to_dict().items():
        print("  {0:<18} {1}".format(key.replace("_", " ").title() + ":", value))
    print(theme.warning("Repository initialization and retention application are not automatic."))

    plans: List[SchedulePlan] = []
    results: List[ScheduleApplyResult] = []
    if apply:
        save_config(settings, target, overwrite=True)
        definitions, _ = load_definitions(str(target))
        definition = next(
            value
            for value in definitions
            if value.name.lower() == selection.backup_set.name.lower()
        )
        if normalize_schedule_type(definition.schedule.type) != "manual":
            plan = build_schedule_plan(definition, config_path=str(target))
            plans.append(plan)
            results.append(apply_schedule_plan(plan, apply=True))
    return {
        "mode": "apply" if apply else "preview",
        "selection": selection.to_dict(),
        "plans": [plan.to_dict() for plan in plans],
        "results": [result.to_dict() for result in results],
    }
