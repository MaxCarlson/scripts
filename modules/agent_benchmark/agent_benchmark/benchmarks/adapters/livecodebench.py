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


def build_test_harness(problem: LCBProblem) -> str:
    """
    Generate the authentic Python test evaluation harness for a LiveCodeBench problem.

    Supports both standard_input (I/O) and functional (call-based) problems.
    Enforces anti-bypass canary verification so premature exit (e.g. sys.exit(0))
    cannot register as a passing score.
    """
    io_data = problem.input_output
    inputs = io_data.get("inputs", [])
    outputs = io_data.get("outputs", [])
    fn_name = io_data.get("fn_name")

    # Serialize test data cleanly into harness
    inputs_json = json.dumps(inputs)
    outputs_json = json.dumps(outputs)

    if fn_name:
        # Call-based / functional problem harness
        harness = f"""
# --- LiveCodeBench Call-Based Test Harness ---
import json
import sys
from decimal import Decimal

_INPUTS = {inputs_json}
_OUTPUTS = {outputs_json}
_FN_NAME = {json.dumps(fn_name)}

def _run_tests():
    total_tests = len(_INPUTS)
    if total_tests == 0:
        print("{CANARY_FAILED_MARKER}: No test cases provided")
        sys.exit(1)

    # Locate solution function or class
    target_fn = None
    if "Solution" in globals():
        sol_inst = globals()["Solution"]()
        target_fn = getattr(sol_inst, _FN_NAME, None)
    if target_fn is None:
        target_fn = globals().get(_FN_NAME)

    if target_fn is None:
        print(f"{CANARY_FAILED_MARKER}: Function '{{_FN_NAME}}' not found in candidate solution")
        sys.exit(1)

    passed_count = 0
    for idx, (inp_raw, exp_raw) in enumerate(zip(_INPUTS, _OUTPUTS)):
        try:
            if isinstance(inp_raw, str):
                inp_args = [json.loads(line) for line in inp_raw.splitlines() if line.strip()]
            elif isinstance(inp_raw, list):
                inp_args = inp_raw
            else:
                inp_args = [inp_raw]
        except Exception as exc:
            print(f"{CANARY_FAILED_MARKER}: Failed to decode input for test {{idx}}: {{exc}}")
            sys.exit(1)

        try:
            exp_val = json.loads(exp_raw) if isinstance(exp_raw, str) else exp_raw
        except Exception:
            exp_val = exp_raw

        try:
            result = target_fn(*inp_args)
            if isinstance(result, tuple):
                result = list(result)
        except SystemExit:
            print(f"{CANARY_FAILED_MARKER}: Premature clean exit during test {{idx}}")
            sys.exit(1)
        except Exception as exc:
            print(f"{CANARY_FAILED_MARKER}: Runtime exception during test {{idx}}: {{exc}}")
            sys.exit(1)

        if result == exp_val:
            passed_count += 1
        else:
            print(f"{CANARY_FAILED_MARKER}: Test {{idx}} failed: expected {{exp_val!r}}, got {{result!r}}")
            sys.exit(1)

    if passed_count == total_tests:
        print(f"{CANARY_SUCCESS_MARKER}: {{passed_count}}/{{total_tests}}")
        sys.exit(0)
    else:
        print(f"{CANARY_FAILED_MARKER}: Only {{passed_count}}/{{total_tests}} passed")
        sys.exit(1)

if __name__ == '__main__':
    _run_tests()
"""
    else:
        # Standard input / output problem harness
        harness = f"""
# --- LiveCodeBench Standard Input/Output Test Harness ---
import io
import json
import sys
from decimal import Decimal

_INPUTS = {inputs_json}
_OUTPUTS = {outputs_json}

def _convert_decimals(line):
    try:
        return True, [Decimal(elem) for elem in line.split()]
    except Exception:
        return False, []

def _run_tests():
    total_tests = len(_INPUTS)
    if total_tests == 0:
        print("{CANARY_FAILED_MARKER}: No test cases provided")
        sys.exit(1)

    target_fn = globals().get("wrapped_function")
    if target_fn is None:
        print("{CANARY_FAILED_MARKER}: wrapped_function entrypoint not found")
        sys.exit(1)

    passed_count = 0
    for idx, (inp_val, exp_val) in enumerate(zip(_INPUTS, _OUTPUTS)):
        inp_str = str(inp_val) if not isinstance(inp_val, str) else inp_val
        exp_str = str(exp_val) if not isinstance(exp_val, str) else exp_val

        old_stdin = sys.stdin
        old_stdout = sys.stdout
        sys.stdin = io.StringIO(inp_str + ("\\n" if not inp_str.endswith("\\n") else ""))
        sys.stdout = io.StringIO()

        premature_exit = False
        try:
            target_fn()
        except SystemExit:
            premature_exit = True
        except Exception as exc:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            print(f"{CANARY_FAILED_MARKER}: Runtime error during test {{idx}}: {{exc}}")
            sys.exit(1)
        finally:
            captured = sys.stdout.getvalue()
            sys.stdin = old_stdin
            sys.stdout = old_stdout

        actual_lines = [l.strip() for l in captured.strip().splitlines() if l.strip()]
        exp_lines = [l.strip() for l in exp_str.strip().splitlines() if l.strip()]

        if premature_exit and not actual_lines:
            print(f"{CANARY_FAILED_MARKER}: Premature clean exit during test {{idx}} without output")
            sys.exit(1)

        if len(actual_lines) != len(exp_lines):
            print(f"{CANARY_FAILED_MARKER}: Test {{idx}} line count mismatch: expected {{len(exp_lines)}}, got {{len(actual_lines)}}")
            sys.exit(1)

        match = True
        for l_act, l_exp in zip(actual_lines, exp_lines):
            if l_act == l_exp:
                continue
            ok_act, dec_act = _convert_decimals(l_act)
            ok_exp, dec_exp = _convert_decimals(l_exp)
            if ok_act and ok_exp and dec_act == dec_exp:
                continue
            match = False
            break

        if match:
            passed_count += 1
        else:
            print(f"{CANARY_FAILED_MARKER}: Test {{idx}} wrong answer: expected {{exp_lines!r}}, got {{actual_lines!r}}")
            sys.exit(1)

    if passed_count == total_tests:
        print(f"{CANARY_SUCCESS_MARKER}: {{passed_count}}/{{total_tests}}")
        sys.exit(0)
    else:
        print(f"{CANARY_FAILED_MARKER}: Only {{passed_count}}/{{total_tests}} passed")
        sys.exit(1)

if __name__ == '__main__':
    _run_tests()
"""
    return harness


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

        is_functional = bool(io_data.get("fn_name"))
        prepared_code = extracted_code
        if not is_functional:
            # Wrap standard I/O solution into wrapped_function
            cleaned = clean_if_name(extracted_code)
            prepared_code = wrap_code_in_function(cleaned)

        test_code = build_test_harness(problem)

        # 3. Secure Containerized Verification
        try:
            res = self.verifier.execute_code(prepared_code, test_code)
        except SandboxUnavailableError as exc:
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="infrastructure_invalid",
                score=0.0,
                error_code="CONTAINER_SANDBOX_UNAVAILABLE",
                error_detail=str(exc),
            )

        # Enforce canary receipt verification
        canary_present = CANARY_SUCCESS_MARKER in res.stdout
        failed_marker_present = CANARY_FAILED_MARKER in res.stdout

        if res.success and canary_present and res.exit_code == 0:
            status = "passed"
            score = 1.0
            error_code = None
            error_detail = None
        else:
            status = "failed"
            score = 0.0
            if failed_marker_present:
                error_code = "TEST_FAILED"
                error_detail = "Verification harness reported test failure"
            elif res.exit_code == 0 and not canary_present:
                error_code = "PREMATURE_EXIT"
                error_detail = "Process exited with code 0 without reaching test completion receipt"
            elif res.status == "timed_out":
                status = "timed_out"
                error_code = "TIMED_OUT"
                error_detail = "Execution timed out in container sandbox"
            else:
                error_code = res.error_code or "EXECUTION_ERROR"
                error_detail = res.error_detail or "Execution failed inside container sandbox"

        metrics = {
            "pass@1": score,
            "syntax_valid": 1.0,
            "execution_duration_ms": res.duration_ms,
            "exit_code": res.exit_code,
        }

        details = {
            "exit_code": res.exit_code,
            "status": status,
            "canary_verified": canary_present,
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
            error_code=error_code,
            error_detail=error_detail,
        )


# Register LCB scorer into execution registry
register_scorer("lcb_official", LCBScoringAdapter)
