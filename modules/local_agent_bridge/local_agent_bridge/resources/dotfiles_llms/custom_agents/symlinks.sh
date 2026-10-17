#!/usr/bin/env sh

# Symlinks for custom agent resources (agents, prompts, instructions, skills).
# This script is sourced by the main setup/symlinks.sh script, which provides:
#   - create_symlink TARGET LINK
#   - ensure_executable TARGET

echo "--- Setting up symlinks for custom agent resources ---"

: "${DOTFILES:=$HOME/dotfiles}"
CUSTOM_AGENTS_DIR="$DOTFILES/symlinked/llms/custom_agents"
CENTRAL_DIR="$HOME/.local/share/agent-abilities"

# Ensure central registry directories exist
mkdir -p "$CENTRAL_DIR/agents"
mkdir -p "$CENTRAL_DIR/prompts"
mkdir -p "$CENTRAL_DIR/instructions"
mkdir -p "$CENTRAL_DIR/skills"

# ── Symlink agents ──────────────────────────────────────────────────────────
if [ -d "$CUSTOM_AGENTS_DIR/agents" ]; then
    for agent_file in "$CUSTOM_AGENTS_DIR/agents"/*.agent.md; do
        [ -e "$agent_file" ] || continue
        basename=$(basename "$agent_file")
        create_symlink "$agent_file" "$CENTRAL_DIR/agents/$basename"
    done
fi

# ── Symlink prompts ─────────────────────────────────────────────────────────
if [ -d "$CUSTOM_AGENTS_DIR/prompts" ]; then
    for prompt_file in "$CUSTOM_AGENTS_DIR/prompts"/*.prompt.md; do
        [ -e "$prompt_file" ] || continue
        basename=$(basename "$prompt_file")
        create_symlink "$prompt_file" "$CENTRAL_DIR/prompts/$basename"
    done
fi

# ── Symlink instructions ────────────────────────────────────────────────────
if [ -d "$CUSTOM_AGENTS_DIR/instructions" ]; then
    for instr_file in "$CUSTOM_AGENTS_DIR/instructions"/*.instructions.md; do
        [ -e "$instr_file" ] || continue
        basename=$(basename "$instr_file")
        create_symlink "$instr_file" "$CENTRAL_DIR/instructions/$basename"
    done
fi

# ── Symlink skills (folder-based) ──────────────────────────────────────────
if [ -d "$CUSTOM_AGENTS_DIR/skills" ]; then
    for skill_dir in "$CUSTOM_AGENTS_DIR/skills"/*/; do
        [ -d "$skill_dir" ] || continue
        [ -f "${skill_dir}SKILL.md" ] || continue
        dirname=$(basename "$skill_dir")
        create_symlink "$skill_dir" "$CENTRAL_DIR/skills/$dirname"
    done
fi

# ── Sync central registry to CLI directories ────────────────────────────────
# Each CLI gets symlinks from the central dir into its own resource dirs.
for cli_name in claude codex cursor; do
    cli_base="$HOME/.$cli_name"
    [ -d "$cli_base" ] || mkdir -p "$cli_base"

    for resource_type in agents prompts instructions skills; do
        src_dir="$CENTRAL_DIR/$resource_type"
        [ -d "$src_dir" ] || continue

        cli_type_dir="$cli_base/$resource_type"
        mkdir -p "$cli_type_dir"

        for item in "$src_dir"/*; do
            [ -e "$item" ] || continue
            item_name=$(basename "$item")
            create_symlink "$item" "$cli_type_dir/$item_name"
        done
    done
done

echo "--- Custom agent resource symlinks complete ---"
