"""Conservative causal-attribution scoring and EvidenceEdge builder."""

from __future__ import annotations

from dataclasses import dataclass, field

from procwatch.models import (
    AgentContext,
    ConfidenceLevel,
    EdgeRelation,
    EvidenceEdge,
    MissingMetadataReason,
    ProcessObservation,
    WindowObservation,
)


@dataclass(slots=True)
class AttributionAssessment:
    """Scored attribution outcome with explicit evidence edges and alternatives."""

    primary_proc: ProcessObservation | None
    confidence: ConfidenceLevel
    score: float
    edges: list[EvidenceEdge] = field(default_factory=list)
    alternative_candidates: list[dict[str, object]] = field(default_factory=list)
    missing_reasons: list[MissingMetadataReason] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def score_window_attribution(
    window: WindowObservation,
    candidates: list[ProcessObservation],
    *,
    agent_context: AgentContext | None = None,
    has_sysmon_lineage: bool = False,
    has_task_trigger: bool = False,
) -> AttributionAssessment:
    """Score candidate processes for a window and produce conservative EvidenceEdges."""
    if not candidates:
        return AttributionAssessment(
            primary_proc=None,
            confidence=ConfidenceLevel.UNKNOWN,
            score=0.0,
            missing_reasons=[MissingMetadataReason.NOT_EMITTED],
            reasons=["no_candidate_process_found"],
        )

    scored: list[tuple[float, ProcessObservation, list[str]]] = []
    for proc in candidates:
        pts = 0.0
        notes: list[str] = []
        if window.owner_pid and proc.identity.pid == window.owner_pid:
            pts += 0.35
            notes.append("direct_hwnd_pid_match")
        if proc.start_monotonic_ns is not None and window.first_seen_monotonic_ns > 0:
            delta_ms = abs(window.first_seen_monotonic_ns - proc.start_monotonic_ns) / 1_000_000.0
            if delta_ms <= 500.0:
                pts += 0.30
                notes.append(f"tight_temporal_delta_ms={delta_ms:.1f}")
            elif delta_ms <= 2500.0:
                pts += 0.18
                notes.append(f"window_temporal_delta_ms={delta_ms:.1f}")
        if not proc.identity.is_provisional:
            pts += 0.10
            notes.append("canonical_kernel_identity")
        if agent_context is not None and agent_context.trust_level == "instrumented":
            pts += 0.25
            notes.append("instrumented_procwatch_context")
        if has_sysmon_lineage:
            pts += 0.20
            notes.append("sysmon_lineage")
        if has_task_trigger:
            pts += 0.15
            notes.append("task_scheduler_trigger")
        scored.append((min(1.0, pts), proc, notes))

    scored.sort(key=lambda item: item[0], reverse=True)
    top_score, top_proc, top_notes = scored[0]

    # Ambiguity penalty if another distinct PID scored nearly as high.
    if len(scored) > 1 and (top_score - scored[1][0]) < 0.08:
        top_score = max(0.0, top_score - 0.15)
        top_notes.append("ambiguous_competing_candidate")

    if top_score >= 0.75:
        confidence = ConfidenceLevel.HIGH
    elif top_score >= 0.45:
        confidence = ConfidenceLevel.MEDIUM
    elif top_score >= 0.20:
        confidence = ConfidenceLevel.LOW
    else:
        confidence = ConfidenceLevel.UNKNOWN

    win_node = f"win:{window.window_instance_id}"
    edges: list[EvidenceEdge] = [
        EvidenceEdge(
            from_node_id=top_proc.identity.proc_key,
            to_node_id=win_node,
            relation=EdgeRelation.HOSTED_BY
            if window.window_class == "CASCADIA_HOSTING_WINDOW_CLASS"
            else EdgeRelation.CORRELATED_WITH,
            source="correlator_scorer",
            method="+".join(top_notes) if top_notes else "temporal_match",
            confidence=round(top_score, 3),
        )
    ]

    alternatives: list[dict[str, object]] = [
        {
            "proc_key": proc.identity.proc_key,
            "pid": proc.identity.pid,
            "image_name": proc.image_name,
            "score": round(sc, 3),
            "reasons": rs,
        }
        for sc, proc, rs in scored[1:5]
    ]

    return AttributionAssessment(
        primary_proc=top_proc,
        confidence=confidence,
        score=round(top_score, 3),
        edges=edges,
        alternative_candidates=alternatives,
        reasons=top_notes,
    )
