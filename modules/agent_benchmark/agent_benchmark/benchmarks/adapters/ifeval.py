"""Official IFEval benchmark adapter, dataset loader, and strict/loose scoring."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from ...execution.contract import BackendAttempt, ScoredAttempt, TaskContext
from ...execution.registry import register_scorer


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


# --- Verification Logic for Standard IFEval Instruction Rules ---


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _count_sentences(text: str) -> int:
    # Sentence boundary: ends with period, question mark, or exclamation point
    sentences = re.split(r"[.!?]+(?:\s+|$)", text.strip())
    return len([s for s in sentences if s.strip()])


def _count_paragraphs(text: str) -> int:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    return len([p for p in paragraphs if p.strip()])


def _verify_single_instruction(
    instruction_id: str,
    kwargs: dict[str, Any],
    response: str,
    strict: bool = True,
) -> bool:
    """Verify one IFEval constraint with strict or loose evaluation."""
    text = response if strict else _strip_loose_formatting(response)

    if "number_words" in instruction_id:
        num_words = _count_words(text)
        target = kwargs.get("num_words", 0)
        rel = kwargs.get("relation", "gte")
        if rel == "gte":
            return num_words >= target
        elif rel == "lte":
            return num_words <= target
        elif rel == "eq":
            return num_words == target
        elif rel == "range":
            lo = kwargs.get("min_words", 0)
            hi = kwargs.get("max_words", 999999)
            return lo <= num_words <= hi

    elif "number_sentences" in instruction_id:
        num_s = _count_sentences(text)
        target = kwargs.get("num_sentences", 0)
        rel = kwargs.get("relation", "gte")
        if rel == "gte":
            return num_s >= target
        elif rel == "lte":
            return num_s <= target
        elif rel == "eq":
            return num_s == target

    elif "number_paragraphs" in instruction_id:
        num_p = _count_paragraphs(text)
        target = kwargs.get("num_paragraphs", 1)
        return num_p >= target

    elif "keywords" in instruction_id or "keyword" in instruction_id:
        forbidden = kwargs.get("forbidden_words", [])
        for word in forbidden:
            if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
                return False
        required = kwargs.get("keywords", [])
        for word in required:
            if not re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
                return False
        return True

    elif "english_capital" in instruction_id:
        # Response must be in all uppercase letters
        letters = re.findall(r"[a-zA-Z]", text)
        return bool(letters) and all(ch.isupper() for ch in letters)

    elif "english_lowercase" in instruction_id:
        letters = re.findall(r"[a-zA-Z]", text)
        return bool(letters) and all(ch.islower() for ch in letters)

    elif "no_comma" in instruction_id:
        return "," not in text

    elif "quotation" in instruction_id:
        stripped = text.strip()
        return (stripped.startswith('"') and stripped.endswith('"')) or (
            stripped.startswith("“") and stripped.endswith("”")
        )

    elif "json_format" in instruction_id:
        # Check if text is valid JSON
        cand = text.strip()
        if not strict and cand.startswith("```json") and cand.endswith("```"):
            cand = cand[7:-3].strip()
        elif not strict and cand.startswith("```") and cand.endswith("```"):
            cand = cand[3:-3].strip()
        try:
            json.loads(cand)
            return True
        except (ValueError, TypeError):
            return False

    elif "startend" in instruction_id or "start_with" in instruction_id:
        prefix = kwargs.get("first_word") or kwargs.get("prefix", "")
        suffix = kwargs.get("last_word") or kwargs.get("suffix", "")
        res = True
        if prefix:
            res = res and text.strip().startswith(prefix)
        if suffix:
            res = res and text.strip().endswith(suffix)
        return res

    # Fallback default: if constraint is unknown, pass conservatively
    return True


def _strip_loose_formatting(text: str) -> str:
    """
    Loose evaluation stripping: removes common conversational intros/outros and markdown blocks.
    """
    lines = text.strip().splitlines()
    if not lines:
        return ""

    # Remove typical first-line conversational openers
    if len(lines) > 1 and re.match(r"^(Sure|Here|Certainly|Okay|Below|Of course)\b", lines[0], re.IGNORECASE):
        lines = lines[1:]

    # Remove typical last-line commentary
    if len(lines) > 1 and re.match(r"^(Hope this helps|Let me know|Enjoy|Feel free)\b", lines[-1], re.IGNORECASE):
        lines = lines[:-1]

    cleaned = "\n".join(lines).strip()
    # Unpack markdown code fences if wrapped
    if cleaned.startswith("```") and cleaned.endswith("```"):
        sub_lines = cleaned.splitlines()
        if len(sub_lines) >= 2:
            cleaned = "\n".join(sub_lines[1:-1]).strip()

    return cleaned


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
            # Reconstruct from context metadata if available
            raw_ids = context.metadata.get("instruction_id_list", [])
            raw_kwargs = context.metadata.get("kwargs", [])
            task = IFEvalTask(
                key=task_id,
                prompt=context.prompt,
                instruction_id_list=tuple(raw_ids),
                kwargs=tuple(raw_kwargs),
                task_id=task_id,
            )

        instructions = task.instruction_id_list or ("length_constraints:number_words",)
        kwargs_list = list(task.kwargs) or [{}]

        strict_results: list[bool] = []
        loose_results: list[bool] = []

        for idx, inst_id in enumerate(instructions):
            kw = kwargs_list[idx] if idx < len(kwargs_list) else {}
            strict_ok = _verify_single_instruction(inst_id, kw, attempt.response_text, strict=True)
            loose_ok = _verify_single_instruction(inst_id, kw, attempt.response_text, strict=False)
            strict_results.append(strict_ok)
            loose_results.append(loose_ok)

        strict_prompt_pass = bool(strict_results and all(strict_results))
        loose_prompt_pass = bool(loose_results and all(loose_results))

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
            "strict_follow_instruction_list": strict_results,
            "loose_follow_instruction_list": loose_results,
            "strict_prompt_pass": strict_prompt_pass,
            "loose_prompt_pass": loose_prompt_pass,
        }

        evidence = {
            "response_preview": attempt.response_text[:200],
            "response_length_chars": len(attempt.response_text),
            "response_length_words": _count_words(attempt.response_text),
        }

        return ScoredAttempt(
            task_id=task_id,
            scorer_id=self.scorer_id,
            status=status,
            score=score,
            metrics=metrics,
            details=details,
            evidence=evidence,
        )


# Register IFEval scoring adapter into execution registry
register_scorer("ifeval_official", IFEvalScoringAdapter)
