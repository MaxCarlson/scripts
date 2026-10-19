"""Coordinator verifier for py-grep-smoke fixture.

Invoked as:
    python check.py <FROZEN_WORKSPACE>

Exit codes:
    0: pass (solution is correct)
    1: incorrect implementation
    2: verifier infrastructure failure
"""

import importlib.util
import json
import os
from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <FROZEN_WORKSPACE>", file=sys.stderr)
        sys.exit(2)

    workspace_arg = sys.argv[1]
    try:
        workspace_path = Path(workspace_arg).resolve()
        if not workspace_path.is_dir():
            print(f"Infrastructure failure: workspace '{workspace_arg}' is not a directory", file=sys.stderr)
            sys.exit(2)
    except Exception as exc:
        print(f"Infrastructure failure: error resolving workspace path: {exc}", file=sys.stderr)
        sys.exit(2)

    grep_file = workspace_path / "grep.py"
    if not grep_file.is_file():
        print(f"Incorrect implementation: grep.py not found in {workspace_path}", file=sys.stderr)
        sys.exit(1)

    try:
        spec = importlib.util.spec_from_file_location("worker_grep", grep_file)
        if spec is None or spec.loader is None:
            print("Incorrect implementation: unable to create module spec for grep.py", file=sys.stderr)
            sys.exit(1)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except BaseException as exc:  # Submitted module termination is an incorrect solution.
        print(f"Incorrect implementation: error loading grep.py: {exc}", file=sys.stderr)
        sys.exit(1)

    if not hasattr(mod, "grep") or not callable(mod.grep):
        print("Incorrect implementation: grep function missing or not callable", file=sys.stderr)
        sys.exit(1)

    grep_fn = mod.grep
    checks_completed = 0

    def run_case(
        name: str,
        pattern: str,
        lines: list[str],
        expected: list[str],
        ignore_case: bool = False,
        pass_kwarg: bool = True,
    ) -> None:
        nonlocal checks_completed
        lines_copy = list(lines)
        try:
            if pass_kwarg:
                actual = grep_fn(pattern, lines, ignore_case=ignore_case)
            else:
                actual = grep_fn(pattern, lines)
        except BaseException as exc:  # Includes submitted SystemExit/KeyboardInterrupt.
            print(f"Incorrect implementation: case '{name}' raised exception: {exc}", file=sys.stderr)
            sys.exit(1)

        if not isinstance(actual, list):
            print(
                f"Incorrect implementation: case '{name}' returned {type(actual).__name__}, expected list",
                file=sys.stderr,
            )
            sys.exit(1)

        if lines != lines_copy:
            print(f"Incorrect implementation: case '{name}' mutated the input lines", file=sys.stderr)
            sys.exit(1)

        if actual != expected:
            print(
                f"Incorrect implementation: case '{name}' failed.\n"
                f"  Pattern: {pattern!r}\n"
                f"  ignore_case: {ignore_case!r}\n"
                f"  Expected: {expected!r}\n"
                f"  Actual:   {actual!r}",
                file=sys.stderr,
            )
            sys.exit(1)

        checks_completed += 1

    # 1. Basic match and no match
    run_case(
        "basic_match",
        "apple",
        ["pineapple", "apple", "banana", "crabapple"],
        ["pineapple", "apple", "crabapple"],
    )
    run_case("no_match", "cherry", ["apple", "banana", "orange"], [])

    # 2. Case sensitivity and defaults
    run_case(
        "default_case_sensitive",
        "foo",
        ["foo", "Foo", "FOO", "barfoobaz", "barFoobaz"],
        ["foo", "barfoobaz"],
        pass_kwarg=False,
    )
    run_case(
        "explicit_case_sensitive",
        "Foo",
        ["foo", "Foo", "FOO", "barfoobaz", "barFoobaz"],
        ["Foo", "barFoobaz"],
        ignore_case=False,
    )
    run_case(
        "case_insensitive",
        "foo",
        ["foo", "Foo", "FOO", "barfoobaz", "barFoobaz"],
        ["foo", "Foo", "FOO", "barfoobaz", "barFoobaz"],
        ignore_case=True,
    )
    run_case(
        "case_insensitive_pattern_upper",
        "FOO",
        ["foo", "Foo", "FOO", "barfoobaz", "nomatch"],
        ["foo", "Foo", "FOO", "barfoobaz"],
        ignore_case=True,
    )

    # 3. Order preservation and duplicates
    run_case(
        "duplicates_and_order",
        "match",
        ["match 1", "other", "match 2", "match 1", "match 2"],
        ["match 1", "match 2", "match 1", "match 2"],
    )

    # 4. Empty strings
    run_case("empty_pattern", "", ["first", "", "second"], ["first", "", "second"])
    run_case("empty_lines", "something", [], [])
    run_case("empty_pattern_empty_lines", "", [], [])

    # 5. Literal substring match (no regex)
    run_case("literal_dot", "a.b", ["a.b", "axb", "a1b", "a.b.c"], ["a.b", "a.b.c"])
    run_case("literal_star", "x*", ["x*", "xxxx", "x", "x*y"], ["x*", "x*y"])
    run_case("literal_brackets", "[0-9]", ["[0-9]", "5", "a[0-9]b"], ["[0-9]", "a[0-9]b"])
    run_case("literal_caret_dollar", "^test$", ["^test$", "test", "prefix ^test$ suffix"], ["^test$", "prefix ^test$ suffix"])
    run_case("literal_backslash", "a\\b", ["a\\b", "ab"], ["a\\b"])
    run_case("literal_question", "a?", ["a?", "a", "aa"], ["a?"])
    run_case("literal_plus", "a+", ["a+", "a", "aa"], ["a+"])
    run_case("literal_parens", "(a)", ["(a)", "a"], ["(a)"])

    # 6. Unicode handling
    run_case("unicode_exact", "café", ["café", "cafe", "CAFÉ"], ["café"])
    run_case("unicode_case_insensitive", "café", ["café", "cafe", "CAFÉ"], ["café", "CAFÉ"], ignore_case=True)
    run_case(
        "unicode_umlaut",
        "ümlaut",
        ["Mit Ümlaut", "Ohne umlaut", "mit ümlaut"],
        ["Mit Ümlaut", "mit ümlaut"],
        ignore_case=True,
    )
    run_case(
        "unicode_symbols",
        "λ-calculus",
        ["learn λ-calculus today", "calculus"],
        ["learn λ-calculus today"],
    )

    # A zero process exit can come from worker code. Emit positive evidence only
    # after every assertion; stdout is diagnostic and is never a pass credential.
    completion_path = os.environ.get("AGENT_BENCH_COMPLETION_PATH")
    if completion_path:
        Path(completion_path).write_text(json.dumps({
            "nonce": os.environ["AGENT_BENCH_VERIFICATION_NONCE"],
            "status": "passed", "checks_completed": checks_completed,
        }), encoding="utf-8")
    print("PASS: all grep tests passed successfully", file=sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
