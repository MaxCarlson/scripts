# LLM Onboarding Guide

A concise playbook for agents working in this repo. Read once, then follow for every task.

## Core Principles
- Work from the plans: read module-specific plan/todo/guide markdowns before coding; update them after changes.
- Small, verifiable steps: implement in bite-sized increments, keep UI logic reusable (prefer termdash widgets over ad-hoc printing).
- Tests are mandatory for code changes: add/adjust tests, run affected suites, fix failures before handing off.
- Preserve user state: never stage/commit unless explicitly asked; never touch files outside this repo.

## Task Log Template
Maintain a running markdown log (per module or feature) with these sections:
- **Context**: short description of the feature/bug and related plan doc links.
- **Checklist**: checkbox items (`- [ ]` / `- [x]`) for subtasks, kept ordered by priority.
- **Decisions**: bullet list of key choices and rationale.
- **Notes/Risks**: edge cases, blockers, follow-ups.
- **Testing**: commands run and outcomes.

Example block:
```
## Feature: Lister size caching
- [x] Show item counts on collapsed dirs
- [ ] Cache folder sizes across toggles
- [ ] Expose size-calc API via termdash widget
Decisions: reuse calculate_folder_size; avoid global threads
Testing: pytest modules/file_utils/tests -q (pass)
```

## Working Loop
1) **Understand**: scan relevant PLAN/todo docs; inspect code/tests before editing.  
2) **Plan**: define 2–5 concrete subtasks; execute one at a time.  
3) **Implement**: keep UI bits portable—if a widget is useful elsewhere, build it inside `modules/termdash` and consume it from callers.  
4) **Test**: run targeted pytest suites; add tests for new behaviors; fix all failures.  
5) **Document**: update the module’s plan/backlog with what changed and what’s next.  
6) **Review Handoff**: summarize changes, list tests, and remind the user to stage/commit if desired.

## Testing Expectations
- Add unit tests for every new feature/branch edge; prefer isolated tests over integration when possible.
- Run the narrowest relevant suites (e.g., `pytest modules/file_utils/tests -q`), then broader if warranted.
- If tests can’t be run, say why and how to run them.

## Versioning & CLI Flags
- Follow SemVer in `pyproject.toml`/`setup.py` whenever code changes.  
- All new CLI args must be `-x/--long` with sensible defaults; keep compatibility.

## UI/UX Reuse (termdash-first)
- Build reusable widgets/components in `modules/termdash`; avoid one-off UI code in downstream modules.
- Keep color/status conventions consistent across dashboards (logs, progress, hotkeys).

## Communication
- Be concise; include file paths when describing changes.  
- After delivering, prompt the user to stage/commit if they want.  
- If unexpected repo state appears, stop and ask before altering anything.
