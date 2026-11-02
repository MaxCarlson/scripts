"""Adapters for existing, already-loaded benchmark and monitor evidence."""

from __future__ import annotations

from .contracts import (
    validate_metric,
    _id,
    _mapping,
    _positive,
    _settings,
    _sha,
    _timestamp,
    _version,
)


def legacy_profile_requests(profile, timestamp):
    """Translate a validated v1 profile into requested settings, never effective settings."""
    _mapping(
        profile, ("schema", "context_length", "output_limit", "reasoning", "sha256")
    )
    _version(profile["schema"], "opencode-inference-profile-v1")
    _positive(profile["context_length"])
    _positive(profile["output_limit"])
    _sha(profile["sha256"])
    reasoning = profile["reasoning"]
    _mapping(reasoning, ("mode", "effort", "provenance"))
    if reasoning["mode"] == "unconfigured":
        if (
            reasoning["effort"] is not None
            or reasoning["provenance"] != "source_config"
        ):
            raise ValueError("invalid legacy reasoning")
    elif reasoning["mode"] == "effort":
        if (
            reasoning["effort"] not in {"none", "low", "medium", "high", "xhigh"}
            or reasoning["provenance"] != "experiment_profile"
        ):
            raise ValueError("invalid legacy reasoning")
    else:
        raise ValueError("invalid legacy reasoning")
    _timestamp(timestamp)
    settings = {
        "context": profile["context_length"],
        "output_limit": profile["output_limit"],
    }
    if reasoning["mode"] == "effort":
        settings["reasoning"] = reasoning["effort"]
    _settings(settings)
    return [
        {
            "field": k,
            "stage": "requested",
            "value": v,
            "status": "reported",
            "source": "legacy_profile",
            "timestamp": timestamp,
        }
        for k, v in sorted(settings.items())
    ]


def benchmark_metric(name, metric):
    """Copy a benchmark_core MetricValue's safe, numerical provenance fields."""
    _id(name)
    _mapping(metric, ("value", "unit", "source", "quality"), ("reason",))
    result = {key: metric[key] for key in ("value", "unit", "source", "quality")}
    result["name"] = name
    validate_metric(result)
    return result


def monitor_request_observations(evidence, timestamp):
    """Normalize a monitor-correlated request; forwarding is not effective activation."""
    _mapping(evidence, ("value", "source", "verification_status"))
    _timestamp(timestamp)
    if evidence["verification_status"] == "unavailable" and evidence["value"] is None:
        return {"status": "unavailable", "observations": []}
    if (
        evidence["source"] != "external_request_capture"
        or evidence["verification_status"] != "verified"
    ):
        raise ValueError("monitor request evidence is not verified")
    data = evidence["value"]
    _mapping(data, ("provider", "model", "parameters"))
    _id(data["provider"])
    _id(data["model"], model_alias=True)
    params = data["parameters"]
    if not isinstance(params, dict):
        raise ValueError("invalid parameters")
    mapping = {
        "temperature": "temperature",
        "top_p": "top_p",
        "top_k": "top_k",
        "max_tokens": "output_limit",
        "max_output_tokens": "output_limit",
        "reasoning_effort": "reasoning",
    }
    if set(params) - mapping.keys():
        raise ValueError("unsupported monitor parameter")
    settings = {}
    for name, value in params.items():
        field = mapping[name]
        if field in settings:
            raise ValueError("ambiguous parameter mapping")
        settings[field] = value
    _settings(settings)
    return {
        "status": "verified",
        "observations": [
            {
                "field": k,
                "stage": "observed",
                "value": v,
                "status": "reported",
                "source": "external_request_capture",
                "timestamp": timestamp,
            }
            for k, v in sorted(settings.items())
        ],
    }
