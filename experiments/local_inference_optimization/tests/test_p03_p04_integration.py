"""Offline integration of P04 execution correlation with LIO and P03."""

import copy
import json

import pytest

from benchmark_core import (
    TrialResult,
    check_condition_compatibility,
    compare_paired_trials,
    evaluate_decision_eligibility,
)
from interactive_reports import ReportData, TrialDetail, generate_html_report
from llm_monitor.inference_correlation import ExecutionCredentialRegistry
from llm_monitor.inference_models import InferenceRequest
from llm_monitor.storage import TelemetryStore

from experiments.local_inference_optimization.preregistration import (
    check_result_set_matches_frozen,
    freeze_preregistration,
    freeze_readiness,
    preregistration_fingerprint,
)
from experiments.local_inference_optimization.correlation_adapter import (
    reconcile_correlated_execution,
)


def _design(study_class="between_models"):
    digest = "a" * 64
    return {
        "schema": "lio-preregistration-v1",
        "experiment_id": "synthetic-p03-p04-integration",
        "study_class": study_class,
        "research_question": "Exercise synthetic trial correlation and comparison.",
        "hypothesis": "Synthetic fixture only; no model claim.",
        "primary_endpoint": "strict_task_acceptance",
        "secondary_endpoints": ["duration.wall_ms"],
        "baseline": {
            "run_id": "synthetic-baseline",
            "sealed": True,
            "fingerprint": digest,
        },
        "models": [
            {
                "condition_id": "baseline",
                "content_sha256": digest,
                "quantization": "Q4_TEST",
                "identity_quality": "verified",
            },
            {
                "condition_id": "candidate",
                "content_sha256": "b" * 64,
                "quantization": "Q5_TEST",
                "identity_quality": "verified",
            },
        ],
        "task_set": {
            "task_ids": ["task-a", "task-b", "task-c", "task-d"],
            "task_sha256": {
                key: digest for key in ("task-a", "task-b", "task-c", "task-d")
            },
            "verifier_sha256": {
                key: "c" * 64 for key in ("task-a", "task-b", "task-c", "task-d")
            },
        },
        "repetitions": 1,
        "randomization_seed": 17,
        "pairing": {
            "unit": "task_repetition",
            "block": "task_id",
            "order": "randomized",
        },
        "execution": {"order": "counterbalanced", "warm_cold": "declared_per_block"},
        "environment": {
            "host_fingerprint": "synthetic-host-v1",
            "instrumentation": "synthetic-fixture-v1",
        },
        "intervention": {
            "target": "model_settings"
            if study_class == "within_model_settings"
            else "model_identity",
            "allowed_differences": ["environment.runtime.model_settings.temperature"]
            if study_class == "within_model_settings"
            else ["environment.model_identity"],
        },
        "fixed_conditions": {
            "prompt_policy": "synthetic-prompt-policy-v1",
            "tool_policy": "synthetic-tools-v1",
        },
        "required_evidence_stages": ["observed", "effective"],
        "limits": {"task_timeout_seconds": 60, "resource_limits": {"cpu_seconds": 120}},
        "missing_data": {
            "infrastructure": "exclude_from_scored_denominator",
            "unscored": "retain_diagnostic",
        },
        "exclusions": {"predeclared": []},
        "stopping": {"rule": "fixed_repetitions"},
        "multiplicity": {
            "family_id": "synthetic-family",
            "method": "holm",
            "confirmatory": True,
        },
        "adoption_criteria": {
            "quality_noninferiority": 0.0,
            "minimum_independent_tasks": 10,
            "review_required": True,
        },
        "analysis_plan": {
            "method": "task_cluster_bootstrap",
            "interval": "percentile_95",
            "cluster_unit": "task_id",
            "seed": 17,
        },
        "decision_statuses": sorted(
            [
                "adopt",
                "provisional",
                "experimental",
                "unsupported",
                "rejected",
                "superseded",
            ]
        ),
    }


def _result_descriptor(design, frozen):
    return {
        "design_sha256": frozen["design_sha256"],
        "task_ids": design["task_set"]["task_ids"],
        "task_sha256": design["task_set"]["task_sha256"],
        "verifier_sha256": design["task_set"]["verifier_sha256"],
        "randomization_seed": design["randomization_seed"],
        "repetitions": design["repetitions"],
        "baseline": design["baseline"],
        "environment": design["environment"],
        "fixed_conditions": design["fixed_conditions"],
        "intervention": design["intervention"],
        "model_identities": [
            {
                key: model[key]
                for key in ("condition_id", "content_sha256", "quantization")
            }
            for model in design["models"]
        ],
    }


def _trial(trial_id="harbor-trial-a", repetition=0):
    return {
        "schema": "lio-trial-v1",
        "experiment_sha256": "d" * 64,
        "variant_sha256": "e" * 64,
        "run_id": "synthetic-run",
        "trial_id": trial_id,
        "task_id": "task-a",
        "repetition": repetition,
        "evidence_ref": "evidence-a",
        "source_revision": "f" * 40,
        "workspace_sha256": "9" * 64,
    }


def _persist_execution(
    store,
    registry,
    execution_id,
    trial_id,
    request_ids,
    *,
    task_id="task-a",
    variant_id="baseline",
):
    context, token = registry.register(
        "synthetic-run", task_id, execution_id, repetition_id="0", variant_id=variant_id
    )
    for request_id in request_ids:
        attached = registry.verify_and_record(token, request_id)
        assert attached == context
        request = InferenceRequest(
            request_id=request_id,
            server_instance_id="synthetic-monitor",
            source="gateway_openai_chat_completions",
            state="completed",
            started_at="2026-11-06T12:00:00Z",
            ended_at="2026-11-06T12:00:01Z",
            benchmark_correlation=attached.to_dict(),
        )
        store.record_inference(request, "metadata")
    registry.complete(execution_id, trial_id)
    final = registry.requests(execution_id)
    assert store.update_execution_correlation(execution_id, final["context"]) == len(
        request_ids
    )
    rows = [
        store.get_inference_request(request_id, include_content=False)
        for request_id in request_ids
    ]
    return final, rows


def test_synthetic_p04_to_lio_to_p03_report_path(tmp_path):
    design = _design()
    assert freeze_readiness(design)["state"] == "freeze_ready"
    frozen = freeze_preregistration(design)
    assert (
        check_result_set_matches_frozen(frozen, _result_descriptor(design, frozen))
        == []
    )
    assert preregistration_fingerprint(design) == frozen["design_sha256"]

    registry = ExecutionCredentialRegistry()
    with TelemetryStore(tmp_path / "synthetic-history.sqlite3") as store:
        correlation, rows = _persist_execution(
            store,
            registry,
            "attempt-a",
            "harbor-trial-a",
            ["gateway-req-1", "gateway-req-2"],
        )
        unrelated, unrelated_rows = _persist_execution(
            store,
            registry,
            "attempt-b",
            "harbor-trial-b",
            ["unrelated-req"],
        )
        rows[0]["content"] = [{"text": "synthetic-private-prompt"}]
        rows[0]["headers"] = {"Authorization": "Bearer synthetic-secret"}
        rows[0]["correlation_credential"] = "synthetic-credential"
        rows.extend(unrelated_rows)

    bundle = reconcile_correlated_execution(
        correlation,
        rows,
        _trial(),
        expected_execution_id="attempt-a",
        expected_variant_id="baseline",
        experiment_id=design["experiment_id"],
        requested_settings={"temperature": 0.2},
        planned_settings={"temperature": 0.2},
        request_settings={
            "gateway-req-1": {
                "provider": "synthetic-provider",
                "model": "synthetic-model-A",
                "parameters": {"temperature": 0.2},
            },
            "gateway-req-2": {
                "provider": "synthetic-provider",
                "model": "synthetic-model-A",
                "parameters": {"temperature": 0.2},
            },
        },
        timestamp="2026-11-06T12:00:00Z",
    )
    assert bundle["trial"]["trial_id"] == "harbor-trial-a"
    assert bundle["correlation"]["execution_id"] == "attempt-a"
    assert bundle["request_ids"] == ["gateway-req-1", "gateway-req-2"]
    assert bundle["request_capture_status"] == "complete"
    assert "unrelated-req" not in bundle["request_ids"]
    assert bundle["effective_settings"] == {}
    assert bundle["evidence_gaps"] == ["backend_runtime_settings_unavailable"]
    assert len(bundle["evidence_records"]) == 2
    for evidence in bundle["evidence_records"]:
        assert evidence["schema"] == "lio-evidence-v1"
        assert all(obs["stage"] != "effective" for obs in evidence["observations"])
        assert {obs["stage"] for obs in evidence["observations"]} >= {
            "requested",
            "planned",
            "observed",
        }
    serialized_bundle = json.dumps(bundle)
    assert "synthetic-private-prompt" not in serialized_bundle
    assert "synthetic-secret" not in serialized_bundle
    assert "synthetic-credential" not in serialized_bundle

    runtime_bundle = reconcile_correlated_execution(
        correlation,
        rows,
        _trial(),
        expected_execution_id="attempt-a",
        expected_variant_id="baseline",
        experiment_id=design["experiment_id"],
        requested_settings={"temperature": 0.2},
        planned_settings={"temperature": 0.2},
        request_settings={
            "gateway-req-1": {
                "provider": "synthetic-provider",
                "model": "synthetic-model-A",
                "parameters": {"temperature": 0.2},
            },
            "gateway-req-2": {
                "provider": "synthetic-provider",
                "model": "synthetic-model-A",
                "parameters": {"temperature": 0.2},
            },
        },
        timestamp="2026-11-06T12:00:00Z",
        backend_runtime_evidence={
            "backend": {"identity": "synthetic-backend", "version": "fixture-v1"},
            "artifact": {"id": "synthetic-runtime-capture", "sha256": "7" * 64},
            "observations": [
                {
                    "field": "temperature",
                    "value": 0.2,
                    "timestamp": "2026-11-06T12:00:00Z",
                }
            ],
        },
    )
    assert runtime_bundle["effective_settings"] == {"temperature": 0.2}
    assert runtime_bundle["evidence_gaps"] == []
    runtime_records = [
        record
        for record in runtime_bundle["evidence_records"]
        if any(
            observation["stage"] == "effective"
            for observation in record["observations"]
        )
    ]
    assert len(runtime_records) == 1
    assert runtime_records[0]["backend"]["identity"] == "synthetic-backend"

    base = [
        TrialResult("r-base", "b-a", "task-a", "baseline", 0, "passed"),
        TrialResult("r-base", "b-b", "task-b", "baseline", 0, "failed"),
        TrialResult("r-base", "b-c", "task-c", "baseline", 0, "passed"),
        TrialResult("r-base", "b-d", "task-d", "baseline", 0, "infrastructure_error"),
    ]
    candidate = [
        TrialResult("r-candidate", "c-a", "task-a", "candidate", 0, "passed"),
        TrialResult("r-candidate", "c-b", "task-b", "candidate", 0, "passed"),
        TrialResult("r-candidate", "c-c", "task-c", "candidate", 0, "timed_out"),
        TrialResult("r-candidate", "c-d", "task-d", "candidate", 0, "passed"),
    ]
    task_conditions = {
        task_id: {
            "task_sha256": design["task_set"]["task_sha256"][task_id],
            "verifier_sha256": design["task_set"]["verifier_sha256"][task_id],
        }
        for task_id in design["task_set"]["task_ids"]
    }
    compatibility = check_condition_compatibility(
        {
            "tasks": task_conditions,
            "environment": {
                "model_identity": {
                    "content_sha256": "a" * 64,
                    "quantization": "Q4_TEST",
                    "identity_quality": "verified",
                },
                "runtime": {"model_settings": {}},
            },
            "fixed_conditions": design["fixed_conditions"],
        },
        {
            "tasks": task_conditions,
            "environment": {
                "model_identity": {
                    "content_sha256": "b" * 64,
                    "quantization": "Q5_TEST",
                    "identity_quality": "verified",
                },
                "runtime": {"model_settings": {}},
            },
            "fixed_conditions": design["fixed_conditions"],
        },
        study_class="between_models",
        allowed_differences=["environment.model_identity"],
        effective_settings_evidence={
            "environment.model_identity": {
                "stage": "observed",
                "evidence_ref": "synthetic-model-identity",
            }
        },
    )
    assert compatibility["compatible"] is True
    analysis = compare_paired_trials(
        base, candidate, compatibility=compatibility
    ).result
    assert analysis["availability"]["baseline_scored_denominator"] == 3
    assert analysis["availability"]["candidate_scored_denominator"] == 4
    assert analysis["pairing"]["completed_pairs"] == 3
    assert analysis["pairing"]["matched_blocks_without_scored_pair"] == 1
    assert (
        analysis["pairing"]["wins"],
        analysis["pairing"]["losses"],
        analysis["pairing"]["ties"],
    ) == (1, 1, 1)
    assert any(
        item["trial_id"] == "b-d"
        and item["reason_code"] == "trial.status_not_scored_in_pair"
        for item in analysis["availability"]["excluded_observations"]
    )
    assert (
        analysis["evidence_sufficiency"]["classification"] == "exploratory_small_sample"
    )
    eligibility = evaluate_decision_eligibility(
        analysis, evidence_sufficient=False, quality_noninferiority_met=False
    )
    assert eligibility["decision"] is None
    assert "eligibility.small_sample_exploratory" in eligibility["reason_codes"]

    report = ReportData(
        experiment_id=design["experiment_id"],
        title="<script>alert('synthetic')</script>",
        trials={
            "gateway-req-1": TrialDetail(
                trial_id="harbor-trial-a",
                variant_id="baseline",
                task_id="task-a",
                status="passed",
                duration_ms=1.0,
                metadata={
                    "execution_id": bundle["correlation"]["execution_id"],
                    "request_ids": bundle["request_ids"],
                },
            )
        },
        metadata={
            "experimental_analysis": {
                "analysis": analysis,
                "correlation": bundle["correlation"],
                "evidence_refs": [
                    item["artifacts"][0]["id"] for item in bundle["evidence_records"]
                ],
                "freeze_state": freeze_readiness(design)["state"],
                "comparison_compatibility": compatibility,
                "correlation_completeness": "verified_all_requests_persisted",
                "promotion_eligibility": eligibility,
            }
        },
    )
    html = generate_html_report(report)
    assert "gateway-req-1" in html and "exploratory_small_sample" in html
    assert (
        "&lt;script&gt;" in html and "<script>alert('synthetic')</script>" not in html
    )
    assert "Authorization" not in html and "synthetic-credential" not in html


def test_integration_rejects_missing_or_mismatched_execution_and_trial(tmp_path):
    registry = ExecutionCredentialRegistry()
    with TelemetryStore(tmp_path / "negative-history.sqlite3") as store:
        correlation, rows = _persist_execution(
            store, registry, "attempt-a", "harbor-trial-a", ["request-a"]
        )

    args = dict(
        expected_variant_id="baseline",
        experiment_id="synthetic-experiment",
        requested_settings={},
        planned_settings={},
        request_settings={},
        timestamp="2026-11-06T12:00:00Z",
    )
    with pytest.raises(ValueError, match="execution"):
        reconcile_correlated_execution(
            correlation, rows, _trial(), expected_execution_id="attempt-other", **args
        )
    wrong_trial = _trial("different-harbor-trial")
    with pytest.raises(ValueError, match="native trial"):
        reconcile_correlated_execution(
            correlation, rows, wrong_trial, expected_execution_id="attempt-a", **args
        )
    with pytest.raises(ValueError, match="correlation"):
        reconcile_correlated_execution(
            {"verification_status": "unavailable"},
            rows,
            _trial(),
            expected_execution_id="attempt-a",
            **args,
        )
    with pytest.raises(ValueError, match="persisted"):
        reconcile_correlated_execution(
            correlation, [], _trial(), expected_execution_id="attempt-a", **args
        )

    corrupted_rows = copy.deepcopy(rows)
    corrupted_rows[0]["benchmark_correlation"]["execution_id"] = "attempt-other"
    with pytest.raises(ValueError, match="persisted request correlation context"):
        reconcile_correlated_execution(
            correlation,
            corrupted_rows,
            _trial(),
            expected_execution_id="attempt-a",
            **args,
        )

    clock = [0.0]
    expiring_registry = ExecutionCredentialRegistry(
        ttl_seconds=1, clock=lambda: clock[0]
    )
    expiring_registry.register(
        "synthetic-run", "task-a", "expired-attempt", variant_id="baseline"
    )
    clock[0] = 2.0
    expired = expiring_registry.requests("expired-attempt")
    with pytest.raises(ValueError, match="verified P04 provenance"):
        reconcile_correlated_execution(
            expired, [], _trial(), expected_execution_id="expired-attempt", **args
        )


def test_unknown_baseline_or_runtime_identity_stays_blocked_and_setting_comparison_fails_closed():
    design = _design("within_model_settings")
    design["models"][1]["content_sha256"] = design["models"][0]["content_sha256"]
    design["models"][1]["quantization"] = design["models"][0]["quantization"]
    design["intervention"] = {
        "target": "model_settings",
        "allowed_differences": ["environment.runtime.model_settings.temperature"],
    }
    assert freeze_readiness(design)["state"] == "freeze_ready"
    unknown = copy.deepcopy(design)
    unknown["baseline"] = {"run_id": None, "sealed": None, "fingerprint": None}
    unknown["environment"]["instrumentation"] = "unknown"
    readiness = freeze_readiness(unknown)
    assert readiness["state"] == "template_ready_blocked"
    assert "baseline.unsealed_or_unidentified" in readiness["reason_codes"]
    assert "conditions.runtime_or_fixed_identity_missing" in readiness["reason_codes"]

    left = {
        "tasks": {"task-a": {"task_sha256": "a" * 64, "verifier_sha256": "c" * 64}},
        "environment": {
            "model_identity": {
                "content_sha256": "a" * 64,
                "quantization": "Q4_TEST",
                "identity_quality": "verified",
            },
            "runtime": {"model_settings": {"temperature": 0.2}},
        },
        "fixed": "same",
    }
    right = copy.deepcopy(left)
    right["environment"]["runtime"]["model_settings"]["temperature"] = 0.8
    incompatible = check_condition_compatibility(
        left,
        right,
        study_class="within_model_settings",
        allowed_differences=["environment.runtime.model_settings.temperature"],
        effective_settings_evidence={
            "environment.model_identity": {
                "source": "backend_runtime",
                "status": "verified",
            }
        },
    )
    assert incompatible["compatible"] is False
    assert incompatible["reason_code"] in {
        "comparison.effective_settings_evidence_incomplete",
        "comparison.effective_settings_unverified",
    }
    result = compare_paired_trials(
        [TrialResult("r", "b", "task-a", "baseline", 0, "passed")],
        [TrialResult("r", "c", "task-a", "candidate", 0, "passed")],
        compatibility=incompatible,
    ).result
    assert result["estimability"]["estimable"] is False


def test_within_model_setting_comparison_requires_independent_effective_attestation():
    baseline = {
        "tasks": {"task-a": {"task_sha256": "a" * 64, "verifier_sha256": "c" * 64}},
        "environment": {
            "model_identity": {
                "content_sha256": "a" * 64,
                "quantization": "Q4_TEST",
                "identity_quality": "verified",
            },
            "runtime": {"model_settings": {"temperature": 0.2}},
        },
        "fixed": "same",
    }
    candidate = copy.deepcopy(baseline)
    candidate["environment"]["runtime"]["model_settings"]["temperature"] = 0.8
    attested = {
        "environment.model_identity": {
            "stage": "observed",
            "evidence_ref": "fixture-model-id",
        },
        "environment.runtime.model_settings.temperature": {
            "stage": "effective",
            "evidence_ref": "independent-backend-runtime-fixture",
        },
    }
    compatible = check_condition_compatibility(
        baseline,
        candidate,
        study_class="within_model_settings",
        allowed_differences=["environment.runtime.model_settings.temperature"],
        effective_settings_evidence=attested,
    )
    assert compatible["compatible"] is True
    comparison = compare_paired_trials(
        [TrialResult("r", "b", "task-a", "baseline", 0, "failed")],
        [TrialResult("r", "c", "task-a", "candidate", 0, "passed")],
        compatibility=compatible,
    ).result
    assert comparison["estimability"]["estimable"] is True
    assert comparison["effects"]["acceptance_difference"] == 1.0
