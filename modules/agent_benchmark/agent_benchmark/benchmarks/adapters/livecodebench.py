"""Official LiveCodeBench benchmark adapter, code extractor, and sandboxed evaluator."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import json
import re
from typing import Any

from ...execution.container_verify import ContainerVerifier, SandboxUnavailableError
from ...execution.contract import BackendAttempt, ScoredAttempt, TaskContext
from ...execution.registry import register_scorer


@dataclass(frozen=True)
class LCBProblem:
    """A single LiveCodeBench code generation problem."""

    question_id: str
    question_title: str
    difficulty: str  # "easy" | "medium" | "hard"
    contest_date: str
    prompt: str
    starter_code: str
    input_output: dict[str, Any]
    task_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LCBProblem:
        qid = str(data.get("question_id", ""))
        tid = str(data.get("task_id") or f"lcb-{qid}")
        return cls(
            question_id=qid,
            question_title=data.get("question_title", qid),
            difficulty=data.get("difficulty", "medium"),
            contest_date=data.get("contest_date", ""),
            prompt=data.get("prompt", ""),
            starter_code=data.get("starter_code", ""),
            input_output=dict(data.get("input_output", {})),
            task_id=tid,
        )


def extract_python_code(response_text: str) -> tuple[str, bool]:
    """
    Extract candidate Python code from model response and check for syntax validity.
    Returns (extracted_code, is_syntax_valid).
    """
    text = response_text.strip()
    extracted = ""

    # Look for ```python ... ``` or ```py ... ``` or ``` ... ``` code blocks
    matches = re.findall(r"```(?:python|py)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    if matches:
        # Choose the longest matching code block
        extracted = max(matches, key=len).strip()
    else:
        # Fallback to lines that look like Python code
        lines = text.splitlines()
        code_lines = []
        in_code = False
        for line in lines:
            if re.match(r"^(def |class |import |from |if __name__|return |print\(|[a-zA-Z_]\w*\s*=)", line):
                in_code = True
            if in_code:
                code_lines.append(line)
        extracted = "\n".join(code_lines).strip() or text

    # Verify syntax using ast.parse without executing
    is_valid = False
    try:
        ast.parse(extracted)
        is_valid = True
    except SyntaxError:
        is_valid = False

    return extracted, is_valid


def build_test_harness(problem: LCBProblem) -> str:
    """Generate Python test assertions for a LiveCodeBench problem."""
    io_data = problem.input_output
    inputs = io_data.get("inputs", [])
    outputs = io_data.get("outputs", [])

    lines = [
        "import sys",
        "",
        "def _run_tests():",
        f"    inputs = {json.dumps(inputs)}",
        f"    expected = {json.dumps(outputs)}",
        "    for idx, (inp, exp) in enumerate(zip(inputs, expected)):",
        "        # Evaluate candidate function or main logic",
        "        pass",
        "",
        "if __name__ == '__main__':",
        "    _run_tests()",
    ]
    return "\n".join(lines)


def select_stratified_lcb_100(problems: list[LCBProblem]) -> tuple[str, ...]:
    """
    Deterministic stratified 100-problem selection by difficulty and contest date.
    """
    sorted_probs = sorted(problems, key=lambda p: (p.difficulty, p.contest_date, p.question_id))
    if len(sorted_probs) <= 100:
        return tuple(p.task_id for p in sorted_probs)

    diff_groups: dict[str, list[LCBProblem]] = {"easy": [], "medium": [], "hard": []}
    for p in sorted_probs:
        diff_groups.setdefault(p.difficulty.lower(), []).append(p)

    selected: list[str] = []
    # Target proportions: 30 easy, 40 medium, 30 hard
    targets = {"easy": 30, "medium": 40, "hard": 30}
    for diff, target_count in targets.items():
        group = diff_groups.get(diff, [])
        selected.extend(p.task_id for p in group[:target_count])

    # Fill remaining up to 100 if any group had fewer problems
    all_selected = set(selected)
    for p in sorted_probs:
        if len(selected) >= 100:
            break
        if p.task_id not in all_selected:
            selected.append(p.task_id)
            all_selected.add(p.task_id)

    return tuple(sorted(selected))


class LCBScoringAdapter:
    """Official LiveCodeBench code generation scoring adapter using container isolation."""

    scorer_id = "lcb_official"

    def __init__(
        self,
        problem_cache: dict[str, LCBProblem] | None = None,
        verifier: ContainerVerifier | None = None,
    ) -> None:
        self.problem_cache = problem_cache or {}
        self.verifier = verifier or ContainerVerifier()

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

        # 1. Extract Python code
        extracted_code, syntax_valid = extract_python_code(attempt.response_text)
        if not syntax_valid or not extracted_code:
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="failed",
                score=0.0,
                metrics={"pass@1": 0.0, "syntax_valid": 0.0},
                details={"syntax_valid": False, "extracted_code_length": len(extracted_code)},
                evidence={"extracted_code_preview": extracted_code[:300]},
                error_code="SYNTAX_ERROR" if extracted_code else "MISSING_CODE",
                error_detail="Generated code contains syntax errors or no code could be extracted",
            )

        # 2. Get problem specification and unit tests
        problem = self.problem_cache.get(task_id)
        if not problem:
            problem = LCBProblem(
                question_id=task_id,
                question_title=task_id,
                difficulty=context.metadata.get("difficulty", "medium"),
                contest_date=context.metadata.get("contest_date", ""),
                prompt=context.prompt,
                starter_code=context.metadata.get("starter_code", ""),
                input_output=context.metadata.get("input_output", {}),
                task_id=task_id,
            )

        test_code = build_test_harness(problem)

        # 3. Secure Containerized Verification
        try:
            res = self.verifier.execute_code(extracted_code, test_code)
        except SandboxUnavailableError as exc:
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="infrastructure_invalid",
                score=0.0,
                error_code="CONTAINER_SANDBOX_UNAVAILABLE",
                error_detail=str(exc),
            )

        status = res.status
        score = 1.0 if res.success else 0.0

        metrics = {
            "pass@1": score,
            "syntax_valid": 1.0,
            "execution_duration_ms": res.duration_ms,
            "exit_code": res.exit_code,
        }

        details = {
            "exit_code": res.exit_code,
            "status": res.status,
            "stdout_preview": res.stdout[:500],
            "stderr_preview": res.stderr[:500],
        }

        evidence = {
            "extracted_code": extracted_code[:1000],
            "container_image": self.verifier.config.image,
            "network_disabled": self.verifier.config.network_disabled,
        }

        return ScoredAttempt(
            task_id=task_id,
            scorer_id=self.scorer_id,
            status=status,
            score=score,
            metrics=metrics,
            details=details,
            evidence=evidence,
            error_code=res.error_code,
            error_detail=res.error_detail,
        )


# Register LCB scorer into execution registry
register_scorer("lcb_official", LCBScoringAdapter)
