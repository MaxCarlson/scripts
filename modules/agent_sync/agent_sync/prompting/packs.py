"""Task-specific prompt packs for delegated LLM workers."""

from agent_sync.tasks import DelegationTask


TASK_INSTRUCTIONS = {
    "research": "Research the topic and return a concise, source-aware synthesis with uncertainties and recommendations.",
    "summarize": "Summarize the provided material. Preserve key decisions, constraints, commands, and open questions.",
    "extract": "Extract structured facts, requirements, APIs, commands, and constraints from the provided material.",
    "review": "Review the provided plan, code, or reasoning. Find bugs, missing cases, risks, and better alternatives.",
    "verify": "Independently verify the claim or implementation. Be adversarial, evidence-driven, and explicit about confidence.",
    "plan": "Produce an implementation plan with ordered tasks, affected files, tests, risks, and validation commands.",
    "classify": "Classify the input into the requested categories. Return only the requested structured output.",
    "brainstorm": "Generate diverse candidate approaches, then rank them by practicality, risk, and expected value.",
    "log-triage": "Analyze logs/errors. Identify likely root cause, evidence, fixes, and next diagnostic commands.",
    "custom": "Complete the requested task exactly as specified by the primary agent.",
}

CONTEXT_LEVELS = {
    "brief": "Use minimal context. Return only the result, major caveats, and confidence.",
    "standard": "Use balanced context. Return result, reasoning summary, caveats, validation steps, and confidence.",
    "full": "Use full context. Return detailed analysis, alternatives considered, caveats, validation steps, and confidence.",
}


def build_delegation_prompt(task: DelegationTask, *, primary_agent: str = "primary-agent") -> str:
    """Build a deterministic prompt for a delegated worker."""
    task.validate()
    title = task.title or f"{task.task_type} task"
    high_stakes = "yes" if task.high_stakes else "no"
    readonly = "yes" if task.readonly else "no"
    source = str(task.source_path) if task.source_path else "inline prompt"
    return f"""# agent_sync Delegated Task Packet

## Role
You are a delegated LLM worker called by {primary_agent}. Your job is to complete a bounded subtask and return output that the primary agent can safely ingest.

## Task Metadata
- Title: {title}
- Task type: {task.task_type}
- Context level: {task.context_level}
- High stakes: {high_stakes}
- Read-only: {readonly}
- Repository root: {task.repo_root}
- Source: {source}

## Task Instructions
{TASK_INSTRUCTIONS[task.task_type]}

## Context Compression Contract
{CONTEXT_LEVELS[task.context_level]}

## Output Contract
Return Markdown with exactly these headings:

1. `## Result`
2. `## Key Findings`
3. `## Evidence Or Rationale`
4. `## Risks And Gaps`
5. `## Recommended Next Actions`
6. `## Confidence`

Rules:
- Do not claim you changed files unless you actually changed files.
- If you are unsure, say so explicitly.
- Do not include hidden chain-of-thought. Provide concise rationale and evidence instead.
- Prefer concrete file paths, commands, and test names when relevant.
- If the task is high-stakes, include at least one adversarial failure mode.

## Primary Prompt
{task.prompt.rstrip()}
"""
