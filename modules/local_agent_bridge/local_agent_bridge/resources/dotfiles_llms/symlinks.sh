#!/usr/bin/env sh

# Symlinks for LLM CLI configuration files and wrappers.
# This script is sourced by the main setup/symlinks.sh script, which provides:
#   - create_symlink TARGET LINK
#   - ensure_executable TARGET

echo "--- Setting up symlinks for LLM CLI configs ---"

: "${DOTFILES:=$HOME/dotfiles}"
LLMS_DIR="$DOTFILES/symlinked/llms"
MASTER_AGENTS="$LLMS_DIR/AGENTS.md"

select_agents_source() {
    local override="$1"
    if [ -s "$override" ]; then
        printf '%s\n' "$override"
    else
        printf '%s\n' "$MASTER_AGENTS"
    fi
}

# Config files
create_symlink "$LLMS_DIR/claude/settings.json" "$HOME/.claude/settings.json"
CLAUDE_SOURCE=$(select_agents_source "$LLMS_DIR/claude/CLAUDE.md")
create_symlink "$CLAUDE_SOURCE" "$HOME/.claude/CLAUDE.md"

create_symlink "$LLMS_DIR/gemini/settings.json" "$HOME/.gemini/settings.json"
create_symlink "$LLMS_DIR/gemini/GEMINI.md"     "$HOME/.gemini/GEMINI.md"

create_symlink "$LLMS_DIR/codex/config.toml"    "$HOME/.codex/config.toml"
CODEX_SOURCE=$(select_agents_source "$LLMS_DIR/codex/AGENTS.md")
create_symlink "$CODEX_SOURCE" "$HOME/.codex/AGENTS.md"

# Tiny wrapper scripts -> ~/bin
ensure_executable "$DOTFILES/symlinked/llms/scripts/claude"
ensure_executable "$DOTFILES/symlinked/llms/scripts/gemini"

create_symlink "$DOTFILES/symlinked/llms/scripts/claude" "$HOME/bin/claude"
create_symlink "$DOTFILES/symlinked/llms/scripts/gemini" "$HOME/bin/gemini"

echo "--- Symlinks for LLM CLI configs setup complete ---"
