"""Additive preregistered paired analysis with task-level inference.

TrialResult objects remain the input authority. A caller must separately supply
compatibility evidence; this module never infers causal comparability from scores.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import copy
import math
import random
from typing import Iterable, Mapping

from .models import TrialResult


@dataclass(frozen=True)
class ExperimentalComparison:
    result: dict


def check_condition_compatibility(
    baseline: object,
    candidate: object,
    *,
    study_class: str,
    allowed_differences: list[str],
    effective_settings_evidence: Mapping[str, object] | None = None,
) -> dict:
    """Verify exact condition equality outside the explicitly targeted fields.

    Accepted paths are deliberately narrow: between-model studies may vary only
    ``environment.model_identity``; within-model studies may vary only named
    scalar leaves under ``environment.runtime.model_settings``.
    """
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return {"compatible": False, "reason_code": "comparison.contract_missing"}
    if study_class not in {"between_models", "within_model_settings"}:
        return {"compatible": False, "reason_code": "comparison.study_class_invalid"}
    if not isinstance(allowed_differences, list) or not allowed_differences:
        return {
            "compatible": False,
            "reason_code": "comparison.allowed_differences_missing",
        }
    left, right = copy.deepcopy(baseline), copy.deepcopy(candidate)
    try:
        task_conditions = left["tasks"]
        if (
            not isinstance(task_conditions, dict)
            or task_conditions != right["tasks"]
            or not task_conditions
        ):
            return {
                "compatible": False,
                "reason_code": "comparison.task_or_verifier_identity_mismatch",
            }
        for task in task_conditions.values():
            if not isinstance(task, dict) or any(
                not _sha256(task.get(key)) for key in ("task_sha256", "verifier_sha256")
            ):
                return {
                    "compatible": False,
                    "reason_code": "comparison.task_or_verifier_digest_unverified",
                }
        if (
            not isinstance(effective_settings_evidence, Mapping)
            or not effective_settings_evidence
        ):
            return {
                "compatible": False,
                "reason_code": "comparison.effective_settings_evidence_missing",
            }
        if any(
            not _effective_evidence(path, evidence)
            for path, evidence in effective_settings_evidence.items()
        ):
            return {
                "compatible": False,
                "reason_code": "comparison.effective_settings_unverified",
            }
        required_evidence = {"environment.model_identity"}
        for key in (
            left.get("environment", {}).get("runtime", {}).get("model_settings", {})
        ):
            required_evidence.add(f"environment.runtime.model_settings.{key}")
        if not required_evidence.issubset(effective_settings_evidence):
            return {
                "compatible": False,
                "reason_code": "comparison.effective_settings_evidence_incomplete",
            }
        if study_class == "between_models":
            if allowed_differences != ["environment.model_identity"]:
                return {
                    "compatible": False,
                    "reason_code": "comparison.model_target_overbroad",
                }
            base_model = _path_get(left, "environment.model_identity")
            candidate_model = _path_get(right, "environment.model_identity")
            if not _identity_established(base_model) or not _identity_established(
                candidate_model
            ):
                return {
                    "compatible": False,
                    "reason_code": "comparison.model_identity_unverified",
                }
            if base_model == candidate_model:
                return {
                    "compatible": False,
                    "reason_code": "comparison.model_intervention_not_observed",
                }
            _path_remove(left, "environment.model_identity")
            _path_remove(right, "environment.model_identity")
        else:
            model_a = _path_get(left, "environment.model_identity")
            model_b = _path_get(right, "environment.model_identity")
            if not _identity_established(model_a) or model_a != model_b:
                return {
                    "compatible": False,
                    "reason_code": "comparison.within_model_identity_changed_or_unknown",
                }
            for path in allowed_differences:
                parts = path.split(".") if isinstance(path, str) else []
                if (
                    len(parts) != 4
                    or parts[:3] != ["environment", "runtime", "model_settings"]
                    or not parts[3]
                ):
                    return {
                        "compatible": False,
                        "reason_code": "comparison.settings_target_invalid",
                    }
                a, b = _path_get(left, path), _path_get(right, path)
                if a == b:
                    return {
                        "compatible": False,
                        "reason_code": "comparison.settings_intervention_not_observed",
                    }
                _path_remove(left, path)
                _path_remove(right, path)
        if left != right:
            return {
                "compatible": False,
                "reason_code": "comparison.non_target_conditions_differ",
            }
        return {
            "compatible": True,
            "reason_code": None,
            "study_class": study_class,
            "allowed_differences": list(allowed_differences),
            "task_digests_verified": True,
            "verifier_digests_verified": True,
            "non_target_conditions_equal": True,
            "model_identity_verified": True,
            "effective_settings_verified": True,
        }
    except (KeyError, TypeError):
        return {
            "compatible": False,
            "reason_code": "comparison.target_identity_missing",
        }


def compare_paired_trials(
    baseline: Iterable[TrialResult],
    candidate: Iterable[TrialResult],
    *,
    compatibility: Mapping[str, object],
    seed: int = 0,
    bootstrap_samples: int = 4000,
    min_tasks_for_confirmatory: int = 10,
) -> ExperimentalComparison:
    """Compare paired task/repetition outcomes; repeats are clustered by task.

    If there is exactly one completed pair per task, the two-sided exact
    McNemar/binomial test uses discordant pairs. With repeated pairs, the
    estimated effect is the equal-task mean acceptance difference and its
    percentile interval resamples whole tasks. This bootstrap is descriptive
    and requires independent sampled tasks; it is not a randomized-trial cure.
    """
    b_trials, c_trials = list(baseline), list(candidate)
    recorded_b, recorded_c = b_trials, c_trials
    reasons = []
    diagnostics = []
    if compatibility.get("compatible") is not True:
        reasons.append(
            str(compatibility.get("reason_code", "comparison.conditions_incompatible"))
        )
    for key in (
        "task_digests_verified",
        "verifier_digests_verified",
        "non_target_conditions_equal",
    ):
        if compatibility.get(key) is not True:
            reasons.append(f"comparison.{key}_unverified")
    if compatibility.get("model_identity_verified") is not True:
        reasons.append("comparison.model_identity_unverified")
    if compatibility.get("effective_settings_verified") is not True:
        reasons.append("comparison.effective_settings_unverified")

    b_idx, c_idx, excluded = _index_trials(b_trials), _index_trials(c_trials), []
    excluded.extend(b_idx.pop("excluded"))
    excluded.extend(c_idx.pop("excluded"))
    ambiguous_ids = {
        entry["trial_id"]
        for entry in excluded
        if entry["reason_code"] == "trial.duplicate_task_repetition"
    }
    if ambiguous_ids:
        b_trials = [trial for trial in b_trials if trial.trial_id not in ambiguous_ids]
        c_trials = [trial for trial in c_trials if trial.trial_id not in ambiguous_ids]
    all_ids = [t.trial_id for t in b_trials + c_trials]
    duplicates = {x for x, n in Counter(all_ids).items() if n > 1}
    if duplicates:
        reasons.append("comparison.duplicate_trial_ids")
        for key in list(b_idx.keys()):
            if b_idx[key].trial_id in duplicates:
                excluded.append(
                    {
                        "trial_id": b_idx.pop(key).trial_id,
                        "reason_code": "trial.duplicate_id",
                    }
                )
        for key in list(c_idx.keys()):
            if c_idx[key].trial_id in duplicates:
                excluded.append(
                    {
                        "trial_id": c_idx.pop(key).trial_id,
                        "reason_code": "trial.duplicate_id",
                    }
                )
        b_trials = [trial for trial in b_trials if trial.trial_id not in duplicates]
        c_trials = [trial for trial in c_trials if trial.trial_id not in duplicates]

    def status_counts(trials):
        return dict(Counter(str(t.status) for t in trials))

    b_scored = [
        t for t in b_trials if str(t.status) in {"passed", "failed", "timed_out"}
    ]
    c_scored = [
        t for t in c_trials if str(t.status) in {"passed", "failed", "timed_out"}
    ]
    b_rate = (
        sum(str(t.status) == "passed" for t in b_scored) / len(b_scored)
        if b_scored
        else None
    )
    c_rate = (
        sum(str(t.status) == "passed" for t in c_scored) / len(c_scored)
        if c_scored
        else None
    )
    blocks = sorted(set(b_idx) | set(c_idx))
    paired = [
        (key, b_idx[key], c_idx[key])
        for key in blocks
        if key in b_idx
        and key in c_idx
        and str(b_idx[key].status) in {"passed", "failed", "timed_out"}
        and str(c_idx[key].status) in {"passed", "failed", "timed_out"}
    ]
    paired_keys = {key for key, _baseline, _candidate in paired}
    non_scored_matched_blocks = sorted(
        key
        for key in set(b_idx) & set(c_idx)
        if key not in paired_keys
    )
    for key in non_scored_matched_blocks:
        for side, trial in (("baseline", b_idx[key]), ("candidate", c_idx[key])):
            if str(trial.status) not in {"passed", "failed", "timed_out"}:
                excluded.append(
                    {
                        "trial_id": trial.trial_id,
                        "reason_code": "trial.status_not_scored_in_pair",
                        "condition": side,
                        "status": str(trial.status),
                    }
                )
    unmatched = len(set(b_idx) ^ set(c_idx))
    task_deltas: dict[str, list[float]] = defaultdict(list)
    wins = losses = ties = 0
    for (task, _rep), b, c in paired:
        bp, cp = str(b.status) == "passed", str(c.status) == "passed"
        wins += cp and not bp
        losses += bp and not cp
        ties += bp == cp
        task_deltas[task].append(float(cp) - float(bp))
    distinct_tasks = len(set(t.task_id for t in b_trials + c_trials))
    paired_tasks = sorted(task_deltas)
    task_effects = [sum(task_deltas[t]) / len(task_deltas[t]) for t in paired_tasks]
    effect = sum(task_effects) / len(task_effects) if task_effects else None
    ci = None
    method = "unavailable"
    if len(task_effects) >= 2 and len(set(task_effects)) >= 2 and bootstrap_samples > 0:
        rng = random.Random(seed)
        draws = sorted(
            sum(rng.choice(task_effects) for _ in task_effects) / len(task_effects)
            for _ in range(bootstrap_samples)
        )
        ci = {
            "lower": draws[int(0.025 * (len(draws) - 1))],
            "upper": draws[int(0.975 * (len(draws) - 1))],
            "coverage": 0.95,
            "assumption": "percentile task-cluster bootstrap; tasks are independent sampled units",
        }
        method = "task_cluster_percentile_bootstrap"
    elif task_effects and len(set(task_effects)) < 2:
        method = "degenerate_task_effects_no_interval"
    elif task_effects:
        method = "single_task_no_interval"
    exact_p = None
    exact_applicable = (
        paired
        and all(len(v) == 1 for v in task_deltas.values())
        and len(paired_tasks) == len(paired)
    )
    if exact_applicable:
        n = wins + losses
        if n:
            tail = sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / (2**n)
            exact_p = min(1.0, 2 * tail)
    rate_delta = c_rate - b_rate if b_rate is not None and c_rate is not None else None
    rel = (
        (rate_delta / b_rate)
        if rate_delta is not None and b_rate not in (None, 0)
        else None
    )
    if b_rate == 0 and c_rate is not None:
        diagnostics.append("effect.relative_improvement_undefined_zero_baseline")
    estimable = not reasons and bool(paired) and effect is not None
    sufficiency = (
        "confirmatory_candidate"
        if len(paired_tasks) >= min_tasks_for_confirmatory
        else "exploratory_small_sample"
    )
    return ExperimentalComparison(
        {
            "schema": "benchmark-paired-analysis-v1",
            "compatibility": {
                "compatible": not reasons,
                "reason_codes": sorted(set(reasons)),
            },
            "availability": {
                "baseline_status_counts": status_counts(recorded_b),
                "candidate_status_counts": status_counts(recorded_c),
                "baseline_scored_denominator": len(b_scored),
                "candidate_scored_denominator": len(c_scored),
                "excluded_observations": excluded,
            },
            "pairing": {
                "distinct_tasks": distinct_tasks,
                "matched_blocks": len(blocks),
                "completed_pairs": len(paired),
                "matched_blocks_without_scored_pair": len(non_scored_matched_blocks),
                "paired_tasks": len(paired_tasks),
                "task_level_effects": [
                    {
                        "task_id": task,
                        "completed_pairs": len(task_deltas[task]),
                        "candidate_minus_baseline_acceptance": task_effects[index],
                    }
                    for index, task in enumerate(paired_tasks)
                ],
                "unmatched_observations": unmatched,
                "wins": wins,
                "losses": losses,
                "ties": ties,
            },
            "effects": {
                "baseline_acceptance": b_rate,
                "candidate_acceptance": c_rate,
                "acceptance_difference": rate_delta,
                "acceptance_difference_pp": rate_delta * 100
                if rate_delta is not None
                else None,
                "relative_improvement": rel,
                "relative_improvement_reason_code": "effect.relative_improvement_undefined_zero_baseline"
                if b_rate == 0
                else None,
                "task_mean_paired_difference": effect,
                "diagnostic_reason_codes": diagnostics,
                "secondary_metric_deltas": _secondary_metric_deltas(b_trials, c_trials),
            },
            "uncertainty": {
                "method": method,
                "interval": ci,
                "exact_mcnemar_p": exact_p,
                "p_value_reason": None
                if exact_p is not None
                else (
                    "paired.no_discordant_pairs"
                    if exact_applicable
                    else "paired.exact_test_not_identifiable"
                ),
            },
            "estimability": {
                "estimable": estimable,
                "reason_codes": sorted(set(reasons)),
            },
            "evidence_sufficiency": {
                "classification": sufficiency,
                "min_tasks": min_tasks_for_confirmatory,
            },
            "duration": _duration_summary(b_trials, c_trials),
        }
    )


def holm_adjust(
    p_values: Mapping[str, float], *, confirmatory: bool, family_id: str | None
) -> dict:
    """Holm step-down adjusted p-values only for an explicitly declared family."""
    if not confirmatory or not family_id:
        return {
            "applied": False,
            "reason_code": "multiplicity.family_not_confirmatory_or_declared",
            "adjusted": {},
        }
    if any(not math.isfinite(p) or p < 0 or p > 1 for p in p_values.values()):
        raise ValueError("p-values must be finite values in [0, 1]")
    ordered = sorted(p_values.items(), key=lambda x: (x[1], x[0]))
    n = len(ordered)
    running = 0.0
    adjusted = {}
    for i, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (n - i) * p))
        adjusted[name] = running
    return {"applied": True, "family_id": family_id, "adjusted": adjusted}


def evaluate_decision_eligibility(
    analysis: Mapping[str, object],
    *,
    evidence_sufficient: bool,
    quality_noninferiority_met: bool,
    reviewer: str | None = None,
) -> dict:
    """Layered gate; returns reasons and never creates a promotion decision."""
    reasons = []
    if not analysis.get("availability"):
        reasons.append("eligibility.descriptive_data_unavailable")
    if not analysis.get("compatibility", {}).get("compatible"):
        reasons.extend(
            analysis.get("compatibility", {}).get(
                "reason_codes", ["eligibility.conditions_incompatible"]
            )
        )
    if not analysis.get("estimability", {}).get("estimable"):
        reasons.append("eligibility.effect_not_estimable")
    if not evidence_sufficient:
        reasons.append("eligibility.experimental_evidence_insufficient")
    sufficiency = analysis.get("evidence_sufficiency", {})
    if (
        isinstance(sufficiency, Mapping)
        and sufficiency.get("classification") != "confirmatory_candidate"
    ):
        reasons.append("eligibility.small_sample_exploratory")
    if not quality_noninferiority_met:
        reasons.append("eligibility.quality_gate_not_met")
    if not reviewer:
        reasons.append("eligibility.reviewer_missing")
    return {
        "eligible_for_review": not reasons,
        "reason_codes": sorted(set(reasons)),
        "decision": None,
        "available_statuses": [
            "adopt",
            "provisional",
            "experimental",
            "unsupported",
            "rejected",
            "superseded",
        ],
    }


def validate_decision_record(value: object) -> list[str]:
    required = {
        "schema",
        "status",
        "evidence_refs",
        "thresholds",
        "compatibility",
        "reviewer",
        "provenance",
        "rationale",
    }
    if not isinstance(value, dict) or set(value) != required:
        return ["decision.fields_invalid"]
    if value["schema"] != "lio-decision-v1":
        return ["decision.schema_unsupported"]
    if value["status"] not in {
        "adopt",
        "provisional",
        "experimental",
        "unsupported",
        "rejected",
        "superseded",
    }:
        return ["decision.status_invalid"]
    errs = []
    for f in ("evidence_refs", "thresholds", "compatibility", "provenance"):
        if not value[f]:
            errs.append(f"decision.{f}_missing")
    if not isinstance(value["reviewer"], str) or not value["reviewer"].strip():
        errs.append("decision.reviewer_missing")
    if not isinstance(value["rationale"], str) or not value["rationale"].strip():
        errs.append("decision.rationale_missing")
    return errs


def _index_trials(trials: list[TrialResult]) -> dict:
    out, excluded, ambiguous = {}, [], set()
    for trial in trials:
        key = (trial.task_id, trial.repetition)
        if key in ambiguous:
            excluded.append(
                {
                    "trial_id": trial.trial_id,
                    "reason_code": "trial.duplicate_task_repetition",
                }
            )
            continue
        if key in out:
            excluded.append(
                {
                    "trial_id": trial.trial_id,
                    "reason_code": "trial.duplicate_task_repetition",
                }
            )
            previous = out.pop(key, None)
            if previous is not None:
                excluded.append(
                    {
                        "trial_id": previous.trial_id,
                        "reason_code": "trial.duplicate_task_repetition",
                    }
                )
            ambiguous.add(key)
            continue
        out[key] = trial
    out["excluded"] = excluded
    return out


def _duration_summary(trials_a, trials_b):
    result = {}
    for label, trials in (("baseline", trials_a), ("candidate", trials_b)):
        all_complete, successes, censored, provenance, incompatible_units = (
            [],
            [],
            0,
            [],
            [],
        )
        for trial in trials:
            metric = trial.metrics.get("duration.wall_ms") or trial.metrics.get(
                "duration_ms"
            )
            if not metric or metric.value is None:
                continue
            provenance.append(
                {
                    "trial_id": trial.trial_id,
                    "unit": metric.unit,
                    "source": metric.source,
                    "quality": str(metric.quality),
                    "reason": metric.reason,
                }
            )
            if metric.unit != "ms":
                incompatible_units.append(trial.trial_id)
                continue
            if str(trial.status) == "timed_out":
                censored += 1
                continue
            if str(trial.status) not in {"passed", "failed"}:
                continue
            all_complete.append(metric.value)
            if str(trial.status) == "passed":
                successes.append(metric.value)
        provenance_kinds = {
            (item["unit"], item["source"], item["quality"])
            for item in provenance
            if item["unit"] == "ms"
        }
        provenance_compatible = len(provenance_kinds) <= 1 and not incompatible_units
        aggregate_quality = (
            next(iter(provenance_kinds))[2] if len(provenance_kinds) == 1 else None
        )
        result[label] = {
            "all_scored_completed_mean": sum(all_complete) / len(all_complete)
            if all_complete and provenance_compatible
            else None,
            "successful_only_mean": sum(successes) / len(successes)
            if successes and provenance_compatible
            else None,
            "completed_n": len(all_complete),
            "successful_n": len(successes),
            "censored_timeout_n": censored,
            "incompatible_unit_n": len(incompatible_units),
            "aggregate_reason_code": None
            if provenance_compatible
            else "duration.unit_or_provenance_incompatible",
            "aggregate_quality": aggregate_quality,
            "units": "ms",
            "metric_provenance": provenance,
        }
    return result


def _path_get(value: dict, path: str):
    current = value
    for part in path.split("."):
        current = current[part]
    return current


def _path_remove(value: dict, path: str):
    parts = path.split(".")
    current = value
    for part in parts[:-1]:
        current = current[part]
    current.pop(parts[-1])


def _identity_established(value: object) -> bool:
    return (
        isinstance(value, dict)
        and _sha256(value.get("content_sha256"))
        and isinstance(value.get("quantization"), str)
        and value["quantization"].strip().lower() not in {"", "unknown", "unverified"}
        and all(
            item is not None
            and str(item).strip().lower() not in {"", "unknown", "unverified"}
            for item in value.values()
        )
    )


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _effective_evidence(path: str, value: object) -> bool:
    expected_stage = "observed" if path == "environment.model_identity" else "effective"
    return (
        isinstance(value, Mapping)
        and value.get("stage") == expected_stage
        and isinstance(value.get("evidence_ref"), str)
        and bool(value["evidence_ref"].strip())
    )


def _secondary_metric_deltas(baseline, candidate):
    scored_statuses = {"passed", "failed", "timed_out"}
    baseline = [t for t in baseline if str(t.status) in scored_statuses]
    candidate = [t for t in candidate if str(t.status) in scored_statuses]
    names = (
        sorted(
            set.intersection(
                *(set(t.metrics) for t in baseline),
                *(set(t.metrics) for t in candidate),
            )
        )
        if baseline and candidate
        else []
    )
    deltas = {}
    for name in names:
        if name in {"duration.wall_ms", "duration_ms"}:
            # Dedicated censored-time summary handles duration metrics.
            continue
        a = [t.metrics[name] for t in baseline if t.metrics[name].value is not None]
        b = [t.metrics[name] for t in candidate if t.metrics[name].value is not None]
        provenance = {(m.unit, m.source, str(m.quality)) for m in a + b}
        if not a or not b:
            deltas[name] = {"delta": None, "reason_code": "metric.observations_missing"}
        elif len(provenance) != 1:
            deltas[name] = {
                "delta": None,
                "reason_code": "metric.provenance_or_unit_incompatible",
                "provenance": sorted(provenance),
            }
        else:
            unit, source, quality = next(iter(provenance))
            mean_a = sum(m.value for m in a) / len(a)
            mean_b = sum(m.value for m in b) / len(b)
            deltas[name] = {
                "baseline_mean": mean_a,
                "candidate_mean": mean_b,
                "delta": mean_b - mean_a,
                "unit": unit,
                "source": source,
                "quality": quality,
                "interpretation": "estimated"
                if quality == "estimated"
                else "descriptive",
            }
    return deltas
