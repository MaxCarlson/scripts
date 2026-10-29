"""Shared evidence-based alert rules and deduplicated state transitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from .observability import SystemSnapshot


@dataclass(frozen=True)
class AlertRule:
    rule_id: str
    category: str
    severity: str
    classification: str
    finding_codes: tuple[str, ...] = ()
    cooldown_seconds: float = 300.0
    threshold: float | None = None
    minimum_observations: int = 1
    window_seconds: float = 300.0


@dataclass(frozen=True)
class Alert:
    alert_id: str
    provider_instance_id: str
    session_id: str
    rule_id: str
    category: str
    severity: str
    classification: str
    status: str
    summary: str
    evidence: list[dict[str, Any]]
    threshold: float | None
    first_seen: str
    last_seen: str
    last_notified_at: str | None
    acknowledged_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AlertTransition:
    transition: str
    alert: Alert
    notify: bool


@dataclass(frozen=True)
class AlertBatch:
    active: list[Alert]
    transitions: list[AlertTransition]
    states: list[dict[str, Any]]


DEFAULT_RULES = (
    AlertRule("inference.length_finish", "completion", "warning", "observed",
              ("context.length_finish", "inference.length_termination")),
    AlertRule("context.near_limit", "context", "warning", "observed", threshold=85,
              finding_codes=("context.near_limit", "context.near_capacity"),
              minimum_observations=2, window_seconds=300),
    AlertRule("compaction.frequent", "compaction", "warning", "strong_inference",
              ("compaction.frequent",)),
    AlertRule("context.read_thrashing", "reads", "info", "hypothesis",
              ("reads.repeated_after_compaction", "reads.possible_thrashing")),
    AlertRule("tool.edit_failure", "tools", "warning", "observed",
              ("tools.failed_edit",)),
    AlertRule("tool.repeated_failure", "tools", "warning", "strong_inference",
              ("tools.repeated_failure", "tools.repeated_failures")),
    AlertRule("blocker.permission", "permissions", "warning", "observed", cooldown_seconds=60),
    AlertRule("blocker.question", "questions", "info", "observed", cooldown_seconds=60),
    AlertRule("lifecycle.possible_stall", "lifecycle", "warning", "hypothesis", threshold=180,
              cooldown_seconds=300),
    AlertRule("monitor.provider_stale", "monitoring", "warning", "observed", cooldown_seconds=300),
)


class AlertEngine:
    """Evaluate normalized diagnostic evidence without side effects or notifications."""

    def __init__(self, rules: tuple[AlertRule, ...] = DEFAULT_RULES) -> None:
        self.rules = rules

    def evaluate(self, snapshot: SystemSnapshot, *, previous: list[dict[str, Any]] | None = None,
                 now: datetime | None = None) -> AlertBatch:
        current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        current_stamp = current_time.isoformat()
        previous_states = previous or []
        previous_by_id = {str(item.get("alert_id")): item for item in previous_states}
        candidates: dict[str, tuple[Any, AlertRule, list[dict[str, Any]], str]] = {}
        for summary in snapshot.sessions:
            findings = summary.diagnostic_findings
            for rule in self.rules:
                evidence, text = self._evidence(rule, summary, findings, current_time)
                if len(evidence) < rule.minimum_observations:
                    continue
                alert_id = _alert_id(summary.provider_instance_id, summary.session_id, rule.rule_id)
                candidates[alert_id] = (summary, rule, evidence, text)

        transitions: list[AlertTransition] = []
        output_states: list[dict[str, Any]] = []
        active: list[Alert] = []
        for alert_id, (summary, rule, evidence, text) in candidates.items():
            previous_state = previous_by_id.pop(alert_id, None)
            old_status = previous_state.get("status") if previous_state else None
            first_seen = previous_state.get("first_seen") if previous_state else current_stamp
            acknowledged_at = previous_state.get("acknowledged_at") if old_status == "acknowledged" else None
            last_notified = previous_state.get("last_notified_at") if previous_state else None
            notify = False
            transition_name = None
            if old_status == "acknowledged":
                status = "acknowledged"
            else:
                status = "active"
                if old_status in {None, "resolved"}:
                    transition_name = "opened" if old_status is None else "reopened"
                    notify = True
                elif _cooldown_elapsed(last_notified, current_time, rule.cooldown_seconds):
                    transition_name = "reminded"
                    notify = True
            if notify:
                last_notified = current_stamp
            alert = Alert(alert_id, summary.provider_instance_id, summary.session_id, rule.rule_id, rule.category,
                          rule.severity, rule.classification, status, text, evidence, rule.threshold,
                          first_seen, current_stamp, last_notified, acknowledged_at)
            active.append(alert)
            state = alert.to_dict()
            state["evidence_json"] = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
            state["last_updated"] = current_stamp
            output_states.append(state)
            if transition_name:
                transitions.append(AlertTransition(transition_name, alert, notify))

        summaries_by_key = {summary.key: summary for summary in snapshot.sessions}
        for previous_state in previous_by_id.values():
            if previous_state.get("status") not in {"active", "acknowledged"}:
                continue
            summary = summaries_by_key.get(
                f"{previous_state.get('provider_instance_id', '').rstrip('/')}\0{previous_state.get('session_id', '')}"
            )
            if summary is None or summary.freshness.status == "stale" or summary.coverage.get("status") != "complete":
                # Missing or partial observations cannot prove a condition cleared.
                output_states.append(previous_state)
                try:
                    active.append(_alert_from_state(previous_state))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    pass
                continue
            resolved = dict(previous_state)
            resolved.update({"status": "resolved", "resolved_at": current_stamp, "last_seen": current_stamp,
                             "last_updated": current_stamp})
            resolved["evidence_json"] = previous_state.get("evidence_json", "[]")
            try:
                alert = _alert_from_state(resolved)
            except (KeyError, TypeError):
                continue
            output_states.append(resolved)
            transitions.append(AlertTransition("resolved", alert, False))
        return AlertBatch(active, transitions, output_states)

    @staticmethod
    def _evidence(rule: AlertRule, summary: Any, findings: list[dict[str, Any]], now: datetime):
        if rule.rule_id == "blocker.permission" and (summary.blockers.get("permissions") or 0) > 0:
            return ([{"count": summary.blockers["permissions"], "observed_at": summary.freshness.observed_at}],
                    "Session is waiting for permission approval.")
        if rule.rule_id == "blocker.question" and (summary.blockers.get("questions") or 0) > 0:
            return ([{"count": summary.blockers["questions"], "observed_at": summary.freshness.observed_at}],
                    "Session is waiting for a user answer.")
        if rule.rule_id == "monitor.provider_stale" and summary.freshness.status == "stale":
            return ([{"status": "stale", "age_seconds": summary.freshness.age_seconds,
                      "error_sources": summary.last_error_sources}], "The most recent provider observation is stale or incomplete.")
        if rule.rule_id == "context.near_limit":
            samples = [item for item in summary.recent_context_utilization
                       if isinstance(item.get("utilization_percent"), (int, float))
                       and item["utilization_percent"] >= (rule.threshold or 85)]
            return samples[-max(rule.minimum_observations, 10):], "Repeated inference requests approached the configured context limit."
        if rule.rule_id == "lifecycle.possible_stall":
            activity = _parse_time(summary.last_activity_at)
            age = (now - activity).total_seconds() if activity else None
            if summary.state == "inference_running" and age is not None and age >= (rule.threshold or 180):
                return ([{"state": summary.state, "last_activity_at": summary.last_activity_at,
                          "no_new_activity_seconds": age}],
                        "No new normalized activity was observed while the provider still reports inference running.")
            return [], ""
        matched = [finding for finding in findings if finding.get("code") in rule.finding_codes]
        evidence = []
        for finding in matched:
            details = finding.get("evidence", [])
            if isinstance(details, dict):
                evidence.append({"finding_code": finding.get("code"), **details})
            elif isinstance(details, list):
                evidence.extend(item if isinstance(item, dict) else
                                {"finding_code": finding.get("code"), "detail": item} for item in details)
        if not evidence and matched:
            evidence = [{"code": finding.get("code"), "summary": finding.get("summary")} for finding in matched]
        text = matched[0].get("summary", "Diagnostic condition is present.") if matched else ""
        return evidence, text


def acknowledge_alert(state: dict[str, Any], *, at: datetime | None = None) -> dict[str, Any]:
    if state.get("status") not in {"active", "acknowledged"}:
        raise ValueError("only active alerts can be acknowledged")
    stamp = (at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    return {**state, "status": "acknowledged", "acknowledged_at": state.get("acknowledged_at") or stamp,
            "last_updated": stamp}


def _alert_id(provider: str, session: str, rule: str) -> str:
    return hashlib.sha256(f"{provider}\0{session}\0{rule}".encode("utf-8")).hexdigest()


def _cooldown_elapsed(last_notified: str | None, now: datetime, cooldown: float) -> bool:
    parsed = _parse_time(last_notified)
    return parsed is None or (now - parsed).total_seconds() >= cooldown


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _alert_from_state(state: dict[str, Any]) -> Alert:
    evidence = json.loads(state.get("evidence_json", "[]")) if isinstance(state.get("evidence_json"), str) else state.get("evidence", [])
    return Alert(state["alert_id"], state["provider_instance_id"], state["session_id"], state["rule_id"],
                 state["category"], state["severity"], state["classification"], state["status"],
                 state["summary"], evidence, state.get("threshold"), state["first_seen"], state["last_seen"],
                 state.get("last_notified_at"), state.get("acknowledged_at"))
