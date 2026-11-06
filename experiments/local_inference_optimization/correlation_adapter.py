"""Reconcile P04 Monitor records with existing LIO trial/evidence contracts.

This adapter intentionally consumes the public P04 registry/history shapes and
emits the existing lio-trial-v1 and lio-evidence-v1 schemas. It does not create
a second trace schema or infer effective backend settings from request data.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from .adapters import monitor_request_observations
from .contracts import canonical_bytes, validate_evidence, validate_trial


def reconcile_correlated_execution(
    correlation: object,
    request_rows: list[dict[str, Any]],
    trial: object,
    *,
    expected_execution_id: str,
    expected_variant_id: str,
    experiment_id: str,
    requested_settings: Mapping[str, Any],
    planned_settings: Mapping[str, Any],
    request_settings: Mapping[str, dict[str, Any]],
    timestamp: str,
    backend_runtime_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a P04 execution and produce only sanitized LIO evidence.

    ``request_settings`` is an optional, already-captured request observation
    keyed by gateway request ID. It is deliberately separate from persisted
    Monitor metadata: P04's history stores correlation, not request parameters.
    Each request observation proves only the external-request ``observed``
    stage. Effective settings require independent backend-runtime evidence and
    are therefore never synthesized here.
    """
    if not isinstance(correlation, dict) or not isinstance(trial, dict):
        raise ValueError("correlation or trial descriptor is invalid")
    validate_trial(trial)
    context = correlation.get("context")
    request_ids = correlation.get("request_ids")
    if (
        correlation.get("verification_status") != "verified"
        or not isinstance(context, dict)
        or context.get("verification_status") != "verified"
        or context.get("schema_version") != 1
        or context.get("provenance_source") != "llm_monitor_gateway_credential"
    ):
        raise ValueError("correlation is missing verified P04 provenance")
    if not isinstance(request_ids, list) or not request_ids:
        raise ValueError("correlation has no verified request IDs")
    if any(not isinstance(item, str) or not item for item in request_ids):
        raise ValueError("correlation request IDs are invalid")
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("correlation request IDs are duplicated")

    execution_id = context.get("execution_id")
    if (
        correlation.get("execution_id") != expected_execution_id
        or execution_id != expected_execution_id
    ):
        raise ValueError("correlation execution_id mismatch")
    if context.get("trial_id") != trial["trial_id"]:
        raise ValueError("correlation native trial_id mismatch")
    if (
        context.get("run_id") != trial["run_id"]
        or context.get("task_id") != trial["task_id"]
        or context.get("repetition_id") != str(trial["repetition"])
        or context.get("variant_id") != expected_variant_id
    ):
        raise ValueError("correlation run, task, repetition or variant mismatch")

    by_id: dict[str, dict[str, Any]] = {}
    for row in request_rows:
        if not isinstance(row, dict):
            raise ValueError("persisted request row is invalid")
        request_id = row.get("request_id")
        if request_id not in request_ids:
            continue  # Unrelated local clients are never included by time overlap.
        if request_id in by_id:
            raise ValueError("persisted request row is duplicated")
        persisted = row.get("benchmark_correlation")
        if not isinstance(persisted, dict):
            raise ValueError("persisted request correlation is missing")
        for key in (
            "schema_version",
            "run_id",
            "task_id",
            "execution_id",
            "trial_id",
            "repetition_id",
            "variant_id",
            "verification_status",
            "provenance_source",
        ):
            if persisted.get(key) != context.get(key):
                raise ValueError("persisted request correlation context mismatch")
        by_id[request_id] = row
    if set(by_id) != set(request_ids):
        raise ValueError("one or more correlated requests are not persisted")

    if (
        not isinstance(requested_settings, Mapping)
        or not isinstance(planned_settings, Mapping)
        or not isinstance(request_settings, Mapping)
    ):
        raise ValueError("evidence settings mappings are invalid")

    evidence_records = []
    all_fields = set(requested_settings) | set(planned_settings)
    for request_id in request_ids:
        observations = []
        for stage, values, source in (
            ("requested", requested_settings, "profile_config"),
            ("planned", planned_settings, "compiled_plan"),
        ):
            for field, value in sorted(values.items()):
                observations.append(
                    {
                        "field": field,
                        "stage": stage,
                        "value": value,
                        "status": "reported",
                        "source": source,
                        "timestamp": timestamp,
                    }
                )

        captured = request_settings.get(request_id)
        if captured is None:
            normalized = {"status": "unavailable", "observations": []}
        else:
            normalized = monitor_request_observations(
                {
                    "value": captured,
                    "source": "external_request_capture",
                    "verification_status": "verified",
                },
                timestamp,
            )
        captured_fields = set()
        for item in normalized["observations"]:
            observations.append(item)
            captured_fields.add(item["field"])
        for field in sorted(all_fields - captured_fields):
            observations.append(
                {
                    "field": field,
                    "stage": "observed",
                    "value": None,
                    "status": "unavailable",
                    "source": "external_request_capture",
                    "timestamp": timestamp,
                }
            )

        safe_trace = {
            key: context.get(key)
            for key in (
                "schema_version",
                "run_id",
                "task_id",
                "execution_id",
                "trial_id",
                "repetition_id",
                "variant_id",
                "verification_status",
                "provenance_source",
            )
        }
        artifact_digest = hashlib.sha256(
            canonical_bytes({"request_id": request_id, "correlation": safe_trace})
        ).hexdigest()
        evidence = {
            "schema": "lio-evidence-v1",
            "experiment_id": experiment_id,
            "variant_sha256": trial["variant_sha256"],
            "run_id": trial["run_id"],
            "trial_id": trial["trial_id"],
            "task_id": trial["task_id"],
            "producer": {"name": "p04_correlation_adapter", "version": "1"},
            "observations": observations,
            "artifacts": [
                {
                    "id": f"monitor-correlation-{artifact_digest[:24]}",
                    "sha256": artifact_digest,
                }
            ],
        }
        validate_evidence(evidence)
        evidence_records.append(evidence)

    effective_settings = {}
    if backend_runtime_evidence is not None:
        if not isinstance(backend_runtime_evidence, Mapping) or set(
            backend_runtime_evidence
        ) != {"backend", "artifact", "observations"}:
            raise ValueError("backend runtime evidence descriptor is invalid")
        backend = backend_runtime_evidence["backend"]
        artifact = backend_runtime_evidence["artifact"]
        runtime_observations = backend_runtime_evidence["observations"]
        if (
            not isinstance(backend, dict)
            or set(backend) != {"identity", "version"}
            or not isinstance(artifact, dict)
            or set(artifact) != {"id", "sha256"}
            or not isinstance(runtime_observations, list)
            or not runtime_observations
        ):
            raise ValueError("backend runtime evidence is incomplete")
        effective_observations = []
        for item in runtime_observations:
            if not isinstance(item, dict) or set(item) != {
                "field",
                "value",
                "timestamp",
            }:
                raise ValueError("backend runtime observation is invalid")
            field = item["field"]
            value = item["value"]
            observed = {
                "field": field,
                "stage": "observed",
                "value": value,
                "status": "verified",
                "source": "backend_runtime",
                "timestamp": item["timestamp"],
            }
            effective = {**observed, "stage": "effective"}
            effective_observations.extend((observed, effective))
            effective_settings[field] = value
        runtime_evidence = {
            "schema": "lio-evidence-v1",
            "experiment_id": experiment_id,
            "variant_sha256": trial["variant_sha256"],
            "run_id": trial["run_id"],
            "trial_id": trial["trial_id"],
            "task_id": trial["task_id"],
            "producer": {"name": "backend_runtime_attestation", "version": "1"},
            "backend": dict(backend),
            "observations": effective_observations,
            "artifacts": [dict(artifact)],
        }
        validate_evidence(runtime_evidence)
        evidence_records.append(runtime_evidence)

    captured_request_ids = [
        request_id
        for request_id in request_ids
        if isinstance(request_settings.get(request_id), dict)
    ]
    request_capture_status = (
        "complete"
        if len(captured_request_ids) == len(request_ids)
        else "partial"
        if captured_request_ids
        else "unavailable"
    )
    missing_runtime_fields = sorted(all_fields - set(effective_settings))
    evidence_gaps = (
        ["backend_runtime_settings_unavailable"]
        if not effective_settings
        else [
            f"backend_runtime_setting_missing:{field}"
            for field in missing_runtime_fields
        ]
    )
    return {
        "trial": trial,
        "correlation": {
            "schema_version": context["schema_version"],
            "run_id": context["run_id"],
            "task_id": context["task_id"],
            "execution_id": context["execution_id"],
            "trial_id": context["trial_id"],
            "repetition_id": context["repetition_id"],
            "variant_id": context["variant_id"],
            "verification_status": context["verification_status"],
            "provenance_source": context["provenance_source"],
        },
        "request_ids": list(request_ids),
        "request_capture_status": request_capture_status,
        "evidence_records": evidence_records,
        "effective_settings": effective_settings,
        "evidence_gaps": evidence_gaps,
    }
