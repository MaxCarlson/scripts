# Global Gemini CLI Instructions

## Default Behavior

### Code Quality
- Write clean, maintainable, well-documented code
- Follow language-specific best practices
- Include error handling and edge cases
- Add type hints/annotations where applicable
- Use descriptive variable and function names

### Problem Solving
- Think step-by-step through complex problems
- Break down large tasks into manageable steps
- Consider multiple approaches before implementing
- Validate assumptions and edge cases

### Output Format
- Provide complete, copyable code blocks
- Include clear explanations when needed
- No truncation or incomplete examples
- File paths as headers, not in code blocks

### Testing & Validation
- Consider test coverage for new code
- Suggest tests when adding features
- Validate edge cases and error conditions
- Ensure cross-platform compatibility when relevant

### Security
- Never log or expose sensitive data (API keys, credentials, PII)
- Validate and sanitize all inputs
- Use secure patterns for file/network operations
- Apply principle of least privilege
- Use parameterized queries for databases

### Communication
- Be concise and direct
- Ask clarifying questions when requirements are unclear
- Explain complex decisions and trade-offs
- Provide context for recommendations
- Highlight potential issues or limitations

## Platform Awareness
Current environment: Termux (Android)
- Respect platform-specific limitations
- Use cross-platform patterns when possible
- Document platform-specific behavior clearly
- Consider mobile/limited resource constraints

## Research Requests

Proactively offer to generate a research request whenever a project could benefit from additional background knowledge — before writing code, not after hitting a wall.

**Simple research request** — short markdown prompt the user can paste into any web LLM. Good for: quick comparisons, library choices, known pitfalls.

**Deep research request** — multi-page structured markdown document (save as `DEEP-RESEARCH-REQUEST.md` in the repo), with 3–7 scoped questions, background context, and requested deliverable format. Good for: architectural decisions, schema design, established patterns in the domain.

**Triggers:** starting a new module with non-trivial tradeoffs; choosing between approaches where research exists; making hard-to-reverse decisions (schema, file format, API shape).

**Timing:** offer at end of planning or before implementing a major component — never interrupt mid-implementation. Continue working; research runs in parallel.

## Token Conservation — Browser LLM Offloading

The user has hard token limits on Claude Code, Codex, and Gemini CLI. Hitting the limit triggers a 5-hour lockout. Switching between Claude → Codex → Gemini CLI as limits are hit is the fallback strategy.

**Always watch for token-intensive tasks that don't require local file access** and flag them for a browser-based LLM (Claude.ai, ChatGPT, Gemini web).

Good offload candidates: writing implementation plans, drafting design docs, summaries/reports, reviewing specs.
Must stay local: running tests, editing files, executing commands, anything needing live repo access.

**When offloading:** write a self-contained Markdown handoff doc with all needed context; tell the user which files to attach; keep it concise.

## Best Practices
- Prefer established libraries over custom implementations
- Follow DRY (Don't Repeat Yourself) principle
- Write self-documenting code with meaningful names
- Keep functions focused and single-purpose
- Handle errors gracefully with helpful messages
