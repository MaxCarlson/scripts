"""Width-independent Markdown summaries and atomic coordinator-owned publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import os
from pathlib import Path
import re
import tempfile
import time
from uuid import uuid4

from .report_models import CompressionReport
from .reporting import clean
from .workspace import CompressionWorkspace, _unlinked, initialize_workspace, workspace_publication


def _escape(value: str) -> str:
    return html.escape(clean(value)).replace("\\", "\\\\").replace("|", "\\|").replace("`", "&#96;")


def render_markdown_report(report: CompressionReport) -> str:
    lines = [
        f"# {_escape(report.title)}",
        "",
        f"Target: {_escape(report.target)}",
        "",
        f"Operation: {_escape(report.operation)} · Status: **{_escape(report.status)}** · Report schema {report.schema}",
        "",
    ]
    for section in report.sections:
        lines.extend(
            [
                f"## {_escape(section.title)}",
                "",
                "| " + " | ".join(_escape(h) for h in section.headers) + " |",
                "| " + " | ".join("---" for _ in section.headers) + " |",
            ]
        )
        lines.extend("| " + " | ".join(_escape(cell) for cell in row) + " |" for row in section.rows)
        lines.append("")
    lines.extend(["## Interpretation and next steps", ""])
    lines.extend(f"- {_escape(note)}" for note in report.notes)
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ReportArtifacts:
    archive_path: Path
    latest_path: Path

    def as_dict(self) -> dict:
        return {"archive": str(self.archive_path), "latest": str(self.latest_path)}


def _write_temp(directory: Path, content: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=".report-", suffix=".tmp", dir=directory)
    path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            if stream.write(content) != len(content):
                raise OSError("Short report write")
            stream.flush()
            os.fsync(stream.fileno())
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def publish_markdown_report(workspace: CompressionWorkspace, report: CompressionReport) -> ReportArtifacts:
    if not re.fullmatch(r"[a-z][a-z0-9-]*", report.operation):
        raise ValueError("Invalid report operation name")
    initialize_workspace(workspace)
    content = render_markdown_report(report)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%fZ")
    archive = workspace.reports_dir / f"{timestamp}-{uuid4().hex[:12]}-{report.operation}.md"
    latest = workspace.reports_dir / "latest.md"
    with workspace_publication(workspace):
        workspace.reports_dir.mkdir(exist_ok=True)
        _unlinked(latest)
        temp = _write_temp(workspace.reports_dir, content)
        try:
            # Exclusive atomic publication: no partial archive and no overwrite race.
            os.link(temp, archive)
            temp.unlink()
            temp = _write_temp(workspace.reports_dir, content)
            for attempt in range(4):
                try:
                    os.replace(temp, latest)
                    break
                except PermissionError as exc:
                    if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 3:
                        raise
                    time.sleep(0.05)
        except OSError as exc:
            raise OSError(
                f"Cannot publish report {archive} or update {latest}: {exc}. Check permissions/free space; an archive may already exist."
            ) from exc
        finally:
            temp.unlink(missing_ok=True)
    return ReportArtifacts(archive, latest)
