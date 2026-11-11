"""Incident lifecycle state machine, deduplication, and notification policy."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from notifications.exceptions import IncidentNotFoundError, InvalidTransitionError
from notifications.models import (
    EventEnvelopeV1,
    Incident,
    Occurrence,
    PublishResult,
    Transition,
)
from notifications.storage import StorageEngine


@dataclass(frozen=True)
class IncidentPolicy:
    """Configurable thresholds for incident deduplication and reminders."""

    cooldown_seconds: float = 300.0
    critical_cooldown_seconds: float = 60.0
    reminder_interval_seconds: float = 900.0
    max_outbox_queue_size: int = 10000


def _parse_time(ts_str: Optional[str]) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


class IncidentLifecycleEngine:
    """Manages state transitions, occurrences, deduplication, and outbox enqueueing."""

    def __init__(self, storage: StorageEngine, policy: Optional[IncidentPolicy] = None) -> None:
        self.storage = storage
        self.policy = policy or IncidentPolicy()

    def process_event(
        self,
        event: EventEnvelopeV1,
        providers: Optional[list[str]] = None,
        now: Optional[datetime] = None,
    ) -> PublishResult:
        """Process an event envelope, updating incident/occurrence state and outbox."""
        current_dt = now or datetime.now(timezone.utc)
        current_iso = current_dt.isoformat().replace("+00:00", "Z")
        target_providers = providers or ["default"]

        with self.storage.transaction() as conn:
            # Persist event to the immutable journal first
            is_new_event, _ = self.storage.record_event(event, conn=conn)

            incident = self.storage.get_incident(event.incident_id, conn=conn)

            if not is_new_event:
                # Idempotent duplicate event submission with matching payload; no-op lifecycle side-effects
                return PublishResult(
                    accepted=True,
                    event_id=event.event_id,
                    incident_id=incident.incident_id if incident else event.incident_id,
                    occurrence_id=incident.active_occurrence_id if incident else "",
                    transition="duplicate",
                    outbox_queued=False,
                )

            # 1. New incident creation
            if incident is None:
                occ_id = uuid.uuid4().hex
                status = "acknowledged" if event.lifecycle == "acknowledge" else "resolved" if event.lifecycle == "resolve" else "open"
                ack_at = current_iso if status == "acknowledged" else None
                res_at = current_iso if status == "resolved" else None
                last_notified = current_iso if status == "open" else None

                incident = Incident(
                    incident_id=event.incident_id,
                    source=event.source,
                    incident_key=event.incident_key,
                    active_occurrence_id=occ_id,
                    status=status,
                    severity=event.severity,
                    summary=event.summary,
                    first_seen=event.occurred_at,
                    last_seen=event.occurred_at,
                    acknowledged_at=ack_at,
                    resolved_at=res_at,
                    last_notified_at=last_notified,
                    occurrence_count=1,
                )
                occurrence = Occurrence(
                    occurrence_id=occ_id,
                    incident_id=event.incident_id,
                    status=status,
                    severity=event.severity,
                    opened_at=event.occurred_at,
                    closed_at=res_at,
                    resolution_evidence=event.summary if status == "resolved" else None,
                )
                transition = Transition(
                    transition_id=0,
                    incident_id=event.incident_id,
                    occurrence_id=occ_id,
                    event_id=event.event_id,
                    from_status=None,
                    to_status=status,
                    transition_name=f"{event.lifecycle}ed" if event.lifecycle in ("open", "resolve") else event.lifecycle,
                    timestamp=current_iso,
                    details={"summary": event.summary, "severity": event.severity},
                )

                self.storage.save_incident(incident, conn=conn)
                self.storage.save_occurrence(occurrence, conn=conn)
                self.storage.record_transition(transition, conn=conn)

                outbox_queued = False
                if status == "open":
                    for pid in target_providers:
                        self.storage.enqueue_outbox(event.event_id, incident.incident_id, pid, conn=conn)
                    outbox_queued = True

                return PublishResult(
                    accepted=True,
                    event_id=event.event_id,
                    incident_id=incident.incident_id,
                    occurrence_id=occ_id,
                    transition="opened" if status == "open" else status,
                    outbox_queued=outbox_queued,
                )

            # 2. Existing incident transitions
            occ_id = incident.active_occurrence_id or uuid.uuid4().hex
            from_status = incident.status
            outbox_queued = False
            transition_name = "updated"
            to_status = from_status

            if event.lifecycle == "open":
                if incident.status == "resolved":
                    # Recurrence after resolution: create a NEW occurrence
                    occ_id = uuid.uuid4().hex
                    to_status = "open"
                    transition_name = "opened"
                    occurrence = Occurrence(
                        occurrence_id=occ_id,
                        incident_id=incident.incident_id,
                        status="open",
                        severity=event.severity,
                        opened_at=event.occurred_at,
                    )
                    self.storage.save_occurrence(occurrence, conn=conn)

                    incident = Incident(
                        incident_id=incident.incident_id,
                        source=incident.source,
                        incident_key=incident.incident_key,
                        active_occurrence_id=occ_id,
                        status="open",
                        severity=event.severity,
                        summary=event.summary,
                        first_seen=incident.first_seen,
                        last_seen=event.occurred_at,
                        acknowledged_at=None,  # Reset ack for new occurrence!
                        resolved_at=None,
                        last_notified_at=current_iso,
                        occurrence_count=incident.occurrence_count + 1,
                    )
                    self.storage.save_incident(incident, conn=conn)

                    for pid in target_providers:
                        self.storage.enqueue_outbox(event.event_id, incident.incident_id, pid, conn=conn)
                    outbox_queued = True

                else:
                    # Still open or acknowledged: check cooldown & severity escalation
                    last_notified_dt = _parse_time(incident.last_notified_at)
                    cooldown = self.policy.critical_cooldown_seconds if event.severity == "critical" else self.policy.cooldown_seconds
                    cooldown_elapsed = last_notified_dt is None or (current_dt - last_notified_dt).total_seconds() >= cooldown
                    severity_escalated = (event.severity == "critical" and incident.severity != "critical")

                    should_notify = (incident.status == "open") and (cooldown_elapsed or severity_escalated)
                    new_notified = current_iso if should_notify else incident.last_notified_at

                    incident = Incident(
                        incident_id=incident.incident_id,
                        source=incident.source,
                        incident_key=incident.incident_key,
                        active_occurrence_id=occ_id,
                        status=incident.status,
                        severity=event.severity,
                        summary=event.summary,
                        first_seen=incident.first_seen,
                        last_seen=event.occurred_at,
                        acknowledged_at=incident.acknowledged_at,
                        resolved_at=None,
                        last_notified_at=new_notified,
                        occurrence_count=incident.occurrence_count,
                    )
                    self.storage.save_incident(incident, conn=conn)

                    if should_notify:
                        for pid in target_providers:
                            self.storage.enqueue_outbox(event.event_id, incident.incident_id, pid, conn=conn)
                        outbox_queued = True
                    transition_name = "reminded" if should_notify and not severity_escalated else "updated"

            elif event.lifecycle == "update":
                # Pure update observation
                last_notified_dt = _parse_time(incident.last_notified_at)
                cooldown = self.policy.critical_cooldown_seconds if event.severity == "critical" else self.policy.cooldown_seconds
                cooldown_elapsed = last_notified_dt is None or (current_dt - last_notified_dt).total_seconds() >= cooldown
                severity_escalated = (event.severity == "critical" and incident.severity != "critical")

                should_notify = (incident.status == "open") and (cooldown_elapsed or severity_escalated)
                new_notified = current_iso if should_notify else incident.last_notified_at

                incident = Incident(
                    incident_id=incident.incident_id,
                    source=incident.source,
                    incident_key=incident.incident_key,
                    active_occurrence_id=occ_id,
                    status=incident.status,
                    severity=event.severity,
                    summary=event.summary,
                    first_seen=incident.first_seen,
                    last_seen=event.occurred_at,
                    acknowledged_at=incident.acknowledged_at,
                    resolved_at=incident.resolved_at,
                    last_notified_at=new_notified,
                    occurrence_count=incident.occurrence_count,
                )
                self.storage.save_incident(incident, conn=conn)

                if should_notify:
                    for pid in target_providers:
                        self.storage.enqueue_outbox(event.event_id, incident.incident_id, pid, conn=conn)
                    outbox_queued = True
                transition_name = "updated"

            elif event.lifecycle == "acknowledge":
                if incident.status == "resolved":
                    raise InvalidTransitionError(
                        f"Cannot acknowledge resolved incident '{incident.incident_id}'."
                    )
                if incident.status == "acknowledged":
                    # Idempotent re-acknowledgement
                    return PublishResult(
                        accepted=True,
                        event_id=event.event_id,
                        incident_id=incident.incident_id,
                        occurrence_id=occ_id or "",
                        transition="idempotent_acknowledge",
                        outbox_queued=False,
                    )

                to_status = "acknowledged"
                transition_name = "acknowledged"
                incident = Incident(
                    incident_id=incident.incident_id,
                    source=incident.source,
                    incident_key=incident.incident_key,
                    active_occurrence_id=occ_id,
                    status=to_status,
                    severity=incident.severity,
                    summary=incident.summary,
                    first_seen=incident.first_seen,
                    last_seen=event.occurred_at,
                    acknowledged_at=incident.acknowledged_at or current_iso,
                    resolved_at=None,
                    last_notified_at=incident.last_notified_at,
                    occurrence_count=incident.occurrence_count,
                )
                self.storage.save_incident(incident, conn=conn)
                curr_occ = self.storage.get_occurrence(occ_id, conn=conn)
                if curr_occ and curr_occ.status == "open":
                    self.storage.save_occurrence(
                        Occurrence(
                            occurrence_id=curr_occ.occurrence_id,
                            incident_id=curr_occ.incident_id,
                            status="acknowledged",
                            severity=curr_occ.severity,
                            opened_at=curr_occ.opened_at,
                            closed_at=None,
                            resolution_evidence=curr_occ.resolution_evidence,
                        ),
                        conn=conn,
                    )
                self.storage.record_acknowledgement(
                    incident.incident_id, occ_id, actor=event.source, reason=event.summary, conn=conn
                )

            elif event.lifecycle == "resolve":
                if incident.status == "resolved":
                    # Idempotent resolution
                    return PublishResult(
                        accepted=True,
                        event_id=event.event_id,
                        incident_id=incident.incident_id,
                        occurrence_id=occ_id or "",
                        transition="idempotent_resolve",
                        outbox_queued=False,
                    )

                to_status = "resolved"
                transition_name = "resolved"
                incident = Incident(
                    incident_id=incident.incident_id,
                    source=incident.source,
                    incident_key=incident.incident_key,
                    active_occurrence_id=occ_id,
                    status=to_status,
                    severity=incident.severity,
                    summary=incident.summary,
                    first_seen=incident.first_seen,
                    last_seen=event.occurred_at,
                    acknowledged_at=incident.acknowledged_at,
                    resolved_at=current_iso,
                    last_notified_at=incident.last_notified_at,
                    occurrence_count=incident.occurrence_count,
                )
                self.storage.save_incident(incident, conn=conn)
                curr_occ = self.storage.get_occurrence(occ_id, conn=conn)
                if curr_occ:
                    self.storage.save_occurrence(
                        Occurrence(
                            occurrence_id=curr_occ.occurrence_id,
                            incident_id=curr_occ.incident_id,
                            status="resolved",
                            severity=curr_occ.severity,
                            opened_at=curr_occ.opened_at,
                            closed_at=current_iso,
                            resolution_evidence=event.summary,
                        ),
                        conn=conn,
                    )

            elif event.lifecycle == "reopen":
                if incident.status == "resolved":
                    to_status = "open"
                    transition_name = "reopened"
                    incident = Incident(
                        incident_id=incident.incident_id,
                        source=incident.source,
                        incident_key=incident.incident_key,
                        active_occurrence_id=occ_id,
                        status="open",
                        severity=incident.severity,
                        summary=incident.summary,
                        first_seen=incident.first_seen,
                        last_seen=event.occurred_at,
                        acknowledged_at=None,
                        resolved_at=None,
                        last_notified_at=current_iso,
                        occurrence_count=incident.occurrence_count,
                    )
                    self.storage.save_incident(incident, conn=conn)
                    for pid in target_providers:
                        self.storage.enqueue_outbox(event.event_id, incident.incident_id, pid, conn=conn)
                    outbox_queued = True

            transition = Transition(
                transition_id=0,
                incident_id=incident.incident_id,
                occurrence_id=occ_id,
                event_id=event.event_id,
                from_status=from_status,
                to_status=to_status,
                transition_name=transition_name,
                timestamp=current_iso,
                details={"summary": event.summary, "severity": event.severity},
            )
            self.storage.record_transition(transition, conn=conn)

            return PublishResult(
                accepted=True,
                event_id=event.event_id,
                incident_id=incident.incident_id,
                occurrence_id=occ_id,
                transition=transition_name,
                outbox_queued=outbox_queued,
            )

    def acknowledge_incident(
        self,
        incident_id: str,
        actor: str = "operator",
        reason: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Incident:
        """Transactionally acknowledge an active incident from CLI or HTTP.

        Guarantees:
        - Atomically validates incident existence and status.
        - Fails with IncidentNotFoundError if incident does not exist.
        - Fails with InvalidTransitionError if incident is resolved.
        - Idempotent: returns existing incident if already acknowledged without duplicate transitions.
        - Transitions active incident and occurrence from open to acknowledged.
        - Stores accurate acknowledgement timestamp.
        - Records audit evidence in acknowledgements and transitions tables.
        """
        current_dt = now or datetime.now(timezone.utc)
        current_iso = current_dt.isoformat().replace("+00:00", "Z")

        with self.storage.transaction() as conn:
            incident = self.storage.get_incident(incident_id, conn=conn)
            if incident is None:
                raise IncidentNotFoundError(f"Incident '{incident_id}' not found")

            if incident.status == "resolved":
                raise InvalidTransitionError(
                    f"Cannot acknowledge resolved incident '{incident_id}'. "
                    "Acknowledgement is only valid for open incidents."
                )

            if incident.status == "acknowledged":
                return incident

            updated = Incident(
                incident_id=incident.incident_id,
                source=incident.source,
                incident_key=incident.incident_key,
                active_occurrence_id=incident.active_occurrence_id,
                status="acknowledged",
                severity=incident.severity,
                summary=incident.summary,
                first_seen=incident.first_seen,
                last_seen=incident.last_seen,
                acknowledged_at=current_iso,
                resolved_at=None,
                last_notified_at=incident.last_notified_at,
                occurrence_count=incident.occurrence_count,
            )
            self.storage.save_incident(updated, conn=conn)

            occ_id = incident.active_occurrence_id or ""
            if occ_id:
                curr_occ = self.storage.get_occurrence(occ_id, conn=conn)
                if curr_occ and curr_occ.status == "open":
                    self.storage.save_occurrence(
                        Occurrence(
                            occurrence_id=curr_occ.occurrence_id,
                            incident_id=curr_occ.incident_id,
                            status="acknowledged",
                            severity=curr_occ.severity,
                            opened_at=curr_occ.opened_at,
                            closed_at=None,
                            resolution_evidence=curr_occ.resolution_evidence,
                        ),
                        conn=conn,
                    )

            # Persist synthetic event for transition foreign key
            synthetic_event_id = uuid.uuid4().hex
            clean_actor = re.sub(r"[^a-zA-Z0-9_-]", "_", actor)[:64] or "operator"
            synthetic_event = EventEnvelopeV1(
                event_id=synthetic_event_id,
                schema_version=1,
                source=clean_actor.lower(),
                kind="incident.acknowledgement",
                incident_key=incident.incident_key,
                severity=incident.severity,
                lifecycle="acknowledge",
                occurred_at=current_iso,
                summary=(reason or f"Incident acknowledged by {actor}")[:256],
            )
            self.storage.record_event(synthetic_event, conn=conn)

            # Record transition
            transition = Transition(
                transition_id=0,
                incident_id=incident.incident_id,
                occurrence_id=occ_id,
                event_id=synthetic_event_id,
                from_status=incident.status,
                to_status="acknowledged",
                transition_name="acknowledged",
                timestamp=current_iso,
                details={"actor": actor, "reason": reason or ""},
            )
            self.storage.record_transition(transition, conn=conn)

            # Record human acknowledgement record
            self.storage.record_acknowledgement(
                incident_id=incident.incident_id,
                occurrence_id=occ_id,
                actor=actor,
                reason=reason,
                conn=conn,
            )

            return updated
