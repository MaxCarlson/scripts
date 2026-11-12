"""Official Google IFEval benchmark adapter, dataset loader, and strict/loose scoring."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ...execution.contract import BackendAttempt, ScoredAttempt, TaskContext
from ...execution.registry import register_scorer
from ..ifeval import (
    INSTRUCTION_DICT,
    InputExample,
    test_instruction_following_loose,
    test_instruction_following_strict,
)


@dataclass(frozen=True)
class IFEvalTask:
    """A single instruction-following evaluation task."""

    key: int | str
    prompt: str
    instruction_id_list: tuple[str, ...]
    kwargs: tuple[dict[str, Any], ...]
    task_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "prompt": self.prompt,
            "instruction_id_list": list(self.instruction_id_list),
            "kwargs": [dict(kw) for kw in self.kwargs],
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IFEvalTask:
        key = data.get("key", 0)
        task_id = str(data.get("task_id") or f"ifeval-{key}")
        return cls(
            key=key,
            prompt=data["prompt"],
            instruction_id_list=tuple(data.get("instruction_id_list", ())),
            kwargs=tuple(data.get("kwargs", ())),
            task_id=task_id,
        )


def load_ifeval_tasks(jsonl_path: Path) -> dict[str, IFEvalTask]:
    """Load IFEval tasks from an input_data.jsonl file."""
    tasks: dict[str, IFEvalTask] = {}
    if not jsonl_path.is_file():
        return tasks

    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        task = IFEvalTask.from_dict(item)
        tasks[task.task_id] = task
    return tasks


def select_stratified_100_cohort(tasks: list[IFEvalTask]) -> tuple[str, ...]:
    """
    Deterministic stratified 100-task cohort selection across instruction categories.
    """
    sorted_tasks = sorted(tasks, key=lambda t: str(t.key))
    if len(sorted_tasks) <= 100:
        return tuple(t.task_id for t in sorted_tasks)

    # Group by primary instruction family
    groups: dict[str, list[IFEvalTask]] = {}
    for t in sorted_tasks:
        family = t.instruction_id_list[0].split(":")[0] if t.instruction_id_list else "other"
        groups.setdefault(family, []).append(t)

    # Stratified round-robin selection
    selected_ids: list[str] = []
    group_keys = sorted(groups.keys())
    indices = {k: 0 for k in group_keys}

    while len(selected_ids) < 100:
        added_in_round = False
        for k in group_keys:
            if len(selected_ids) >= 100:
                break
            idx = indices[k]
            if idx < len(groups[k]):
                selected_ids.append(groups[k][idx].task_id)
                indices[k] += 1
                added_in_round = True
        if not added_in_round:
            break

    return tuple(sorted(selected_ids))


def verify_single_instruction(
    instruction_id: str,
    kwargs: dict[str, Any],
    response: str,
    prompt: str = "",
    strict: bool = True,
) -> bool:
    """
    Verify one IFEval constraint using the official reference instruction implementation.

    Rejects unknown or unsupported instruction IDs with False (never True).
    """
    if instruction_id not in INSTRUCTION_DICT:
        return False

    instruction_cls = INSTRUCTION_DICT[instruction_id]
    instruction = instruction_cls(instruction_id)
    try:
        instruction.build_description(**kwargs)
        args = instruction.get_instruction_args()
        if args and "prompt" in args and prompt:
            instruction.build_description(prompt=prompt)
    except Exception:
        return False

    if strict:
        return bool(response.strip() and instruction.check_following(response))

    # Official 8 loose variants check
    r = response.split("\n")
    response_remove_first = "\n".join(r[1:]).strip()
    response_remove_last = "\n".join(r[:-1]).strip()
    response_remove_both = "\n".join(r[1:-1]).strip()
    revised_response = response.replace("*", "")
    revised_response_remove_first = response_remove_first.replace("*", "")
    revised_response_remove_last = response_remove_last.replace("*", "")
    revised_response_remove_both = response_remove_both.replace("*", "")
    all_responses = [
        response,
        revised_response,
        response_remove_first,
        response_remove_last,
        response_remove_both,
        revised_response_remove_first,
        revised_response_remove_last,
        revised_response_remove_both,
    ]
    for cand in all_responses:
        if cand.strip() and instruction.check_following(cand):
            return True
    return False


class IFEvalScoringAdapter:
    """Official Google IFEval scoring adapter calculating strict and loose accuracies."""

    scorer_id = "ifeval_official"

    def __init__(self, task_cache: dict[str, IFEvalTask] | None = None) -> None:
        self.task_cache = task_cache or {}

    def score_task(
        self,
        task_id: str,
        attempt: BackendAttempt,
        context: TaskContext,
    ) -> ScoredAttempt:
        if attempt.status == "timed_out":
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="timed_out",
                score=0.0,
                error_code=attempt.error_code,
                error_detail=attempt.error_detail,
            )

        if attempt.status == "error":
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="infrastructure_invalid",
                score=0.0,
                error_code=attempt.error_code or "INFERENCE_ERROR",
                error_detail=attempt.error_detail or "Model generation failed",
            )

        # Retrieve task instruction definitions
        task = self.task_cache.get(task_id)
        if not task:
            raw_ids = context.metadata.get("instruction_id_list", [])
            raw_kwargs = context.metadata.get("kwargs", [])
            if raw_ids:
                task = IFEvalTask(
                    key=task_id,
                    prompt=context.prompt,
                    instruction_id_list=tuple(raw_ids),
                    kwargs=tuple(raw_kwargs),
                    task_id=task_id,
                )

        if not task or not task.instruction_id_list:
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="infrastructure_invalid",
                score=0.0,
                error_code="MISSING_BENCHMARK_DATA",
                error_detail=f"Task {task_id} has no instruction metadata in cache or context",
            )

        instructions = task.instruction_id_list
        kwargs_list = list(task.kwargs) if task.kwargs else [{}] * len(instructions)
        # Pad kwargs_list if shorter than instructions
        while len(kwargs_list) < len(instructions):
            kwargs_list.append({})

        # Check for unknown instruction IDs: reject unsupported instructions
        unsupported = [iid for iid in instructions if iid not in INSTRUCTION_DICT]

        inp = InputExample(
            key=int(task.key) if isinstance(task.key, int) or (isinstance(task.key, str) and task.key.isdigit()) else 0,
            instruction_id_list=list(instructions),
            prompt=task.prompt or context.prompt,
            kwargs=[dict(kw) for kw in kwargs_list],
        )
        prompt_map = {inp.prompt: attempt.response_text}

        strict_out = test_instruction_following_strict(inp, prompt_map)
        loose_out = test_instruction_following_loose(inp, prompt_map)

        strict_results = strict_out.follow_instruction_list
        loose_results = loose_out.follow_instruction_list

        strict_prompt_pass = bool(strict_out.follow_all_instructions)
        loose_prompt_pass = bool(loose_out.follow_all_instructions)

        strict_passed_count = sum(strict_results)
        loose_passed_count = sum(loose_results)
        total_instructions = len(instructions)

        strict_inst_acc = round(strict_passed_count / total_instructions, 4) if total_instructions else 0.0
        loose_inst_acc = round(loose_passed_count / total_instructions, 4) if total_instructions else 0.0

        status = "passed" if strict_prompt_pass else "failed"
        score = 1.0 if strict_prompt_pass else 0.0

        metrics = {
            "ifeval.strict_prompt": 1.0 if strict_prompt_pass else 0.0,
            "ifeval.loose_prompt": 1.0 if loose_prompt_pass else 0.0,
            "ifeval.strict_instructions_passed": strict_passed_count,
            "ifeval.loose_instructions_passed": loose_passed_count,
            "ifeval.instructions_total": total_instructions,
            "ifeval.strict_instruction_acc": strict_inst_acc,
            "ifeval.loose_instruction_acc": loose_inst_acc,
        }

        details = {
            "instruction_id_list": list(instructions),
            "unsupported_instruction_ids": unsupported,
            "strict_follow_instruction_list": strict_results,
            "loose_follow_instruction_list": loose_results,
            "strict_prompt_pass": strict_prompt_pass,
            "loose_prompt_pass": loose_prompt_pass,
        }

        evidence = {
            "response_preview": attempt.response_text[:200],
            "response_length_chars": len(attempt.response_text),
        }

        error_code = None
        error_detail = None
        if unsupported:
            error_code = "UNSUPPORTED_INSTRUCTION"
            error_detail = f"Task contains unsupported instruction IDs: {unsupported}"

        return ScoredAttempt(
            task_id=task_id,
            scorer_id=self.scorer_id,
            status=status,
            score=score,
            metrics=metrics,
            details=details,
            evidence=evidence,
            error_code=error_code,
            error_detail=error_detail,
        )


# Register IFEval scoring adapter into execution registry
register_scorer("ifeval_official", IFEvalScoringAdapter)
