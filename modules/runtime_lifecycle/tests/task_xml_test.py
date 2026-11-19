from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from runtime_lifecycle import (
    BootTrigger,
    CalendarTrigger,
    LogonTrigger,
    RepeatingIntervalTrigger,
    TaskPrincipal,
    TaskSpec,
    parse_task_xml,
    render_task_xml,
    semantic_diff,
    spec_hash,
)


NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def _task(**changes: object) -> TaskSpec:
    values: dict[str, object] = {
        "owner": "snips",
        "name": "runtime",
        "executable": Path("C:/Python/pythonw.exe"),
        "args": ("-m", "snips.cli", "ensure-runtime", "--apply"),
        "working_dir": Path("C:/Users/test/snips"),
        "principal": TaskPrincipal(sid="S-1-5-21-123-456-789-1001"),
        "triggers": (LogonTrigger(), RepeatingIntervalTrigger(interval="PT1M")),
    }
    values.update(changes)
    return TaskSpec(**values)  # type: ignore[arg-type]


def test_render_task_xml_sets_interactive_security_and_explicit_settings() -> None:
    xml = render_task_xml(_task())
    root = ET.fromstring(xml)

    assert root.findtext("t:Principals/t:Principal/t:UserId", namespaces=NS) == "S-1-5-21-123-456-789-1001"
    assert root.findtext("t:Principals/t:Principal/t:LogonType", namespaces=NS) == "InteractiveToken"
    assert root.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=NS) == "LeastPrivilege"
    assert root.findtext("t:Settings/t:DisallowStartIfOnBatteries", namespaces=NS) == "false"
    assert root.findtext("t:Settings/t:StopIfGoingOnBatteries", namespaces=NS) == "false"
    assert root.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=NS) == "IgnoreNew"
    assert root.findtext("t:Settings/t:StartWhenAvailable", namespaces=NS) == "true"
    assert root.findtext("t:Settings/t:ExecutionTimeLimit", namespaces=NS) == "PT2M"
    assert root.findtext("t:Settings/t:Hidden", namespaces=NS) == "true"
    assert root.findtext("t:Actions/t:Exec/t:WorkingDirectory", namespaces=NS) == "C:\\Users\\test\\snips"
    assert root.findtext("t:Triggers/t:LogonTrigger/t:UserId", namespaces=NS) == "S-1-5-21-123-456-789-1001"
    assert root.findtext("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", namespaces=NS) == "PT1M"


def test_render_task_xml_escapes_description_command_and_arguments() -> None:
    task = _task(
        executable=Path("C:/Program Files/Tools & More/pythonw.exe"),
        args=("--label", 'A&B <"quoted">'),
        description="User's task <managed> & safe",
    )
    xml = render_task_xml(task)
    root = ET.fromstring(xml)

    assert root.findtext("t:Actions/t:Exec/t:Command", namespaces=NS) == "C:\\Program Files\\Tools & More\\pythonw.exe"
    args = root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS)
    assert args is not None and "A&B" in args and "quoted" in args
    description = root.findtext("t:RegistrationInfo/t:Description", namespaces=NS)
    assert description is not None and "User's task <managed> & safe" in description
    assert "&amp;" in xml.decode("utf-16") and "&lt;managed&gt;" in xml.decode("utf-16")


def test_spec_hash_is_deterministic_and_excludes_description() -> None:
    task = _task()
    assert spec_hash(task) == spec_hash(task)
    assert spec_hash(task) == spec_hash(_task(description="different operator note"))
    assert spec_hash(task) != spec_hash(_task(working_dir=Path("C:/different")))


@pytest.mark.parametrize("owner", ["", "UPPER", "two words", "../outside", "a\\b"])
def test_task_spec_rejects_invalid_owner(owner: str) -> None:
    with pytest.raises(ValueError, match="owner"):
        _task(owner=owner)


@pytest.mark.parametrize("sid", ["", "1001", "S-1-5-21-not-a-sid"])
def test_task_spec_rejects_malformed_sid(sid: str) -> None:
    with pytest.raises(ValueError, match="SID"):
        _task(principal=TaskPrincipal(sid=sid))


def test_repeating_trigger_rejects_zero_interval() -> None:
    with pytest.raises(ValueError, match="PT1M"):
        RepeatingIntervalTrigger(interval="PT0S")


def test_repeating_trigger_rejects_malformed_interval() -> None:
    with pytest.raises(ValueError, match="ISO-8601"):
        RepeatingIntervalTrigger(interval="not-a-duration")


def test_task_spec_requires_absolute_paths_and_valid_name() -> None:
    with pytest.raises(ValueError, match="absolute"):
        _task(executable=Path("pythonw.exe"))
    with pytest.raises(ValueError, match="name"):
        _task(name="../other")
    with pytest.raises(ValueError, match="folder"):
        _task(folder=r"\Scripts\..\Windows")


@pytest.mark.parametrize(
    "trigger, expected_tag",
    [
        (LogonTrigger(delay="PT5S"), "LogonTrigger"),
        (BootTrigger(delay="PT10S"), "BootTrigger"),
        (RepeatingIntervalTrigger(interval="PT1M"), "TimeTrigger"),
        (CalendarTrigger("once"), "TimeTrigger"),
        (CalendarTrigger("daily"), "CalendarTrigger"),
        (CalendarTrigger("weekly", days_of_week=("Monday",)), "CalendarTrigger"),
        (CalendarTrigger("monthly", days_of_month=(1, 15), months=(1, 6)), "CalendarTrigger"),
    ],
)
def test_all_trigger_types_render(trigger: object, expected_tag: str) -> None:
    root = ET.fromstring(render_task_xml(_task(triggers=(trigger,))))
    assert root.find(f"t:Triggers/t:{expected_tag}", NS) is not None


def test_render_task_xml_is_utf16le_and_emits_restart_policy() -> None:
    xml = render_task_xml(_task(restart_count=3, restart_interval="PT1M"))
    assert xml.startswith(b"\xff\xfe")
    decoded = xml.decode("utf-16")
    assert decoded.startswith('<?xml version="1.0" encoding="UTF-16"?>')
    root = ET.fromstring(xml)
    assert root.findtext("t:Settings/t:RestartOnFailure/t:Interval", namespaces=NS) == "PT1M"
    assert root.findtext("t:Settings/t:RestartOnFailure/t:Count", namespaces=NS) == "3"


def test_system_principal_is_normalized_for_service_account_tasks() -> None:
    task = _task(principal=TaskPrincipal.system())
    root = ET.fromstring(render_task_xml(task))
    assert task.principal_sid == "S-1-5-18"
    assert root.findtext("t:Principals/t:Principal/t:UserId", namespaces=NS) == "S-1-5-18"
    assert root.findtext("t:Principals/t:Principal/t:LogonType", namespaces=NS) == "ServiceAccount"
    assert root.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=NS) == "HighestAvailable"


def test_canonical_xml_round_trip_has_no_semantic_drift() -> None:
    task = _task()
    parsed = parse_task_xml(render_task_xml(task))
    assert parsed.owner == "snips"
    assert parsed.name == "runtime"
    assert parsed.spec_hash == spec_hash(task)
    assert parsed.principal_sid == task.principal_sid
    assert semantic_diff(task, parsed) == {}


def test_parser_accepts_utf8_xml_and_semantic_diff_finds_manual_edit() -> None:
    task = _task()
    xml = render_task_xml(task).decode("utf-16")
    xml = xml.replace("C:\\Python\\pythonw.exe", "C:\\Other\\pythonw.exe")
    utf8_xml = xml.replace('encoding="UTF-16"', 'encoding="UTF-8"')
    parsed = parse_task_xml(utf8_xml.encode("utf-8"))
    assert parsed.executable == "C:\\Other\\pythonw.exe"
    assert "executable" in semantic_diff(task, parsed)


def test_semantic_diff_detects_manual_restart_policy_edit() -> None:
    task = _task(restart_count=2, restart_interval="PT1M")
    xml = render_task_xml(task).decode("utf-16").replace("<Count>2</Count>", "<Count>4</Count>")
    parsed = parse_task_xml(xml)
    assert "settings" in semantic_diff(task, parsed)


def test_render_uses_lowercase_principal_id_attribute() -> None:
    decoded = render_task_xml(_task()).decode("utf-16")
    assert '<Principal id="Author">' in decoded
    assert 'Id="Author"' not in decoded


def test_parse_task_xml_accepts_schtasks_utf8_with_utf16_declaration_and_omitted_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime_lifecycle import xml as xml_module

    task = _task()
    exported_like = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>managed-by=runtime_lifecycle; owner=snips; name=runtime; schema=1; spec_hash={spec_hash(task)}</Description>
    <URI>\\Scripts\\snips-runtime</URI>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-21-123-456-789-1001</UserId>
      <LogonType>InteractiveToken</LogonType>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT2M</ExecutionTimeLimit>
    <Hidden>true</Hidden>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
  </Settings>
  <Triggers>
    <LogonTrigger>
      <Delay>PT5S</Delay>
      <UserId>TESTHOST\\alice</UserId>
    </LogonTrigger>
    <TimeTrigger>
      <StartBoundary>2020-01-01T00:00:00</StartBoundary>
      <Repetition>
        <Interval>PT1M</Interval>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>C:\\Python\\pythonw.exe</Command>
      <Arguments>-m snips.cli ensure-runtime --apply</Arguments>
      <WorkingDirectory>C:\\Users\\test\\snips</WorkingDirectory>
    </Exec>
  </Actions>
</Task>""".encode("utf-8")

    monkeypatch.setattr(
        xml_module,
        "resolve_account_sid",
        lambda value: "S-1-5-21-123-456-789-1001"
        if value in {"TESTHOST\\alice", "S-1-5-21-123-456-789-1001"}
        else None,
    )
    parsed = parse_task_xml(exported_like)
    assert parsed.run_level == "LeastPrivilege"
    assert parsed.enabled is True
    assert semantic_diff(task, parsed) == {}
