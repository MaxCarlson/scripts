"""Authentic task data resolver and prompt generator for external benchmarks."""

from __future__ import annotations

import base64
import functools
import json
from pathlib import Path
import pickle
from typing import Any
import zlib

from .adapters.ifeval import IFEvalTask, load_ifeval_tasks
from .adapters.livecodebench import LCBProblem, format_lcb_prompt
from ..external_sources import SourceManager


def decode_test_cases(raw: Any) -> list[dict[str, Any]]:
    """
    Decode JSON or base64/zlib/pickle obfuscated test cases from LiveCodeBench dataset.
    Returns list of dicts with 'input' and 'output' keys.
    """
    if not raw:
        return []
    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, dict)]
    if isinstance(raw, str):
        clean = raw.strip()
        if not clean:
            return []
        # Try direct JSON parsing
        try:
            val = json.loads(clean)
            if isinstance(val, list):
                return [t for t in val if isinstance(t, dict)]
        except Exception:
            pass
        # Try base64 -> zlib -> pickle / json
        try:
            raw_bytes = base64.b64decode(clean.encode("utf-8"))
            decompressed = zlib.decompress(raw_bytes)
            try:
                val = pickle.loads(decompressed)
                if isinstance(val, list):
                    return [t for t in val if isinstance(t, dict)]
            except Exception:
                val = json.loads(decompressed.decode("utf-8"))
                if isinstance(val, list):
                    return [t for t in val if isinstance(t, dict)]
        except Exception:
            pass
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
