# AGENTS.md

> Vendor-neutral AI coding agent instructions. Compatible with: OpenAI Codex, Claude Code, Cursor, Cline, GitHub Copilot.

<project>
name: [PROJECT_NAME]
language: Python 3.11+
type: [cli-tool | library | web-service | monorepo]
</project>

<stack>
## Runtime
- Python 3.11+ (primary)
- Rust via PyO3/maturin (performance-critical extensions)

## Platforms
- Linux (WSL2 Ubuntu 22.04+)
- Windows 11 (PowerShell 7, UTF-8)
- Android (Termux, proot-distro)

## Dependencies
- Package manager: uv (pip fallback on Termux)
- Virtual env: .venv/ (uv venv)
- Lock file: uv.lock
</stack>

<commands>
## Setup
```bash
uv venv && source .venv/bin/activate  # Linux/macOS
uv venv && .venv\Scripts\Activate.ps1  # Windows
uv sync
```

## Build
```bash
uv run black .
uv run ruff check --fix .
uv run mypy src/ --strict
```

## Test
```bash
uv run pytest tests/ -v --tb=short --cov=src --cov-report=term-missing
```

## Single test file
```bash
uv run pytest tests/<module_name>_test.py -v
```
</commands>

<code_style>
## Python Conventions
- Type hints: mandatory on all public functions and methods
- Docstrings: Google style, imperative first line
- Imports: stdlib | third-party | local (blank line separated, alphabetized)
- Paths: pathlib.Path (never os.path)
- Strings: f-strings (never .format() or %)
- I/O: explicit encoding="utf-8"
- Logging: logging module (never print() for operational output)

## CLI Arguments
- Format: `-a/--argument-name` (short and long REQUIRED)
- Parser: argparse with subcommands where appropriate
- Help: every argument has help= text

## File Naming
- Source: `src/<package>/<module>.py`
- Tests: `tests/<module_name>_test.py` (NOT test_<module>.py)
- Config: pyproject.toml (no setup.py, setup.cfg)

## Git
- Commits: imperative mood, 50 char subject, blank line, body
- Branches: feature/<name>, fix/<name>, refactor/<name>
</code_style>

<architecture>
## Module Structure
```
src/
├── <package>/
│   ├── __init__.py      # __version__, public API exports
│   ├── cli.py           # argparse entry point
│   ├── core.py          # business logic
│   └── utils.py         # shared utilities
tests/
├── conftest.py          # pytest fixtures
├── cli_test.py
├── core_test.py
└── utils_test.py
```

## Cross-Platform
- Use existing cross_platform.py module for OS detection
- Termux: /data/data/com.termux/files/home paths
- WSL2: prefer /home/ over /mnt/c/ for performance
- Windows: handle backslash paths via pathlib
</architecture>

<validation>
Before marking any task complete:
1. [ ] All new code has type hints
2. [ ] Tests exist in tests/<module>_test.py
3. [ ] `uv run pytest` passes
4. [ ] `uv run ruff check .` passes (no errors)
5. [ ] `uv run mypy src/ --strict` passes
6. [ ] No hardcoded paths; use pathlib and config
7. [ ] Docstrings on all public functions
</validation>

<constraints>
## NEVER
- Use os.path (use pathlib)
- Use print() for logging (use logging module)
- Hardcode file paths
- Skip type hints on public APIs
- Name test files test_*.py (use *_test.py)
- Modify files outside project root without confirmation
- Run destructive commands (rm -rf, format) without confirmation
- Commit without showing diff

## ALWAYS
- Run tests before claiming completion
- Use virtual environment (.venv/)
- Preserve existing code style when editing
- Ask for clarification on ambiguous requirements
</constraints>

<research_delegation>
## Trigger Conditions
Delegate to external deep research when:
- Architecture decision with >3 viable approaches
- Security or compliance implications
- Performance optimization requiring benchmarks
- Technology/vendor selection
- Information potentially outdated (check recency)
- Confidence below 80% on technical recommendation
- Third failed attempt at same problem

## Output Format
When triggered, STOP and output:
```
═══════════════════════════════════════════════════════════════
RESEARCH DELEGATION REQUIRED
═══════════════════════════════════════════════════════════════
Topic: [2-5 word summary]
Question: [Specific, answerable question]
Context: 
  - Project: [relevant project details]
  - Constraint: [key constraints]
  - Already tried: [failed approaches if any]
Suggested tools: ChatGPT Deep Research | Gemini Deep Research | Perplexity Pro
═══════════════════════════════════════════════════════════════
```

## Post-Research
User will provide research results. Integrate findings and continue.
</research_delegation>

<pr_guidelines>
## Pull Request Checklist
- Title: imperative, <50 chars
- Description: what, why, how
- Tests: added/updated for changes
- Docs: updated if API changed
- Breaking: labeled if breaking change
</pr_guidelines>
