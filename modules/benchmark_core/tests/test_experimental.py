from benchmark_core import MetricValue, TrialResult, TrialStatus
from benchmark_core.experimental import (
    check_condition_compatibility,
    compare_paired_trials,
    evaluate_decision_eligibility,
    holm_adjust,
)


def trial(tid, task, rep, status, variant="v", duration=None):
    metrics = {}
    if duration is not None:
        metrics["duration.wall_ms"] = MetricValue(
            duration, "ms", "synthetic-clock", "measured"
        )
    return TrialResult("synthetic-run", tid, task, variant, rep, status, metrics)


def compatible():
    return {
        "compatible": True,
        "task_digests_verified": True,
        "verifier_digests_verified": True,
        "non_target_conditions_equal": True,
        "model_identity_verified": True,
        "effective_settings_verified": True,
    }


def test_exact_paired_outcome_and_denominators():
    base = [
        trial("b1", "a", 0, TrialStatus.PASSED),
        trial("b2", "b", 0, TrialStatus.FAILED),
        trial("b3", "c", 0, TrialStatus.INFRASTRUCTURE_ERROR),
    ]
    cand = [
        trial("c1", "a", 0, TrialStatus.PASSED),
        trial("c2", "b", 0, TrialStatus.PASSED),
        trial("c3", "c", 0, TrialStatus.INFRASTRUCTURE_ERROR),
    ]
    result = compare_paired_trials(base, cand, compatibility=compatible()).result
    assert result["effects"]["baseline_acceptance"] == 0.5
    assert result["effects"]["candidate_acceptance"] == 1.0
    assert result["pairing"]["wins"] == 1
    assert result["pairing"]["losses"] == 0
    assert result["pairing"]["ties"] == 1
    assert result["uncertainty"]["exact_mcnemar_p"] == 1.0
    assert result["availability"]["baseline_scored_denominator"] == 2
    assert result["availability"]["baseline_status_counts"]["infrastructure_error"] == 1


def test_repeated_task_bootstraps_clusters_and_timeouts_are_censored():
    b = [
        trial("b1", "a", 0, "failed", duration=20),
        trial("b2", "a", 1, "timed_out", duration=100),
        trial("b3", "b", 0, "failed", duration=30),
    ]
    c = [
        trial("c1", "a", 0, "passed", duration=10),
        trial("c2", "a", 1, "passed", duration=11),
        trial("c3", "b", 0, "failed", duration=31),
    ]
    result = compare_paired_trials(
        b, c, compatibility=compatible(), seed=17, bootstrap_samples=200
    ).result
    assert result["pairing"]["paired_tasks"] == 2
    assert result["uncertainty"]["method"] == "task_cluster_percentile_bootstrap"
    assert result["uncertainty"]["exact_mcnemar_p"] is None
    assert result["duration"]["baseline"]["censored_timeout_n"] == 1
    assert result["duration"]["baseline"]["completed_n"] == 2


def test_no_pairs_incompatible_reason_and_zero_baseline_relative_undefined():
    b = [trial("b", "a", 0, "failed")]
    c = [trial("c", "z", 0, "passed")]
    result = compare_paired_trials(
        b, c, compatibility={"compatible": False}, min_tasks_for_confirmatory=1
    ).result
    assert result["effects"]["relative_improvement"] is None
    assert (
        "comparison.conditions_incompatible" in result["compatibility"]["reason_codes"]
    )
    assert result["pairing"]["completed_pairs"] == 0
    assert result["estimability"]["estimable"] is False


def test_holm_requires_preregistered_family_and_is_monotonic():
    assert (
        holm_adjust({"x": 0.01}, confirmatory=False, family_id="F")["applied"] is False
    )
    result = holm_adjust(
        {"x": 0.01, "y": 0.04, "z": 0.03}, confirmatory=True, family_id="F"
    )
    assert result["adjusted"] == {"x": 0.03, "z": 0.06, "y": 0.06}


def test_eligibility_never_mints_automatic_decision():
    result = compare_paired_trials(
        [trial("b", "a", 0, "passed")],
        [trial("c", "a", 0, "passed")],
        compatibility=compatible(),
    ).result
    gate = evaluate_decision_eligibility(
        result,
        evidence_sufficient=True,
        quality_noninferiority_met=True,
        reviewer="reviewer",
    )
    assert gate["decision"] is None
    assert "eligibility.small_sample_exploratory" in gate["reason_codes"]


def conditions():
    return {
        "tasks": {"t": {"task_sha256": "a" * 64, "verifier_sha256": "b" * 64}},
        "environment": {
            "model_identity": {"content_sha256": "c" * 64, "quantization": "Q4"},
            "runtime": {
                "model_settings": {"temperature": 0.2, "context": 4096},
                "prompt_sha256": "d" * 64,
            },
        },
    }


def test_condition_gate_allows_only_declared_between_or_within_target():
    base, model = conditions(), conditions()
    evidence = {
        "environment.model_identity": {
            "stage": "observed",
            "evidence_ref": "synthetic://model",
        },
        "environment.runtime.model_settings.temperature": {
            "stage": "effective",
            "evidence_ref": "synthetic://temperature",
        },
        "environment.runtime.model_settings.context": {
            "stage": "effective",
            "evidence_ref": "synthetic://context",
        },
    }
    model["environment"]["model_identity"]["content_sha256"] = "e" * 64
    result = check_condition_compatibility(
        base,
        model,
        study_class="between_models",
        allowed_differences=["environment.model_identity"],
        effective_settings_evidence=evidence,
    )
    assert result["compatible"] is True
    model["environment"]["runtime"]["prompt_sha256"] = "f" * 64
    assert (
        check_condition_compatibility(
            base,
            model,
            study_class="between_models",
            allowed_differences=["environment.model_identity"],
            effective_settings_evidence=evidence,
        )["reason_code"]
        == "comparison.non_target_conditions_differ"
    )
    candidate = conditions()
    candidate["environment"]["runtime"]["model_settings"]["temperature"] = 0.8
    assert (
        check_condition_compatibility(
            conditions(),
            candidate,
            study_class="within_model_settings",
            allowed_differences=["environment.runtime.model_settings.temperature"],
            effective_settings_evidence=evidence,
        )["compatible"]
        is True
    )


def test_zero_baseline_keeps_absolute_comparison_estimable_and_estimates_are_labeled():
    baseline = [trial("b1", "a", 0, "failed"), trial("b2", "b", 0, "failed")]
    candidate = [trial("c1", "a", 0, "passed"), trial("c2", "b", 0, "failed")]
    for item in baseline + candidate:
        item.metrics["throughput"] = MetricValue(
            10, "tokens/s", "synthetic", "estimated"
        )
    result = compare_paired_trials(
        baseline, candidate, compatibility=compatible()
    ).result
    assert result["effects"]["relative_improvement"] is None
    assert result["effects"]["acceptance_difference"] == 0.5
    assert result["estimability"]["estimable"] is True
    assert (
        result["effects"]["secondary_metric_deltas"]["throughput"]["interpretation"]
        == "estimated"
    )


def test_all_ties_have_no_degenerate_p_value_or_bootstrap_interval():
    baseline = [trial(f"b{i}", f"t{i}", 0, "passed") for i in range(3)]
    candidate = [trial(f"c{i}", f"t{i}", 0, "passed") for i in range(3)]
    result = compare_paired_trials(
        baseline, candidate, compatibility=compatible()
    ).result
    assert result["uncertainty"]["exact_mcnemar_p"] is None
    assert result["uncertainty"]["p_value_reason"] == "paired.no_discordant_pairs"
    assert result["uncertainty"]["interval"] is None
    assert result["uncertainty"]["method"] == "degenerate_task_effects_no_interval"


def test_duplicate_trial_id_does_not_inflate_scored_denominator():
    baseline = [trial("dup", "a", 0, "passed"), trial("dup", "b", 0, "passed")]
    candidate = [trial("c", "a", 0, "passed")]
    result = compare_paired_trials(
        baseline, candidate, compatibility=compatible()
    ).result
    assert result["availability"]["baseline_scored_denominator"] == 0
    assert result["availability"]["baseline_status_counts"]["passed"] == 2
    assert "comparison.duplicate_trial_ids" in result["compatibility"]["reason_codes"]
