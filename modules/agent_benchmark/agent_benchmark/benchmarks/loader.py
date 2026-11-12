"""Authentic task data resolver and prompt generator for external benchmarks."""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

from .adapters.ifeval import IFEvalTask, load_ifeval_tasks
from .adapters.livecodebench import LCBProblem, format_lcb_prompt


def get_ifeval_data_path() -> Path | None:
    """Locate official input_data.jsonl in package data or external store."""
    pkg_data = Path(__file__).parent / "ifeval" / "data" / "input_data.jsonl"
    if pkg_data.is_file():
        return pkg_data
    # Fallback to external store if installed
    from ..external_sources.stores import get_default_resource_root
    ext_data = get_default_resource_root() / "sources" / "google-research-ifeval" / "f8d6d14a1fc6" / "src" / "instruction_following_eval" / "data" / "input_data.jsonl"
    if ext_data.is_file():
        return ext_data
    return None


def get_lcb_data_path() -> Path | None:
    """Locate official LiveCodeBench test6.jsonl or smoke problems."""
    # Check external store for full installed dataset first
    from ..external_sources.stores import get_default_resource_root
    ext_data = get_default_resource_root() / "datasets" / "lcb-code-generation-lite" / "0fe84c3912ea" / "test6.jsonl"
    if ext_data.is_file():
        return ext_data
    # Check package bundled smoke problems
    pkg_data = Path(__file__).parent / "livecodebench" / "data" / "smoke_problems.jsonl"
    if pkg_data.is_file():
        return pkg_data
    return None


@functools.lru_cache(maxsize=1)
def load_all_ifeval_tasks() -> dict[str, IFEvalTask]:
    path = get_ifeval_data_path()
    if path and path.is_file():
        return load_ifeval_tasks(path)
    return {}


@functools.lru_cache(maxsize=1)
def load_all_lcb_problems() -> dict[str, LCBProblem]:
    path = get_lcb_data_path()
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
            # Extract inputs/outputs
            io_data = item.get("input_output")
            if not io_data:
                pub_raw = json.loads(item["public_test_cases"]) if isinstance(item.get("public_test_cases"), str) else (item.get("public_test_cases") or [])
                inputs = [t["input"] for t in pub_raw]
                outputs = [t["output"] for t in pub_raw]
                meta = json.loads(item["metadata"]) if isinstance(item.get("metadata"), str) else (item.get("metadata") or {})
                io_data = {
                    "inputs": inputs,
                    "outputs": outputs,
                    "fn_name": meta.get("fn_name"),
                }
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
        all_tasks = load_all_ifeval_tasks()
        task = all_tasks.get(task_id)
        if task:
            meta = {
                "instruction_id_list": list(task.instruction_id_list),
                "kwargs": [dict(k) for k in task.kwargs],
                "key": task.key,
            }
            return task.prompt, meta

    elif dataset_id == "livecodebench/release_v6":
        all_problems = load_all_lcb_problems()
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
