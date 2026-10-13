# Stage 4 follow-up: Claude and Gemini repository instruction parity

## Authorization and sequence

The user explicitly requested Claude parity before the previously planned Codex stages 2 and 3 were complete, and later requested repository Gemini routing cleanup. The user has since run the dotfiles symlink setup. This pass verifies existing global Codex and Claude links read-only; it does not change dotfiles or Claude/Gemini settings.

## Scope

- Confirm the active Codex and Claude global symlinks resolve to their dotfiles sources and contain aligned policy, retaining Claude-specific tool-permission wording.
- Make the scripts root `CLAUDE.md` route directly to the repository's canonical `AGENTS.md` without a duplicate reminder.
- Remove stale, conflicting Claude-only policy from the ignored `scripts/.claude/CLAUDE.md` local source while leaving its settings and other local state alone.
- Make the scripts root `GEMINI.md` import the canonical root `AGENTS.md` and use Gemini's documented `@file.md` import syntax.
- Leave global Gemini instruction verification for a separate pass.

## Verification

- Confirm Claude's official instruction-loading rules and inspect the source-selection setup.
- Check the updated instruction sources and run `git diff --check` with submodule recursion disabled in `scripts/`.
- No code tests are needed for this documentation-only stage.
- Verify the Gemini import against the official Gemini CLI context-file documentation; no Gemini runtime session is available for this pass.

## Progress and result

- `C:\Users\mcarls\.codex\AGENTS.md` resolves to `dotfiles/symlinked/llms/codex/AGENTS.md`; `C:\Users\mcarls\.claude\CLAUDE.md` resolves to `dotfiles/symlinked/llms/claude/CLAUDE.md`. Both targets exist and the contents have aligned policy, with a Claude-specific tool-permission reminder. The dotfiles Git checkout could not be inspected because filesystem access was denied.
- The scripts root `CLAUDE.md` now contains only `@AGENTS.md`. Its former hybrid reminder was redundant with the conditional workflow route in `REPO_LLM_INSTRUCTIONS.md` and the referenced hybrid workflow document.
- The ignored local `scripts/.claude/CLAUDE.md` now contains a block-comment pointer to the root instructions. Claude strips block-level HTML comments before loading them, so this local file adds no competing rules or context tokens.
- The root `GEMINI.md` now imports the canonical `AGENTS.md` using Gemini CLI's documented import syntax. The global and scripts-specific Gemini dotfiles sources remain untouched for the other agent.
- A fresh `codex exec` runtime check could not start because the sandbox denied access to `C:\Users\mcarls\.codex\state_5.sqlite` and its temporary arg0 directory. No Claude runtime session was run.
- Staged and unstaged `git diff --check` checks passed in `scripts/`. No code tests are needed for this documentation-only stage.
- Review is pending. The local `.claude/CLAUDE.md` is ignored by Git, so only the root `CLAUDE.md` change is part of the tracked scripts diff.

## Boundary

The user has authorized publishing this work. The user's Codex and Claude symlink setup is verified by target resolution; fresh Claude and Gemini runtime context checks remain.

Last edited: 2026-10-12 21:45:53 -07:00
