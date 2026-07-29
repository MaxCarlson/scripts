"""Health evaluation for snapshots, runs, locks, and required inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .locking import LockInspection
from .models import RunRecord, RunState, ensure_utc, utc_now
from .profile import BackupProfile
from .snapshots import SnapshotRecord


class HealthSeverity(str, Enum):
    """Ordered health severity."""

    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


_SEVERITY_ORDER = {
    HealthSeverity.OK: 0,
    HealthSeverity.INFO: 1,
    HealthSeverity.WARNING: 2,
    HealthSeverity.CRITICAL: 3,
}


@dataclass(frozen=True)
class HealthIssue:
    """One actionable health finding."""

    code: str
    severity: HealthSeverity
    message: str
    recommendation: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the health issue."""

        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "recommendation": self.recommendation,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class HealthReport:
    """Combined health state for one backup profile."""

    profile: str
    severity: HealthSeverity
    generated_utc: datetime
    latest_snapshot: Optional[SnapshotRecord]
    latest_run: Optional[RunRecord]
    issues: Sequence[HealthIssue]

    @property
    def healthy(self) -> bool:
        """Whether no warning or critical issue exists."""

        return _SEVERITY_ORDER[self.severity] < _SEVERITY_ORDER[HealthSeverity.WARNING]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the report."""

        return {
            "profile": self.profile,
            "severity": self.severity.value,
            "healthy": self.healthy,
            "generated_utc": self.generated_utc.isoformat(),
            "latest_snapshot": (
                None if self.latest_snapshot is None else self.latest_snapshot.to_dict()
            ),
            "latest_run": None if self.latest_run is None else self.latest_run.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _highest_severity(issues: Sequence[HealthIssue]) -> HealthSeverity:
    if not issues:
        return HealthSeverity.OK
    return max(issues, key=lambda issue: _SEVERITY_ORDER[issue.severity]).severity


def evaluate_health(
    profile: BackupProfile,
    *,
    snapshots: Sequence[SnapshotRecord],
    latest_run: Optional[RunRecord],
    lock: LockInspection,
    now: Optional[datetime] = None,
) -> HealthReport:
    """Evaluate current backup health without mutating any state."""

    generated = ensure_utc(now or utc_now())
    ordered = sorted(snapshots, key=lambda snapshot: snapshot.time, reverse=True)
    latest_snapshot = ordered[0] if ordered else None
    issues: List[HealthIssue] = []

    required_paths = {
        "password-file": profile.password_file,
        "sources-file": profile.sources_file,
    }
    optional_paths = {"excludes-file": profile.excludes_file}
    for code, raw_path in required_paths.items():
        if not raw_path or not Path(raw_path).exists():
            issues.append(
                HealthIssue(
                    code="missing-{0}".format(code),
                    severity=HealthSeverity.CRITICAL,
                    message="Required {0} is missing: {1}".format(code, raw_path),
                    recommendation="Correct the profile path before running a backup.",
                )
            )
    for code, raw_path in optional_paths.items():
        if raw_path and not Path(raw_path).exists():
            issues.append(
                HealthIssue(
                    code="missing-{0}".format(code),
                    severity=HealthSeverity.WARNING,
                    message="Configured {0} is missing: {1}".format(code, raw_path),
                    recommendation="Restore the file or remove the configuration value.",
                )
            )

    if latest_snapshot is None:
        issues.append(
            HealthIssue(
                code="no-snapshots",
                severity=HealthSeverity.CRITICAL,
                message="No snapshots were found for this profile.",
                recommendation="Verify repository access and run a controlled backup.",
            )
        )
    else:
        snapshot_time = ensure_utc(latest_snapshot.time)
        age = max(0.0, (generated - snapshot_time).total_seconds())
        threshold = profile.cpu_policy.overdue_after.total_seconds()
        if age > threshold:
            issues.append(
                HealthIssue(
                    code="backup-overdue",
                    severity=HealthSeverity.CRITICAL,
                    message=(
                        "Latest snapshot is {0:.2f} day(s) old; expected within {1:.2f} day(s)."
                    ).format(age / 86400.0, threshold / 86400.0),
                    recommendation="Inspect schedule and run history, then run a backup when safe.",
                    details={
                        "snapshot_id": latest_snapshot.snapshot_id,
                        "age_seconds": age,
                        "threshold_seconds": threshold,
                    },
                )
            )

    if latest_run is not None:
        if latest_run.state in {RunState.FAILURE, RunState.INTERRUPTED}:
            issues.append(
                HealthIssue(
                    code="latest-run-{0}".format(latest_run.state.value),
                    severity=HealthSeverity.CRITICAL,
                    message="Latest run ended as {0}: {1}".format(
                        latest_run.state.value,
                        latest_run.reason or "no reason recorded",
                    ),
                    recommendation="Review the run record and log before retrying.",
                    details={"run_id": latest_run.run_id},
                )
            )
        elif latest_run.state == RunState.SKIPPED:
            issues.append(
                HealthIssue(
                    code="latest-run-skipped",
                    severity=HealthSeverity.WARNING,
                    message="Latest attempted run was skipped: {0}".format(
                        latest_run.reason or "no reason recorded"
                    ),
                    recommendation="Confirm a later successful snapshot exists or adjust policy.",
                    details={"run_id": latest_run.run_id},
                )
            )
        elif latest_run.state in {RunState.QUEUED, RunState.WAITING, RunState.RUNNING}:
            issues.append(
                HealthIssue(
                    code="run-in-progress",
                    severity=HealthSeverity.INFO,
                    message="A run is currently recorded as {0}.".format(
                        latest_run.state.value
                    ),
                    details={"run_id": latest_run.run_id},
                )
            )

    if lock.exists and not lock.valid:
        issues.append(
            HealthIssue(
                code="invalid-lock",
                severity=HealthSeverity.CRITICAL,
                message=lock.reason,
                recommendation="Inspect the lock manually; it will not be removed automatically.",
            )
        )
    elif lock.stale:
        issues.append(
            HealthIssue(
                code="stale-lock",
                severity=HealthSeverity.WARNING,
                message=lock.reason,
                recommendation="Use the future explicit stale-lock cleanup command after review.",
            )
        )
    elif lock.active:
        issues.append(
            HealthIssue(
                code="active-lock",
                severity=HealthSeverity.INFO,
                message=lock.reason,
                details={
                    "pid": None if lock.identity is None else lock.identity.pid,
                },
            )
        )

    return HealthReport(
        profile=profile.name,
        severity=_highest_severity(issues),
        generated_utc=generated,
        latest_snapshot=latest_snapshot,
        latest_run=latest_run,
        issues=tuple(issues),
    )
