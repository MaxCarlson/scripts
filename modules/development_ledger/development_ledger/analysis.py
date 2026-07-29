"""Traceability evaluation, progress classification, and routing recommendations."""

from __future__ import annotations

import fnmatch
import re
from collections import Counter, defaultdict, deque
from typing import Any

from development_ledger.models import NormalizedTest, PlanItem, PlanState
from development_ledger.results import aggregate_tests, failure_fingerprint


def evaluate_items(
    plan: PlanState,
    tests: list[NormalizedTest],
    manual_statuses: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate automated and manual evidence for every plan item."""

    manual_statuses = manual_statuses or {check.id: check.status for check in plan.manual_checks}
    evaluations: list[dict[str, Any]] = []
    for item in plan.items:
        matched = [test for test in tests if _test_matches_item(test, item)]
        automated = _automated_status(item, matched)
        check_states = {check_id: manual_statuses.get(check_id, "missing") for check_id in item.manual_checks}
        manual = _manual_status(check_states)
        verification = _verification_status(item, automated, manual)
        evaluations.append(
            {
                "id": item.id,
                "title": item.title,
                "kind": item.kind,
                "implementation": item.implementation,
                "automated": automated,
                "manual": manual,
                "verification": verification,
                "matched_test_ids": [test.id for test in matched],
                "manual_check_states": check_states,
                "depends_on": item.depends_on,
                "blocked_by": item.blocked_by,
                "relevant_files": item.relevant_files,
                "priority": item.priority,
                "architecture_role": item.architecture_role,
            }
        )
    return evaluations


def build_validation_event(
    *,
    event_id: str,
    timestamp: str,
    plan: PlanState,
    tests: list[NormalizedTest],
    provenance: dict[str, Any],
    prior_events: list[dict[str, Any]],
    transcript_metrics: dict[str, int | float] | None = None,
    artifacts: list[str] | None = None,
    actor: str = "",
    mode: str = "",
) -> dict[str, Any]:
    """Build a complete validation-run event and compare it with prior evidence."""

    prior_validation = _latest_event(prior_events, "validation_run")
    manual_statuses = current_manual_statuses(plan, prior_events)
    item_evaluations = evaluate_items(plan, tests, manual_statuses)
    test_summary = aggregate_tests(tests)
    if transcript_metrics:
        test_summary["transcript_metrics"] = transcript_metrics
    failures = sorted(failure_fingerprint(test) for test in tests if test.status in {"failed", "error"})
    comparison = compare_to_previous(item_evaluations, failures, test_summary, prior_validation)
    progress = classify_progress(plan, item_evaluations, comparison, prior_events, failures)
    planning_gate = assess_planning_gate(plan, prior_events)
    architecture_review = assess_architecture_review(plan, prior_events, progress)
    routing = recommend_routing(plan, progress, failures, planning_gate, architecture_review)

    return {
        "schema_version": 1,
        "event_type": "validation_run",
        "event_id": event_id,
        "timestamp": timestamp,
        "plan_id": plan.plan_id,
        "plan_title": plan.title,
        "project_root": plan.project_root,
        "plan_revision": plan.plan_revision,
        "stage": plan.stage,
        "actor": actor or str(plan.session.get("actor", "unknown")),
        "mode": mode or str(plan.session.get("mode", "hybrid")),
        "request": dict(plan.session.get("request", {})),
        "intent": {
            "objective": str(plan.session.get("objective", "")),
            "hypothesis": str(plan.session.get("hypothesis", "")),
            "target_ids": list(plan.session.get("target_ids", [])),
            "selection_rationale": str(plan.session.get("selection_rationale", "")),
            "stop_conditions": list(plan.session.get("stop_conditions", [])),
            "batch": dict(plan.session.get("batch", {})),
            "environment_dependencies": list(plan.session.get("environment_dependencies", [])),
            "architecture_impact": str(plan.session.get("architecture_impact", "none")),
            "relevant_files": list(plan.session.get("relevant_files", [])),
        },
        "provenance": provenance,
        "tests": [test.to_dict() for test in tests],
        "test_summary": test_summary,
        "failure_fingerprints": failures,
        "items": item_evaluations,
        "manual_checks": [
            {**check.to_dict(), "status": manual_statuses.get(check.id, check.status)} for check in plan.manual_checks
        ],
        "planning_gate": planning_gate,
        "comparison": comparison,
        "progress": progress,
        "architecture_review": architecture_review,
        "routing": routing,
        "artifacts": artifacts or [],
    }


def build_manual_event(
    *,
    event_id: str,
    timestamp: str,
    plan: PlanState,
    check_id: str,
    status: str,
    note: str,
    provenance: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    """Build an immutable manual-check event."""

    check = plan.manual_check_map().get(check_id)
    if check is None:
        raise ValueError(f"Unknown manual check {check_id!r} for plan {plan.plan_id}.")
    return {
        "schema_version": 1,
        "event_type": "manual_check",
        "event_id": event_id,
        "timestamp": timestamp,
        "plan_id": plan.plan_id,
        "plan_title": plan.title,
        "project_root": plan.project_root,
        "plan_revision": plan.plan_revision,
        "stage": plan.stage,
        "actor": actor,
        "check_id": check_id,
        "status": status,
        "note": note,
        "item_ids": check.item_ids,
        "platform": check.platform,
        "provenance": provenance,
    }


def current_manual_statuses(plan: PlanState, events: list[dict[str, Any]]) -> dict[str, str]:
    """Project manual-check events over the statuses declared in the plan."""

    statuses = {check.id: check.status for check in plan.manual_checks}
    for event in events:
        if event.get("event_type") == "manual_check" and event.get("check_id") in statuses:
            statuses[str(event["check_id"])] = str(event.get("status", statuses[str(event["check_id"])]))
    return statuses


def assess_planning_gate(plan: PlanState, prior_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Check request intake, dependency readiness, and batch cohesion before another pass."""

    issues: list[str] = []
    warnings: list[str] = []
    request = plan.session.get("request", {})
    request_status = str(request.get("status", ""))
    if request_status == "conflict_pending":
        issues.append("User requirements conflict with the current plan and require an explicit decision.")

    previous = _latest_event(prior_events, "validation_run")
    if request_status == "incorporated" and previous:
        previous_revision = int(previous.get("plan_revision", 0) or 0)
        if plan.plan_revision <= previous_revision:
            issues.append("The request is marked incorporated but plan_revision did not increase.")

    selected_ids = list(plan.session.get("target_ids", []))
    selected = set(selected_ids)
    item_map = plan.item_map()
    for item_id in selected_ids:
        item = item_map[item_id]
        for dependency_id in item.depends_on:
            dependency = item_map[dependency_id]
            if dependency_id not in selected and dependency.implementation not in {"implemented", "deferred"}:
                issues.append(
                    f"Selected item {item_id} depends on unfinished {dependency_id}, which is not included in the batch."
                )

    batch = plan.session.get("batch", {})
    max_items = int(batch.get("max_items", plan.policy["session"]["max_items"]))
    if len(selected_ids) > max_items:
        warnings.append(
            f"The batch selects {len(selected_ids)} items, above the configured soft maximum of {max_items}."
        )
    if not selected_ids:
        warnings.append("No target plan items are selected for this session.")
    if len(selected_ids) > 1 and not _selected_items_are_cohesive(plan, selected_ids):
        warnings.append(
            "Selected items are not connected by dependencies or shared relevant files; consider a more cohesive batch."
        )

    candidates = recommend_batch_candidates(plan)
    return {
        "passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "selected_ids": selected_ids,
        "dependency_order": _dependency_order(plan, selected_ids),
        "recommended_candidates": candidates,
        "batch": dict(batch),
    }


def recommend_batch_candidates(plan: PlanState) -> list[dict[str, Any]]:
    """Rank ready plan items, favoring prerequisites, foundations, priority, and downstream leverage."""

    item_map = plan.item_map()
    dependents: dict[str, set[str]] = defaultdict(set)
    for item in plan.items:
        for dependency in item.depends_on:
            dependents[dependency].add(item.id)

    candidates: list[dict[str, Any]] = []
    for item in plan.items:
        if item.implementation in {"implemented", "deferred", "blocked"}:
            continue
        unresolved = [
            dependency
            for dependency in item.depends_on
            if item_map[dependency].implementation not in {"implemented", "deferred"}
        ]
        if unresolved:
            continue
        downstream = _transitive_dependent_count(item.id, dependents)
        role_bonus = 100 if item.architecture_role == "foundation" else 30 if item.architecture_role == "integration" else 0
        score = role_bonus + item.priority * 10 + downstream
        candidates.append(
            {
                "id": item.id,
                "title": item.title,
                "score": score,
                "priority": item.priority,
                "architecture_role": item.architecture_role,
                "downstream_dependents": downstream,
                "relevant_files": item.relevant_files,
            }
        )
    return sorted(candidates, key=lambda value: (-int(value["score"]), str(value["id"])))


def assess_architecture_review(
    plan: PlanState,
    prior_events: list[dict[str, Any]],
    progress: dict[str, Any],
) -> dict[str, Any]:
    """Determine whether a lightweight or deeper architecture review is due."""

    requested = bool(plan.session.get("architecture_review", {}).get("requested", False))
    performed = bool(plan.session.get("architecture_review", {}).get("performed", False))
    current_review = dict(plan.session.get("architecture_review", {}))
    latest_review = next(
        (
            event
            for event in reversed(prior_events)
            if event.get("event_type") == "validation_run"
            and event.get("architecture_review", {}).get("performed")
        ),
        None,
    )
    validations = [event for event in prior_events if event.get("event_type") == "validation_run"]
    if latest_review:
        review_index = validations.index(latest_review)
        runs_since = len(validations) - review_index - 1
        reviewed_revision = int(latest_review.get("plan_revision", 0) or 0)
    else:
        runs_since = len(validations)
        reviewed_revision = 0
    revisions_since = max(0, plan.plan_revision - reviewed_revision)

    triggers: list[str] = []
    policy = plan.policy["architecture_review"]
    impact = str(plan.session.get("architecture_impact", "none"))
    if requested:
        triggers.append("The user or working agent explicitly requested an architecture review.")
    if impact in {"cross_cutting", "foundational"}:
        triggers.append(f"The current change declares {impact} architecture impact.")
    if progress.get("classification") in {"looping", "regressing"}:
        triggers.append(f"The latest progress classification is {progress.get('classification')}.")
    if runs_since >= int(policy["max_validation_runs"]):
        triggers.append(f"{runs_since} validation runs have occurred since the last architecture review.")
    if revisions_since >= int(policy["max_plan_revisions"]):
        triggers.append(f"The plan advanced {revisions_since} revisions since the last architecture review.")

    if performed:
        return {
            "due": False,
            "performed": True,
            "depth": "completed",
            "triggers": triggers,
            "runs_since_last_review": 0,
            "plan_revisions_since_last_review": 0,
            "summary": current_review.get("summary", ""),
            "findings": current_review.get("findings", []),
            "actions": current_review.get("actions", []),
        }

    depth = "deep" if impact == "foundational" or len(triggers) >= 2 else "cursory"
    return {
        "due": bool(triggers),
        "performed": False,
        "depth": depth,
        "triggers": triggers,
        "runs_since_last_review": runs_since,
        "plan_revisions_since_last_review": revisions_since,
        "summary": "",
        "findings": [],
        "actions": [],
    }


def compare_to_previous(
    items: list[dict[str, Any]],
    failures: list[str],
    test_summary: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute semantic deltas from the previous validation run."""

    if previous is None:
        return {
            "baseline": True,
            "new_failures": failures,
            "persistent_failures": [],
            "resolved_failures": [],
            "item_transitions": [],
            "test_count_delta": {},
            "verified_delta": sum(item["verification"] == "verified" for item in items),
        }

    old_failures = set(previous.get("failure_fingerprints", []))
    new_failures = set(failures)
    old_items = {item["id"]: item for item in previous.get("items", [])}
    transitions: list[dict[str, str]] = []
    for item in items:
        old = old_items.get(item["id"])
        if old and old.get("verification") != item.get("verification"):
            transitions.append(
                {
                    "id": item["id"],
                    "from": str(old.get("verification", "unknown")),
                    "to": str(item.get("verification", "unknown")),
                }
            )
    count_delta = {
        key: int(test_summary.get(key, 0)) - int(previous.get("test_summary", {}).get(key, 0))
        for key in ("total", "passed", "failed", "errors", "skipped")
    }
    verified_now = sum(item["verification"] == "verified" for item in items)
    verified_before = sum(item.get("verification") == "verified" for item in previous.get("items", []))
    return {
        "baseline": False,
        "new_failures": sorted(new_failures - old_failures),
        "persistent_failures": sorted(new_failures & old_failures),
        "resolved_failures": sorted(old_failures - new_failures),
        "item_transitions": transitions,
        "test_count_delta": count_delta,
        "verified_delta": verified_now - verified_before,
    }


def classify_progress(
    plan: PlanState,
    items: list[dict[str, Any]],
    comparison: dict[str, Any],
    prior_events: list[dict[str, Any]],
    failures: list[str],
) -> dict[str, Any]:
    """Classify progress using semantic deltas and recent history."""

    if comparison.get("baseline"):
        classification = "ready" if not failures and _all_required_items_verified(items) else "baseline"
        return {"classification": classification, "material_progress": True, "reasons": ["Established baseline."]}

    reasons: list[str] = []
    material = False
    regression = False
    if comparison.get("verified_delta", 0) > 0:
        material = True
        reasons.append(f"{comparison['verified_delta']} additional plan item(s) became verified.")
    if comparison.get("resolved_failures"):
        material = True
        reasons.append(f"Resolved {len(comparison['resolved_failures'])} failure fingerprint(s).")
    if comparison.get("new_failures"):
        regression = True
        reasons.append(f"Introduced {len(comparison['new_failures'])} new failure fingerprint(s).")
    if comparison.get("verified_delta", 0) < 0:
        regression = True
        reasons.append(f"Lost verification for {-comparison['verified_delta']} plan item(s).")

    latest = _latest_event(prior_events, "validation_run")
    prior_classification = str(latest.get("progress", {}).get("classification", "")) if latest else ""
    same_failures = bool(failures) and set(failures) == set(latest.get("failure_fingerprints", [])) if latest else False
    same_hypothesis = False
    if latest:
        current_hypothesis = _normalize_text(str(plan.session.get("hypothesis", "")))
        prior_hypothesis = _normalize_text(str(latest.get("intent", {}).get("hypothesis", "")))
        same_hypothesis = bool(current_hypothesis) and current_hypothesis == prior_hypothesis

    if regression:
        classification = "regressing"
    elif not failures:
        classification = "ready" if _all_required_items_verified(items) else "progressing"
        if classification == "ready":
            material = True
            reasons.append("All non-deferred plan items are verified.")
    elif material:
        classification = "partial_progress"
    elif same_failures and (same_hypothesis or prior_classification in {"stalled", "looping"}):
        classification = "looping"
        reasons.append("The same failure set persisted without a new successful hypothesis.")
    else:
        classification = "stalled"
        reasons.append("No acceptance, verification, or failure-resolution progress was detected.")

    if not reasons:
        reasons.append("Validation completed without a material semantic delta.")
    return {"classification": classification, "material_progress": material, "reasons": reasons}


def recommend_routing(
    plan: PlanState,
    progress: dict[str, Any],
    failures: list[str],
    planning_gate: dict[str, Any],
    architecture_review: dict[str, Any],
) -> dict[str, Any]:
    """Recommend the next actor and a local Codex model when escalation is warranted."""

    classification = progress["classification"]
    environment_dependencies = list(plan.session.get("environment_dependencies", []))
    request_status = str(plan.session.get("request", {}).get("status", ""))
    if request_status == "conflict_pending":
        decision = "stop_for_user_decision"
        reason = "Conflicting requirements must be resolved in the plan before implementation continues."
    elif not planning_gate.get("passed", True):
        decision = "replan_remote"
        reason = "The plan-intake or dependency gate failed: " + "; ".join(planning_gate.get("issues", []))
    elif failures and environment_dependencies:
        decision = "handoff_local"
        reason = "Failures depend on local environment capabilities: " + ", ".join(environment_dependencies)
    elif classification == "looping":
        decision = "handoff_local"
        reason = "The remote iteration is looping on the same evidence."
    elif classification == "regressing":
        decision = "replan_remote"
        reason = "Regressions should be isolated or reverted before further feature expansion."
    elif architecture_review.get("due"):
        decision = "review_architecture"
        reason = "Architecture review is due before selecting another implementation batch."
    elif classification == "stalled":
        decision = "one_targeted_remote_pass"
        reason = "One bounded remote pass is permitted only with a distinct evidence-backed hypothesis."
    elif classification in {"progressing", "partial_progress", "baseline"}:
        decision = "continue_remote"
        reason = "Evidence shows useful progress or establishes the first baseline."
    else:
        decision = "ready_for_acceptance"
        reason = "Automated evidence is ready for remaining acceptance or manual checks."

    model, reasoning = recommend_local_model(plan) if decision == "handoff_local" else ("", "")
    return {"decision": decision, "reason": reason, "model": model, "reasoning": reasoning}


def recommend_local_model(plan: PlanState) -> tuple[str, str]:
    """Choose a local model from declared diagnostic complexity and dependency tags."""

    tags = {str(tag).lower() for tag in plan.session.get("environment_dependencies", [])}
    complexity = str(plan.session.get("diagnostic_complexity", "normal")).lower()
    if tags & {"security", "corruption", "data_loss"} or complexity == "critical":
        return "gpt-5.6-sol", "high"
    if tags & {"concurrency", "native", "filesystem", "encoding", "process", "linker"} or complexity == "deep":
        return "gpt-5.6-sol", "medium"
    if complexity == "complex" or len(tags) >= 2:
        return "gpt-5.6-terra", "high"
    if complexity == "mechanical":
        return "gpt-5.6-luna", "medium"
    return "gpt-5.6-terra", "medium"


def _test_matches_item(test: NormalizedTest, item: PlanItem) -> bool:
    if item.id in test.item_ids:
        return True
    for pattern in item.tests:
        candidate = pattern[5:] if pattern.startswith("glob:") else pattern
        if fnmatch.fnmatchcase(test.id, candidate):
            return True
        if candidate.startswith("suite:") and fnmatch.fnmatchcase(test.suite, candidate[6:]):
            return True
    return False


def _automated_status(item: PlanItem, tests: list[NormalizedTest]) -> str:
    if not item.tests and not tests:
        return "unmapped"
    if item.tests and not tests:
        return "not_run"
    states = Counter(test.status for test in tests)
    if states["failed"] or states["error"]:
        return "failed"
    if states["passed"] and not states["skipped"]:
        return "passed"
    if states["passed"] and states["skipped"]:
        return "partial"
    if states["skipped"]:
        return "skipped"
    return "not_run"


def _manual_status(states: dict[str, str]) -> str:
    if not states:
        return "not_required"
    values = set(states.values())
    if "failed" in values:
        return "failed"
    if "blocked" in values or "missing" in values:
        return "blocked"
    if "pending" in values:
        return "pending"
    if values <= {"passed", "waived"}:
        return "passed"
    return "pending"


def _verification_status(item: PlanItem, automated: str, manual: str) -> str:
    if item.implementation == "deferred":
        return "deferred"
    if item.implementation == "blocked" or item.blocked_by:
        return "blocked"
    if item.implementation != "implemented":
        return item.implementation
    if automated == "failed" or manual == "failed":
        return "failing"
    if automated in {"unmapped", "not_run", "skipped", "partial"}:
        return "unverified"
    if manual in {"pending", "blocked"}:
        return "manual_pending"
    return "verified"


def _selected_items_are_cohesive(plan: PlanState, selected_ids: list[str]) -> bool:
    item_map = plan.item_map()
    selected = set(selected_ids)
    graph: dict[str, set[str]] = {item_id: set() for item_id in selected_ids}
    for left_id in selected_ids:
        left = item_map[left_id]
        for right_id in selected_ids:
            if left_id == right_id:
                continue
            right = item_map[right_id]
            related = (
                right_id in left.depends_on
                or left_id in right.depends_on
                or bool(set(left.relevant_files) & set(right.relevant_files))
            )
            if related:
                graph[left_id].add(right_id)
    visited: set[str] = set()
    queue = deque([selected_ids[0]])
    while queue:
        item_id = queue.popleft()
        if item_id in visited:
            continue
        visited.add(item_id)
        queue.extend(graph[item_id] - visited)
    return visited == selected


def _dependency_order(plan: PlanState, selected_ids: list[str]) -> list[str]:
    selected = set(selected_ids)
    item_map = plan.item_map()
    indegree = {item_id: 0 for item_id in selected_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for item_id in selected_ids:
        for dependency in item_map[item_id].depends_on:
            if dependency in selected:
                indegree[item_id] += 1
                outgoing[dependency].append(item_id)
    queue = deque(sorted((item_id for item_id, degree in indegree.items() if degree == 0)))
    ordered: list[str] = []
    while queue:
        current = queue.popleft()
        ordered.append(current)
        for dependent in sorted(outgoing[current]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    return ordered if len(ordered) == len(selected_ids) else selected_ids


def _transitive_dependent_count(item_id: str, dependents: dict[str, set[str]]) -> int:
    visited: set[str] = set()
    queue = deque(dependents.get(item_id, set()))
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        queue.extend(dependents.get(current, set()) - visited)
    return len(visited)


def _latest_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event_type") == event_type:
            return event
    return None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _all_required_items_verified(items: list[dict[str, Any]]) -> bool:
    required = [item for item in items if item.get("verification") != "deferred"]
    return bool(required) and all(item.get("verification") == "verified" for item in required)
