"""Unit and safety tests for Phase 3 Windows trigger auditor (`task_auditor`)."""

from __future__ import annotations

import json
from pathlib import Path

from procwatch.analyzers.task_auditor import (
    apply_task_fix_preview_or_xml,
    parse_task_definition_xml,
    run_audit,
)
from procwatch.cli import main
from procwatch.models import EdgeRelation, EvidenceEdge, IncidentRecord
from procwatch.storage import FlightRecorderStorage

SAMPLE_TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Principals>
    <Principal id="Author">
      <UserId>WORKSTATION\\mcarls</UserId>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
  </Settings>
  <Triggers>
    <TimeTrigger><StartBoundary>2026-11-15T00:00:00</StartBoundary></TimeTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>C:\\Python312\\python.exe</Command>
      <Arguments>worker.py --token=SecretTok123</Arguments>
      <WorkingDirectory>C:\\work</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def test_parse_task_xml_and_redaction() -> None:
    finding = parse_task_definition_xml(SAMPLE_TASK_XML, task_path=r"\Custom\WorkerPoll")
    assert finding is not None
    assert finding.enabled is True
    assert finding.hidden_flag is False
    assert finding.executable == r"C:\Python312\python.exe"
    assert "SecretTok123" not in (finding.arguments_redacted or "")
    assert finding.working_dir == r"C:\work"
    assert finding.evidence_rank == "configured_only"
    assert finding.remediation_status == "not_applicable_yet"


def test_task_fix_dry_run_phase4_wrap_and_backup(tmp_path: Path) -> None:
    finding = parse_task_definition_xml(SAMPLE_TASK_XML, task_path=r"\Custom\WorkerPoll")
    assert finding is not None and finding.raw_xml_sha256

    # Phase 4 `procwatch exec` wrapper preview is now supported and non-mutating by default.
    wrap_preview = apply_task_fix_preview_or_xml(
        task_path=r"\Custom\WorkerPoll",
        original_xml=SAMPLE_TASK_XML,
        proposed_command="procwatch",
        proposed_arguments="exec -- C:\\Python312\\python.exe worker.py",
        expected_sha256=finding.raw_xml_sha256,
        apply_fix=False,
        backup_dir=tmp_path,
    )
    assert wrap_preview["status"] == "dry_run_preview"

    # Dry-run preview mutates nothing.
    preview = apply_task_fix_preview_or_xml(
        task_path=r"\Custom\WorkerPoll",
        original_xml=SAMPLE_TASK_XML,
        proposed_command=r"C:\Python312\pythonw.exe",
        proposed_arguments="worker.py",
        expected_sha256=finding.raw_xml_sha256,
        apply_fix=False,
        backup_dir=tmp_path,
    )
    assert preview["status"] == "dry_run_preview"
    assert list(tmp_path.glob("*.xml")) == []

    # Explicit apply writes backup XML and rollback command.
    applied = apply_task_fix_preview_or_xml(
        task_path=r"\Custom\WorkerPoll",
        original_xml=SAMPLE_TASK_XML,
        proposed_command=r"C:\Python312\pythonw.exe",
        proposed_arguments="worker.py",
        expected_sha256=finding.raw_xml_sha256,
        apply_fix=True,
        backup_dir=tmp_path,
    )
    assert applied["status"] == "prepared_with_backup"
    assert Path(applied["backup_path"]).exists()
    assert "schtasks /Create" in applied["rollback_command"]


def test_audit_correlates_with_storage_and_cli_json(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "audit.db"
    storage = FlightRecorderStorage(db_path=db_path)
    try:
        storage.insert_edge(
            EvidenceEdge(
                from_node_id="canon:b1:123:1",
                to_node_id=r"task:\Custom\WorkerPoll",
                relation=EdgeRelation.TRIGGERED_BY,
                source="task_events",
                method="task_event_129",
                confidence=0.92,
            )
        )
        storage.insert_incident(
            IncidentRecord(
                created_ts_utc="2099-01-01T00:00:00.000Z",
                category="visible_popup",
                summary_text=r"Popup from \Custom\WorkerPoll python.exe",
            )
        )
    finally:
        storage.close()

    report = run_audit(target_type="defterm", db_path=db_path)
    assert report.target_type == "defterm"
    assert len(report.findings) == 1
    assert report.findings[0].source_type == "defterm"

    rc = main(["audit", "-t", "defterm", "-j", "-D", str(db_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == 1
    assert out["target_type"] == "defterm"
