"""Official LiveCodeBench benchmark adapter, code extractor, and sandboxed evaluator."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from decimal import Decimal
import json
import re
from typing import Any

from ...execution.container_verify import ContainerVerifier, SandboxUnavailableError
from ...execution.contract import BackendAttempt, ScoredAttempt, TaskContext
from ...execution.registry import register_scorer


CANARY_SUCCESS_MARKER = "__LCB_VERIFICATION_SUCCESS__"
CANARY_FAILED_MARKER = "__LCB_VERIFICATION_FAILED__"


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


def clean_if_name(code: str) -> str:
    """Strip or inline `if __name__ == '__main__':` block to allow clean function wrapping."""
    try:
        tree = ast.parse(code)
        if tree.body and isinstance(tree.body[-1], ast.If):
            last_block = tree.body[-1]
            condition_text = ast.unparse(last_block.test).strip()
            if condition_text in ("__name__ == '__main__'", '__name__ == "__main__"'):
                return ast.unparse(tree.body[:-1]) + "\n" + ast.unparse(last_block.body)
    except Exception:
        pass
    return code


def wrap_code_in_function(code: str, fn_name: str = "wrapped_function") -> str:
    """Wrap standard I/O code into a callable function to execute against multiple inputs."""
    try:
        tree = ast.parse(code)
        import_stmts = []
        other_stmts = []
        for stmt in tree.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                import_stmts.append(stmt)
            else:
                other_stmts.append(stmt)
        fn_def = ast.FunctionDef(
            name=fn_name,
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=other_stmts or [ast.Pass()],
            decorator_list=[],
            lineno=-1,
        )
        imports_code = ast.unparse(import_stmts) if import_stmts else ""
        return imports_code + "\n\n" + ast.unparse(fn_def)
    except Exception:
        return code


def convert_line_to_decimals(line: str) -> tuple[bool, list[Decimal]]:
    """Convert line of whitespace-separated tokens into Decimals if possible."""
    try:
        decimal_line = [Decimal(elem) for elem in line.split()]
        return True, decimal_line
    except Exception:
        return False, []


def format_lcb_prompt(problem: LCBProblem) -> str:
    """Format official LiveCodeBench prompt matching upstream PromptConstants."""
    prompt = f"### Question:\n{problem.prompt}\n\n"
    if problem.starter_code:
        prompt += "### Format: You will use the following starter code to write the solution to the problem and enclose your code within delimiters.\n"
        prompt += f"```python\n{problem.starter_code}\n```\n\n"
    else:
        prompt += "### Format: Read the inputs from stdin solve the problem and write the answer to stdout (do not directly test on the sample inputs). Enclose your code within delimiters as follows. Ensure that when the python program runs, it reads the inputs, runs the algorithm and writes output to STDOUT.\n"
        prompt += "```python\n# YOUR CODE HERE\n```\n\n"
    prompt += "### Answer: (use the provided format with backticks)\n\n"
    return prompt


def _stdio_equal(actual: str, expected: str) -> bool:
    """Line-wise comparison with whitespace stripping and Decimal-equivalence (upstream semantics)."""
    act = [ln.strip() for ln in actual.strip().splitlines() if ln.strip()]
    exp = [ln.strip() for ln in expected.strip().splitlines() if ln.strip()]
    if len(act) != len(exp):
        return False
    for a, e in zip(act, exp):
        if a == e:
            continue
        ok_a, dec_a = convert_line_to_decimals(a)
        ok_e, dec_e = convert_line_to_decimals(e)
        if ok_a and ok_e and dec_a == dec_e:
            continue
        return False
    return True


@dataclass(frozen=True)
class HostVerdict:
    """Pass/fail verdict computed exclusively on the trusted host from raw execution evidence."""

    status: str  # "passed" | "failed" | "timed_out" | "infrastructure_invalid"
    passed_tests: int
    total_tests: int
    error_code: str | None = None
    error_detail: str | None = None
    duration_ms: float = 0.0
    exit_code: int = 0
    stdout_preview: str = ""
    stderr_preview: str = ""


def evaluate_problem(verifier: ContainerVerifier, code: str, problem: LCBProblem) -> HostVerdict:
    """
    Host-side orchestration: run the candidate once per test input in isolated containers and
    compare returned results with private expected outputs held only in host memory.
    Short-circuits on the first failing test. Raises SandboxUnavailableError if the sandbox is down.
    """
    io_data = problem.input_output or {}
    inputs = list(io_data.get("inputs", []))
    outputs = list(io_data.get("outputs", []))
    fn_name = io_data.get("fn_name")
    total = len(inputs)

    if total == 0 or len(outputs) == 0:
        return HostVerdict("infrastructure_invalid", 0, 0, "MISSING_BENCHMARK_DATA", "No test cases provided")
    if len(inputs) != len(outputs):
        return HostVerdict(
            "infrastructure_invalid", 0, total, "CORRUPT_BENCHMARK_DATA",
            f"inputs/outputs length mismatch ({len(inputs)} vs {len(outputs)})",
        )

    passed = 0
    total_ms = 0.0
    last_exit = 0
    last_out = ""
    last_err = ""

    def fail(code: str, detail: str, status: str = "failed") -> HostVerdict:
        return HostVerdict(status, passed, total, code, detail, total_ms, last_exit, last_out[:500], last_err[:500])

    for idx, (inp_raw, exp_raw) in enumerate(zip(inputs, outputs)):
        if fn_name:
            try:
                if isinstance(inp_raw, str):
                    args = [json.loads(ln) for ln in inp_raw.splitlines() if ln.strip()]
                elif isinstance(inp_raw, list):
                    args = inp_raw
                else:
                    args = [inp_raw]
                stdin_text = json.dumps(args)
            except Exception as exc:
                return HostVerdict(
                    "infrastructure_invalid", passed, total, "CORRUPT_BENCHMARK_DATA",
                    f"Undecodable input for test {idx}: {exc}",
                )
        else:
            stdin_text = inp_raw if isinstance(inp_raw, str) else str(inp_raw)
            if not stdin_text.endswith("\n"):
                stdin_text += "\n"

        res = verifier.run_candidate(code, stdin_text, fn_name=fn_name)
        total_ms += res.duration_ms
        last_exit, last_out, last_err = res.exit_code, res.stdout, res.stderr

        if res.status == "error":
            return HostVerdict(
                "infrastructure_invalid", passed, total,
                res.error_code or "VERIFIER_SANDBOX_ERROR", res.error_detail or "Sandbox execution error",
                total_ms, last_exit, last_out[:500], last_err[:500],
            )
        if res.status == "timed_out":
            return fail("TIMED_OUT", f"Test {idx} timed out in container sandbox", status="timed_out")

        if fn_name:
            lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
            record: Any = None
            if lines:
                try:
                    record = json.loads(lines[-1])
                except Exception:
                    record = None
            if not isinstance(record, dict) or ("result" not in record and "error" not in record):
                if res.exit_code == 0:
                    return fail("PREMATURE_EXIT", f"Test {idx}: candidate ended without a verified result record")
                return fail("RUNTIME_ERROR", f"Test {idx}: candidate crashed (exit {res.exit_code})")
            if "error" in record:
                err = str(record["error"])
                if err == "premature_exit":
                    return fail("PREMATURE_EXIT", f"Test {idx}: candidate called exit before returning")
                return fail("RUNTIME_ERROR", f"Test {idx}: {err}")
            try:
                exp_val = json.loads(exp_raw) if isinstance(exp_raw, str) else exp_raw
            except Exception:
                exp_val = exp_raw
            if record["result"] != exp_val:
                return fail("WRONG_ANSWER", f"Wrong answer on test {idx}")
        else:
            if res.exit_code != 0:
                return fail("RUNTIME_ERROR", f"Test {idx}: candidate exited with code {res.exit_code}")
            exp_str = exp_raw if isinstance(exp_raw, str) else str(exp_raw)
            if not res.stdout.strip() and exp_str.strip():
                return fail("PREMATURE_EXIT", f"Test {idx}: candidate produced no output")
            if not _stdio_equal(res.stdout, exp_str):
                return fail("WRONG_ANSWER", f"Wrong answer on test {idx}")
        passed += 1

    return HostVerdict("passed", passed, total, None, None, total_ms, last_exit, last_out[:500], last_err[:500])

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
            raw_io = context.metadata.get("input_output", {})
            problem = LCBProblem(
                question_id=task_id,
                question_title=task_id,
                difficulty=context.metadata.get("difficulty", "medium"),
                contest_date=context.metadata.get("contest_date", ""),
                prompt=context.prompt,
                starter_code=context.metadata.get("starter_code", ""),
                input_output=dict(raw_io),
                task_id=task_id,
            )

        # Check for missing benchmark test data
        io_data = problem.input_output or {}
        inputs = io_data.get("inputs", [])
        outputs = io_data.get("outputs", [])
        if not inputs or not outputs or len(inputs) == 0 or len(outputs) == 0:
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="infrastructure_invalid",
                score=0.0,
                metrics={"pass@1": 0.0, "syntax_valid": 1.0},
                error_code="MISSING_BENCHMARK_DATA",
                error_detail="Problem has empty or missing test inputs/outputs in input_output specification",
            )

        # 3. Host-side orchestration: contestant code only ever runs inside isolated containers
        try:
            verdict = evaluate_problem(self.verifier, extracted_code, problem)
        except SandboxUnavailableError as exc:
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="infrastructure_invalid",
                score=0.0,
                error_code="CONTAINER_SANDBOX_UNAVAILABLE",
                error_detail=str(exc),
            )

        if verdict.status == "infrastructure_invalid":
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="infrastructure_invalid",
                score=0.0,
                metrics={"pass@1": 0.0, "syntax_valid": 1.0},
                error_code=verdict.error_code,
                error_detail=verdict.error_detail,
            )

        passed = verdict.status == "passed"
        status = verdict.status
        score = 1.0 if passed else 0.0
        error_code = verdict.error_code
        error_detail = verdict.error_detail

        metrics = {
            "pass@1": score,
            "syntax_valid": 1.0,
            "execution_duration_ms": verdict.duration_ms,
            "exit_code": verdict.exit_code,
        }

        details = {
            "exit_code": verdict.exit_code,
            "status": status,
            "receipt_verified": passed,
            "verification_authority": "host",
            "tests_passed": verdict.passed_tests,
            "tests_total": verdict.total_tests,
            "stdout_preview": verdict.stdout_preview,
            "stderr_preview": verdict.stderr_preview,
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
            error_code=error_code,
            error_detail=error_detail,
        )


# Register LCB scorer into execution registry
register_scorer("lcb_official", LCBScoringAdapter)
