# Research Request: [TOPIC_SLUG]

> Generated: [YYYY-MM-DD HH:MM]
> Status: PENDING | IN_PROGRESS | COMPLETED
> Priority: HIGH | MEDIUM | LOW

---

## Context

<project_context>
- Project: [project name]
- Task: [what triggered this request]
- Tech Stack: [relevant technologies]
- Constraints: [time, budget, compatibility requirements]
</project_context>

<current_state>
- What exists: [current implementation or situation]
- What's blocked: [specific blocker]
- Attempts made: [approaches already tried and why they failed]
</current_state>

---

## Research Question

### Primary Question
[Single, specific, answerable question]

### Sub-Questions
1. [Supporting question 1]
2. [Supporting question 2]
3. [Supporting question 3]

---

## Scope

<boundaries>
- Time frame: [e.g., "solutions available as of 2025"]
- Geographic: [e.g., "US-based services only" or "global"]
- Industry: [e.g., "open-source preferred" or "enterprise-grade required"]
- Budget: [e.g., "free tier must be viable" or "up to $X/month"]
</boundaries>

<exclusions>
- [Explicitly exclude approaches or technologies not viable]
- [E.g., "Exclude solutions requiring Kubernetes"]
</exclusions>

---

## Expected Output

<deliverables>
1. **Decision Matrix**: Comparison table of top 3-5 options
2. **Recommendation**: Single recommended approach with justification
3. **Trade-offs**: Explicit pros/cons for each option
4. **Implementation Notes**: Key gotchas, setup steps, or migration concerns
5. **Sources**: Links to documentation, benchmarks, or case studies
</deliverables>

<format>
Preferred output format:
- Structured markdown
- Code snippets where applicable
- Comparison tables for multi-option analysis
</format>

---

## Ready-to-Paste Prompts

### ChatGPT Deep Research

```
Research the following technical question with comprehensive analysis:

**Question**: [PRIMARY_QUESTION]

**Context**:
- Project type: [type]
- Tech stack: [stack]
- Constraints: [constraints]

**Requirements**:
1. Compare top 3-5 solutions with pros/cons
2. Provide decision matrix
3. Recommend single best option with justification
4. Include implementation considerations
5. Cite sources (documentation, benchmarks, case studies)

**Sub-questions to address**:
- [Sub-question 1]
- [Sub-question 2]
- [Sub-question 3]

Focus on solutions available as of 2025. Prioritize practical, production-ready options.
```

### Gemini Deep Research

```
Conduct deep research on:

[PRIMARY_QUESTION]

Context:
• Project: [project description]
• Stack: [tech stack]
• Constraints: [key constraints]

Deliverables needed:
1. Comparative analysis of viable solutions
2. Decision matrix (features, cost, complexity, maturity)
3. Recommended approach with reasoning
4. Implementation risks and mitigations
5. Referenced sources

Additional questions:
• [Sub-question 1]
• [Sub-question 2]
• [Sub-question 3]

Scope: 2025-current solutions, [industry/geographic constraints if any]
```

### Perplexity Pro

```
[PRIMARY_QUESTION]

Context: [One paragraph combining project, stack, constraints]

I need:
- Comparison of top options
- Clear recommendation
- Trade-offs analysis
- Implementation notes

Also address:
- [Sub-question 1]
- [Sub-question 2]
- [Sub-question 3]
```

---

## Research Results

> [Paste research findings below after completing external research]

### Summary
[High-level summary of findings]

### Decision Matrix

| Option | Pros | Cons | Complexity | Cost | Maturity |
|--------|------|------|------------|------|----------|
| [A]    |      |      |            |      |          |
| [B]    |      |      |            |      |          |
| [C]    |      |      |            |      |          |

### Recommendation
[Recommended option and justification]

### Implementation Notes
[Key considerations for implementation]

### Sources
- [Source 1]
- [Source 2]
- [Source 3]

---

## Post-Research Actions

- [ ] Review findings with team (if applicable)
- [ ] Update AGENTS.md/CLAUDE.md if architectural decision
- [ ] Create implementation ticket/task
- [ ] Archive this request to `.research-requests/completed/`
