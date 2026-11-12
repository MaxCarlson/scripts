"""Authentic task data resolver and prompt generator for external benchmarks."""

from __future__ import annotations

import base64
import functools
import json
from pathlib import Path
import pickletools
from typing import Any
import zlib

from .adapters.ifeval import IFEvalTask, load_ifeval_tasks
from .adapters.livecodebench import LCBProblem, format_lcb_prompt
from ..external_sources import SourceManager


_MAX_DECOMPRESSED_BYTES = 512 * 1024 * 1024
# Opcodes that can appear in a pickle containing nothing but a single (JSON) string.
# Anything else (GLOBAL/REDUCE/BUILD/INST/OBJ/...) is rejected without executing the stream.
_SAFE_STRING_PICKLE_OPS = frozenset({
    "PROTO", "FRAME", "STOP", "MEMOIZE", "PUT", "BINPUT", "LONG_BINPUT",
    "UNICODE", "BINUNICODE", "SHORT_BINUNICODE", "BINUNICODE8",
})
_STRING_OPS = frozenset({"UNICODE", "BINUNICODE", "SHORT_BINUNICODE", "BINUNICODE8"})


def _extract_pickled_string(data: bytes) -> str | None:
    """
    Extract the string payload of a legacy LiveCodeBench pickle WITHOUT deserializing it.

    The pickle opcode stream is only *tokenized* (``pickletools.genops`` never executes anything).
    The stream must consist solely of allowlisted opcodes carrying exactly one string; any
    other opcode (e.g. GLOBAL/STACK_GLOBAL/REDUCE used by malicious payloads) rejects the data.
    """
    strings: list[str] = []
    try:
        for opcode, arg, _pos in pickletools.genops(data):
            if opcode.name not in _SAFE_STRING_PICKLE_OPS:
                return None
            if opcode.name in _STRING_OPS:
                strings.append(arg)
    except Exception:
        return None
    return strings[0] if len(strings) == 1 else None


def _decompress_bounded(raw: bytes) -> bytes | None:
    d = zlib.decompressobj()
    try:
        out = d.decompress(raw, _MAX_DECOMPRESSED_BYTES)
    except zlib.error:
        return None
    if d.unconsumed_tail:  # exceeded the size bound (decompression bomb)
        return None
    return out


def decode_test_cases(raw: Any) -> list[dict[str, Any]]:
    """
    Decode JSON or base64/zlib/pickle-encoded test cases from the LiveCodeBench dataset.

    Never calls ``pickle.loads``: legacy pickle payloads are tokenized and must be a bare string
    (see ``_extract_pickled_string``). Returns list of dicts with 'input' and 'output' keys, or
    an empty list for undecodable/unsafe data (callers classify that as missing benchmark data).
    """
    if not raw:
        return []
    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, dict)]
    if not isinstance(raw, str):
        return []
    clean = raw.strip()
    if not clean:
        return []
    try:
        val = json.loads(clean)
        if isinstance(val, list):
            return [t for t in val if isinstance(t, dict)]
    except Exception:
        pass
    try:
        decompressed = _decompress_bounded(base64.b64decode(clean.encode("utf-8"), validate=True))
    except Exception:
        return []
    if decompressed is None:
        return []
    payload: Any = None
    text = _extract_pickled_string(decompressed)
    try:
        if text is not None:
            payload = json.loads(text)
        else:
            payload = json.loads(decompressed.decode("utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [t for t in payload if isinstance(t, dict)]
    return []

def get_ifeval_data_path(resource_root: Path | None = None) -> Path | None:
    """Locate official input_data.jsonl in verified installation or package data."""
    # 1. Check verified installation via SourceManager
    sm = SourceManager(resource_root)
    installed = sm.resolve_installed_path("ifeval", "google-research-ifeval")
    if installed:
        for candidate in (
            installed / "instruction_following_eval" / "data" / "input_data.jsonl",
            installed / "data" / "input_data.jsonl",
            installed / "input_data.jsonl",
        ):
            if candidate.is_file():
                return candidate.resolve()

    # 2. Package bundled official dataset
    pkg_data = Path(__file__).parent / "ifeval" / "data" / "input_data.jsonl"
    if pkg_data.is_file():
        return pkg_data.resolve()

    return None


def get_lcb_data_path(resource_root: Path | None = None, *, allow_smoke: bool = False) -> Path | None:
    """
    Locate official LiveCodeBench test6.jsonl from verified installation.
    If allow_smoke is True, allows fallback to bundled smoke fixture.
    For full/100 cohorts, allow_smoke MUST remain False to prevent silent fallback.
    """
    # 1. Check verified installation via SourceManager
    sm = SourceManager(resource_root)
    installed = sm.resolve_installed_path("livecodebench", "lcb-code-generation-lite")
    if installed:
        for candidate in (
            installed / "test6.jsonl",
            installed / "datasets" / "test6.jsonl",
        ):
            if candidate.is_file():
                return candidate.resolve()

    # 2. Canonical external store location
    for parent in (
        sm.layout["datasets"] / "livecodebench",
        sm.layout["datasets"] / "lcb-code-generation-lite",
    ):
        if parent.is_dir():
            for child in parent.iterdir():
                cand = child / "test6.jsonl"
                if cand.is_file():
                    return cand.resolve()

    # 3. Only if allow_smoke is explicitly permitted (e.g. smoke cohort / offline testing)
    if allow_smoke:
        pkg_data = Path(__file__).parent / "livecodebench" / "data" / "smoke_problems.jsonl"
        if pkg_data.is_file():
            return pkg_data.resolve()

    return None


@functools.lru_cache(maxsize=4)
def load_all_ifeval_tasks(resource_root: Path | None = None) -> dict[str, IFEvalTask]:
    path = get_ifeval_data_path(resource_root)
    if path and path.is_file():
        return load_ifeval_tasks(path)
    return {}


@functools.lru_cache(maxsize=4)
def load_all_lcb_problems(
    resource_root: Path | None = None,
    *,
    allow_smoke: bool = False,
) -> dict[str, LCBProblem]:
    path = get_lcb_data_path(resource_root, allow_smoke=allow_smoke)
    if not path or not path.is_file():
        return {}

    problems: dict[str, LCBProblem] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            qid = str(item["question_id"])
            tid = f"lcb-{qid}"

            # Extract inputs/outputs combining public and private test cases
            meta = json.loads(item["metadata"]) if isinstance(item.get("metadata"), str) else (item.get("metadata") or {})
            fn_name = meta.get("fn_name")

            public_cases = decode_test_cases(item.get("public_test_cases"))
            private_cases = decode_test_cases(item.get("private_test_cases"))
            all_cases = public_cases + private_cases

            if all_cases:
                inputs = [t["input"] for t in all_cases if "input" in t and "output" in t]
                outputs = [t["output"] for t in all_cases if "input" in t and "output" in t]
                io_data = {
                    "inputs": inputs,
                    "outputs": outputs,
                    "fn_name": fn_name,
                }
            elif item.get("input_output"):
                io_data = item["input_output"]
            else:
                io_data = {"inputs": [], "outputs": [], "fn_name": fn_name}

            problem = LCBProblem(
                question_id=qid,
                question_title=item.get("question_title", qid),
                difficulty=item.get("difficulty", "medium"),
                contest_date=item.get("contest_date", ""),
                prompt=item.get("question_content", "") or item.get("prompt", ""),
                starter_code=item.get("starter_code", ""),
                input_output=io_data,
                task_id=tid,
            )
            problems[tid] = problem
        except Exception:
            continue
    return problems


def resolve_task_prompt_and_metadata(
    dataset_id: str,
    task_id: str,
    custom_manifest_tasks: dict[str, Any] | None = None,
    *,
    resource_root: Path | None = None,
    cohort_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Resolve authentic prompt string and evaluation metadata for a task.
    Returns (prompt, metadata_dict). If prompt is missing or unresolved, returns ("", {}).
    """
    if custom_manifest_tasks and task_id in custom_manifest_tasks:
        entry = custom_manifest_tasks[task_id]
        if isinstance(entry, dict):
            return entry.get("prompt", ""), entry.get("metadata", {})
        return str(entry), {}

    if dataset_id == "ifeval/google-2023":
        all_tasks = load_all_ifeval_tasks(resource_root)
        task = all_tasks.get(task_id)
        if task:
            meta = {
                "instruction_id_list": list(task.instruction_id_list),
                "kwargs": [dict(k) for k in task.kwargs],
                "key": task.key,
            }
            return task.prompt, meta

    elif dataset_id == "livecodebench/release_v6":
        from .cohort_definitions import LCB_SMOKE_TASKS

        allow_smoke = (cohort_id == "lcb-v6-smoke") or (cohort_id is None and task_id in LCB_SMOKE_TASKS)
        all_problems = load_all_lcb_problems(resource_root, allow_smoke=allow_smoke)
        problem = all_problems.get(task_id)
        if problem:
            prompt = format_lcb_prompt(problem)
            meta = {
                "question_id": problem.question_id,
                "question_title": problem.question_title,
                "difficulty": problem.difficulty,
                "contest_date": problem.contest_date,
                "starter_code": problem.starter_code,
                "input_output": problem.input_output,
            }
            return prompt, meta

    return "", {}
