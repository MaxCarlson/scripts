#!/bin/bash

# Ensure `gh` is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed." >&2
    exit 1
fi

# Ensure `git` is installed
if ! command -v git &> /dev/null; then
    echo "Error: Git is not installed." >&2
    exit 1
fi

# Check if inside a Git repository
if ! git rev-parse --is-inside-work-tree &> /dev/null; then
    echo "Error: You are not inside a Git repository." >&2
    exit 1
fi

# Check if a repository name is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <repo-name> [submodule-path]"
    exit 1
fi

# Repository name (assumes it's owned by the current GitHub user)
REPO_NAME="$1"
USER=$(gh api user --jq '.login')
REPO_FULL_NAME="$USER/$REPO_NAME"

# Default submodule path (same as repo name unless specified)
SUBMODULE_PATH="${2:-$REPO_NAME}"

# Ensure submodule path does not already exist
if [ -d "$SUBMODULE_PATH" ]; then
    echo "Error: Target directory '$SUBMODULE_PATH' already exists." >&2
    exit 1
fi

# Clone the repository directly to the submodule path
gh repo clone "$REPO_NAME" "$SUBMODULE_PATH"

# Add the repository as a submodule
git submodule add "./$SUBMODULE_PATH" "$SUBMODULE_PATH"

# Commit the submodule addition
git add .gitmodules "$SUBMODULE_PATH"
git commit -m "Added submodule: $REPO_NAME at $SUBMODULE_PATH"
git push

echo "Submodule '$REPO_NAME' added successfully at '$SUBMODULE_PATH'."
