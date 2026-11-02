"""Strict, bounded and deterministic offline experiment contracts."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import re

MAX_BYTES = 262144
MAX_ITEMS = 256
HEX = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
SETTING_TYPES = {
    "context": int,
    "output_limit": int,
    "temperature": (int, float),
    "top_p": (int, float),
    "top_k": int,
    "reasoning": str,
    "flash_attention": bool,
    "kv_cache_type": str,
    "speculation_mode": str,
    "max_draft_tokens": int,
    "batch_size": int,
}


def _mapping(value, required, optional=()):
    if (
        not isinstance(value, dict)
        or not set(required) <= value.keys()
        or value.keys() - set(required) - set(optional)
    ):
        raise ValueError("missing or unsupported fields")
    if len(value) > MAX_ITEMS:
        raise ValueError("too many fields")


def _id(value, *, model_alias=False):
    if (
        not isinstance(value, str)
        or not ID.fullmatch(value)
        or "://" in value
        or ("@" in value and not model_alias)
    ):
        raise ValueError("invalid or sensitive identifier")
    return value


def _sha(value):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError("expected lowercase SHA-256")
    return value


def _version(value, expected):
    if value != expected:
        raise ValueError("unsupported schema")


def _positive(value, maximum=2**31 - 1):
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError("expected positive integer")


def _settings(value):
    if (
        not isinstance(value, dict)
        or len(value) > len(SETTING_TYPES)
        or value.keys() - SETTING_TYPES.keys()
    ):
        raise ValueError("unsupported setting")
    for name, item in value.items():
        expected = SETTING_TYPES[name]
        if type(item) not in (expected if isinstance(expected, tuple) else (expected,)):
            raise ValueError("invalid setting type")
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("non-finite setting")
        if isinstance(item, str):
            _id(item)
        if name in {"context", "output_limit", "batch_size", "max_draft_tokens"}:
            _positive(item)
        if name == "top_k" and item < 0:
            raise ValueError("invalid top_k")
        if name == "temperature" and item < 0:
            raise ValueError("invalid temperature")
        if name == "top_p" and not 0 <= item <= 1:
            raise ValueError("invalid top_p")


def canonical_bytes(value):
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 8192 or depth > 16:
            raise ValueError("contract structure exceeds limits")
        if isinstance(item, str):
            if len(item) > 4096:
                raise ValueError("contract string exceeds limit")
        elif isinstance(item, dict):
            if len(item) > MAX_ITEMS or any(not isinstance(k, str) for k in item):
                raise ValueError("invalid contract mapping")
            pending.extend((k, depth + 1) for k in item)
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            if len(item) > MAX_ITEMS:
                raise ValueError("contract list exceeds limit")
            pending.extend((v, depth + 1) for v in item)
        elif item is not None and type(item) not in (int, float, bool):
            raise ValueError("invalid contract value")
    try:
        result = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid canonical data") from exc
    if len(result) > MAX_BYTES:
        raise ValueError("contract exceeds size limit")
    return result


def _fingerprint(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_experiment(value):
    _mapping(
        value,
        (
            "schema",
            "study_id",
            "task_set",
            "baseline_ref",
            "fixed",
            "dimensions",
            "repetitions",
            "randomization",
            "success_criterion",
            "rejection_criterion",
        ),
    )
    _version(value["schema"], "lio-experiment-v1")
    for key in ("study_id", "baseline_ref", "success_criterion", "rejection_criterion"):
        _id(value[key])
    task = value["task_set"]
    _mapping(task, ("id", "sha256"))
    _id(task["id"])
    _sha(task["sha256"])
    _settings(value["fixed"])
    dimensions = value["dimensions"]
    if (
        not isinstance(dimensions, list)
        or len(dimensions) > len(SETTING_TYPES)
        or any(not isinstance(x, str) or x not in SETTING_TYPES for x in dimensions)
        or len(set(dimensions)) != len(dimensions)
    ):
        raise ValueError("invalid dimensions")
    _positive(value["repetitions"])
    _mapping(value["randomization"], ("method", "seed"))
    if (
        value["randomization"]["method"]
        not in {"counterbalanced", "randomized", "fixed"}
        or type(value["randomization"]["seed"]) is not int
        or not 0 <= value["randomization"]["seed"] < 2**63
    ):
        raise ValueError("invalid randomization policy")
    canonical_bytes(value)
    return value


def experiment_fingerprint(value):
    validate_experiment(value)
    normalized = dict(value, dimensions=sorted(value["dimensions"]))
    return _fingerprint(normalized)


def validate_model(value):
    _mapping(value, ("alias", "file_identity", "quantization"))
    _id(value["alias"], model_alias=True)
    _id(value["quantization"])
    file = value["file_identity"]
    _mapping(file, ("status", "size_bytes", "sha256"), ("file_path",))
    if "file_path" in file:
        path = file["file_path"]
        if (
            not isinstance(path, str)
            or not 0 < len(path) <= 1024
            or any(ord(c) < 32 for c in path)
            or "@" in path
            or "?" in path
            or "#" in path
        ):
            raise ValueError("invalid or sensitive file path")
    if not isinstance(file["status"], str) or file["status"] not in {
        "unknown",
        "weak",
        "verified",
    }:
        raise ValueError("invalid identity status")
    if file["size_bytes"] is not None:
        _positive(file["size_bytes"], 2**63 - 1)
    if file["status"] == "verified":
        _sha(file["sha256"])
    elif file["sha256"] is not None:
        raise ValueError("unverified identity cannot claim digest")
    if file["status"] == "weak" and file["size_bytes"] is None:
        raise ValueError("weak identity needs observed size")
    if file["status"] == "unknown" and file["size_bytes"] is not None:
        raise ValueError("unknown identity cannot claim size")


def validate_variant(value):
    _mapping(
        value,
        (
            "schema",
            "model",
            "context",
            "output_limit",
            "reasoning",
            "sampling",
            "features",
            "prompt_policy",
            "config_sha256",
        ),
    )
    _version(value["schema"], "lio-variant-v1")
    validate_model(value["model"])
    _positive(value["context"])
    _positive(value["output_limit"])
    _id(value["reasoning"])
    _id(value["prompt_policy"])
    _sha(value["config_sha256"])
    _settings(value["sampling"])
    _settings(value["features"])
    canonical_bytes(value)
    return value


def variant_fingerprint(value):
    validate_variant(value)
    normalized = dict(
        value,
        model=dict(
            value["model"],
            file_identity={
                k: v
                for k, v in value["model"]["file_identity"].items()
                if k != "file_path"
            },
        ),
    )
    return _fingerprint(normalized)


def has_verified_model_digest(value):
    """Return whether model evidence asserts a verified digest; no file is read."""
    validate_variant(value)
    return value["model"]["file_identity"]["status"] == "verified"


def validate_trial(value):
    _mapping(
        value,
        (
            "schema",
            "experiment_sha256",
            "variant_sha256",
            "run_id",
            "trial_id",
            "task_id",
            "repetition",
            "evidence_ref",
            "source_revision",
            "workspace_sha256",
        ),
    )
    _version(value["schema"], "lio-trial-v1")
    for key in ("experiment_sha256", "variant_sha256", "workspace_sha256"):
        _sha(value[key])
    for key in ("run_id", "trial_id", "task_id", "evidence_ref"):
        _id(value[key])
    if not isinstance(value["source_revision"], str) or not re.fullmatch(
        r"[0-9a-f]{40}|[0-9a-f]{64}", value["source_revision"]
    ):
        raise ValueError("invalid source revision")
    if type(value["repetition"]) is not int or not 0 <= value["repetition"] < 1000000:
        raise ValueError("invalid repetition")
    canonical_bytes(value)
    return value


def _timestamp(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be UTC")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc


def validate_metric(metric):
    _mapping(metric, ("name", "value", "unit", "source", "quality"))
    _id(metric["name"])
    _id(metric["unit"])
    _id(metric["source"])
    if not isinstance(metric["quality"], str) or metric["quality"] not in {
        "measured",
        "derived",
        "estimated",
        "unavailable",
    }:
        raise ValueError("invalid metric quality")
    if metric["quality"] == "unavailable":
        if metric["value"] is not None:
            raise ValueError("unavailable metric must be null")
    elif (
        type(metric["value"]) not in (int, float)
        or (type(metric["value"]) is int and abs(metric["value"]) > 2**63 - 1)
        or (type(metric["value"]) is float and not math.isfinite(metric["value"]))
    ):
        raise ValueError("invalid metric value")


def validate_evidence(value):
    _mapping(
        value,
        (
            "schema",
            "experiment_id",
            "variant_sha256",
            "run_id",
            "trial_id",
            "producer",
            "observations",
        ),
        (
            "capabilities",
            "activation",
            "model",
            "backend",
            "source_revision",
            "workspace_sha256",
            "prompt_policy",
            "task_id",
            "artifacts",
            "metrics",
        ),
    )
    _version(value["schema"], "lio-evidence-v1")
    for key in ("experiment_id", "run_id", "trial_id"):
        _id(value[key])
    _sha(value["variant_sha256"])
    _mapping(value["producer"], ("name", "version"))
    _id(value["producer"]["name"])
    _id(value["producer"]["version"])
    if "model" in value:
        validate_model(value["model"])
    if "backend" in value:
        _mapping(value["backend"], ("identity", "version"))
        for part in value["backend"].values():
            if part is not None:
                _id(part)
    if "source_revision" in value:
        if not isinstance(value["source_revision"], str) or not re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}", value["source_revision"]
        ):
            raise ValueError("invalid source revision")
    if "workspace_sha256" in value:
        _sha(value["workspace_sha256"])
    for key in ("prompt_policy", "task_id"):
        if key in value:
            _id(value[key])
    for key in ("capabilities", "metrics", "artifacts"):
        if key in value and (
            not isinstance(value[key], list) or len(value[key]) > MAX_ITEMS
        ):
            raise ValueError("invalid evidence list")
    if "activation" in value:
        activation = value["activation"]
        _mapping(activation, ("status", "source"))
        _id(activation["source"])
        if not isinstance(activation["status"], str) or activation["status"] not in {
            "unknown",
            "unsupported",
            "verified",
        }:
            raise ValueError("invalid activation status")
        if activation["status"] == "verified" and (
            activation["source"] != "backend_runtime"
            or not value.get("backend")
            or not all(value["backend"].get(k) for k in ("identity", "version"))
            or not value.get("artifacts")
        ):
            raise ValueError(
                "verified activation requires runtime identity and evidence artifact"
            )
    for capability in value.get("capabilities", []):
        _mapping(capability, ("name", "status", "source"))
        _id(capability["name"])
        _id(capability["source"])
        if not isinstance(capability["status"], str) or capability["status"] not in {
            "unknown",
            "unsupported",
            "verified",
        }:
            raise ValueError("invalid capability status")
        if capability["status"] == "verified" and (
            capability["source"] != "backend_runtime"
            or not value.get("backend")
            or not all(value["backend"].get(k) for k in ("identity", "version"))
            or not value.get("artifacts")
        ):
            raise ValueError(
                "verified capability requires runtime identity and evidence artifact"
            )
    for artifact in value.get("artifacts", []):
        _mapping(artifact, ("id", "sha256"))
        _id(artifact["id"])
        _sha(artifact["sha256"])
    for metric in value.get("metrics", []):
        validate_metric(metric)
    observations = value["observations"]
    if not isinstance(observations, list) or len(observations) > MAX_ITEMS:
        raise ValueError("invalid observations")
    seen = set()
    effective = {}
    for obs in observations:
        _mapping(obs, ("field", "stage", "value", "status", "source", "timestamp"))
        field, stage, status = obs["field"], obs["stage"], obs["status"]
        if (
            not isinstance(field, str)
            or field not in SETTING_TYPES
            or not isinstance(stage, str)
            or not isinstance(status, str)
            or stage not in {"requested", "planned", "observed", "effective"}
            or status
            not in {"reported", "verified", "unknown", "unavailable", "unsupported"}
        ):
            raise ValueError("invalid observation")
        _id(obs["source"])
        _timestamp(obs["timestamp"])
        if (field, stage) in seen:
            raise ValueError("duplicate field and stage")
        seen.add((field, stage))
        if status in {"unknown", "unavailable", "unsupported"}:
            if obs["value"] is not None:
                raise ValueError("unknown evidence cannot have value")
        else:
            _settings({field: obs["value"]})
        if stage == "effective":
            if status != "verified" or obs["source"] != "backend_runtime":
                raise ValueError(
                    "effective values require verified backend runtime evidence"
                )
            effective[field] = obs["value"]
    if effective and (
        not value.get("backend")
        or not all(value["backend"].get(k) for k in ("identity", "version"))
        or not value.get("artifacts")
    ):
        raise ValueError(
            "effective values require backend identity and evidence artifact"
        )
    for field, expected in effective.items():
        effective_timestamp = next(
            obs["timestamp"]
            for obs in observations
            if obs["field"] == field and obs["stage"] == "effective"
        )
        matches = [
            obs
            for obs in observations
            if obs["field"] == field
            and obs["stage"] == "observed"
            and obs["status"] == "verified"
            and obs["source"] == "backend_runtime"
            and obs["timestamp"] == effective_timestamp
            and type(obs["value"]) is type(expected)
            and obs["value"] == expected
        ]
        if len(matches) != 1:
            raise ValueError(
                "effective setting requires correlated verified runtime observation"
            )
    canonical_bytes(value)
    return {"evidence": value, "effective": effective}
