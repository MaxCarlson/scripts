#!/usr/bin/env bash
# ai-cli-upsert.sh
# ---------------------------------------------------------------------------
# Installs or updates these AI CLIs:
#   • Claude Code CLI        -> npm package @anthropic-ai/claude-code  (bin: claude)
#   • Google AI Studio CLI   -> npm package aistudio                   (bin: aistudio)
#   • OpenAI CLI             -> pipx package openai                    (bin: openai)
#
# If a tool is missing, it will be installed. If present, it’s upgraded to latest.
# Termux-safe: never tries to upgrade npm itself; only installs/upgrades packages.
#
# Usage:
#   ai-cli-upsert.sh [--all|-a] [--claude|-c] [--gemini|-g] [--openai|-o]
#                    [--yes|-y] [--dry-run|-n] [--verbose|-v]
#
# Defaults to --all if no specific tools are selected.
#
# Examples:
#   ai-cli-upsert.sh -a -y
#   ai-cli-upsert.sh -c -g        # only Claude & Gemini CLIs
#   ai-cli-upsert.sh -o -y        # only OpenAI CLI via pipx
#
# Exit codes:
#   0 = success, 70 = partial failures, 64 = usage error
# ---------------------------------------------------------------------------

set -euo pipefail

# -------------------- flags --------------------
DO_CLAUDE=false
DO_GEMINI=false
DO_OPENAI=false
ASSUME_YES=false
DRY_RUN=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -a|--all) DO_CLAUDE=true; DO_GEMINI=true; DO_OPENAI=true; shift;;
        -c|--claude) DO_CLAUDE=true; shift;;
        -g|--gemini) DO_GEMINI=true; shift;;
        -o|--openai) DO_OPENAI=true; shift;;
        -y|--yes) ASSUME_YES=true; shift;;
        -n|--dry-run) DRY_RUN=true; shift;;
        -v|--verbose) VERBOSE=true; shift;;
        -h|--help)
            sed -n '1,120p' "$0" | sed 's/^# \{0,1\}//'
            exit 0;;
        *) echo "Unknown argument: $1" >&2; exit 64;;
    esac
done

# default to all if none chosen
if ! $DO_CLAUDE && ! $DO_GEMINI && ! $DO_OPENAI; then
    DO_CLAUDE=true
    DO_GEMINI=true
    DO_OPENAI=true
fi

# -------------------- helpers --------------------
log() { printf "%s\n" "$*"; }
debug() { $VERBOSE && printf "DEBUG: %s\n" "$*" >&2 || true; }
warn() { printf "WARN: %s\n" "$*" >&2; }
err()  { printf "ERROR: %s\n" "$*" >&2; }

run() {
    if $DRY_RUN; then
        printf "[dry-run] %s\n" "$*"
    else
        $VERBOSE && printf "→ %s\n" "$*"
        eval "$@"
    fi
}

confirm() {
    $ASSUME_YES && return 0
    read -r -p "${1:-Proceed?} [y/N] " ans
    [[ "${ans,,}" == "y" || "${ans,,}" == "yes" ]]
}

is_termux() { [[ -n "${ANDROID_DATA:-}" && -d /data/data/com.termux/files ]]; }

require_cmd() {
    local c="$1" msg="${2:-}"
    if ! command -v "$c" >/dev/null 2>&1; then
        [[ -n "$msg" ]] && err "$msg"
        return 1
    fi
    return 0
}

# Termux global node_modules; fallback for other systems
npm_global_root() {
    local root
    if ! root="$(npm root -g 2>/dev/null)"; then
        echo ""
        return 1
    fi
    echo "$root"
    return 0
}

# Nuke npm’s leftover temp dirs like ".<name>-random" that can cause ENOTEMPTY
npm_cleanup_temp_dirs_for_pkg() {
    local pkg="$1"
    local root; root="$(npm_global_root)" || return 0
    [[ -d "$root" ]] || return 0

    # Compute dir patterns to clean, including scope
    local scope="" name="$pkg" base="$root"
    if [[ "$pkg" == @*/* ]]; then
        scope="${pkg%%/*}"
        name="${pkg#*/}"
        base="$root/$scope"
    fi

    if [[ -d "$base" ]]; then
        # remove half-installed package dir with no package.json
        if [[ -d "$base/$name" && ! -f "$base/$name/package.json" ]]; then
            warn "Removing half-installed $pkg at $base/$name"
            run "rm -rf '$base/$name'"
        fi
        # remove temp reify dirs like ".name-*"
        # shellcheck disable=SC2010
        local d
        for d in "$base"/."$name"-*; do
            [[ -e "$d" ]] || continue
            warn "Removing stale npm temp dir: $d"
            run "rm -rf '$d'"
        done
    fi
}

npm_install_or_update() {
    local pkg="$1" bin="$2"
    local have=false
    if command -v "$bin" >/dev/null 2>&1; then have=true; fi

    npm_cleanup_temp_dirs_for_pkg "$pkg"

    if $have; then
        # Update to latest explicitly
        log "Updating npm package $pkg to latest ..."
        run "npm i -g '$pkg@latest' --no-audit --no-fund"
    else
        log "Installing npm package $pkg ..."
        run "npm i -g '$pkg' --no-audit --no-fund"
    fi
}

pipx_install_or_update() {
    local pkg="$1" bin="$2"
    if ! command -v pipx >/dev/null 2>&1; then
        log "pipx not found — installing pipx (user) ..."
        # On Termux, python is installed as 'python' and pip as 'pip'
        if ! command -v python >/dev/null 2>&1; then
            if is_termux; then
                if confirm "Install python via 'pkg install -y python'?"; then
                    run "pkg install -y python"
                else
                    err "Python is required for pipx."; return 70
                fi
            else
                err "Python is required for pipx. Please install Python and re-run."; return 70
            fi
        fi
        run "python -m pip install --user --upgrade pip"
        run "python -m pip install --user pipx"
        # Ensure pipx on PATH (Termux installs to $PREFIX/bin typically)
        if ! command -v pipx >/dev/null 2>&1; then
            # Try adding ~/.local/bin for non-Termux
            export PATH="$HOME/.local/bin:$PATH"
            debug "Added ~/.local/bin to PATH for pipx"
            if ! command -v pipx >/dev/null 2>&1; then
                err "pipx still not found on PATH; add ~/.local/bin to PATH and re-run."
                return 70
            fi
        fi
    fi

    if command -v "$bin" >/dev/null 2>&1; then
        log "Upgrading pipx package $pkg ..."
        run "pipx upgrade '$pkg'"
    else
        log "Installing pipx package $pkg ..."
        run "pipx install '$pkg' || pipx install --force '$pkg'"
    fi
}

kill_running_bin() {
    local bin="$1"
    # Best-effort kill (don’t fail if nothing running)
    run "pkill -f '$bin' 2>/dev/null || true"
    run "pkill -f 'node.*$bin' 2>/dev/null || true"
}

# -------------------- preflight --------------------
if ! require_cmd npm "npm is required. Install Node.js first (Termux: pkg install -y nodejs)."; then
    if is_termux; then
        if confirm "Install Node.js via 'pkg install -y nodejs'?"; then
            run "pkg update -y && pkg install -y nodejs"
        else
            err "Missing npm/Node. Aborting."
            exit 70
        fi
    else
        err "Missing npm/Node. Please install Node.js and re-run."
        exit 70
    fi
fi

overall_status=0

# -------------------- Claude Code CLI --------------------
if $DO_CLAUDE; then
    log "=== Claude Code CLI (@anthropic-ai/claude-code) ==="
    kill_running_bin "claude"
    if ! npm_install_or_update "@anthropic-ai/claude-code" "claude"; then
        err "Failed to install/update @anthropic-ai/claude-code"
        overall_status=70
    else
        log "✅ Claude Code CLI ready: $(command -v claude || echo 'claude')"
    fi
fi

# -------------------- Google AI Studio (Gemini) CLI --------------------
if $DO_GEMINI; then
    log "=== Google AI Studio CLI (aistudio) ==="
    kill_running_bin "aistudio"
    if ! npm_install_or_update "aistudio" "aistudio"; then
        warn "Primary install path failed for 'aistudio'."
        warn "If Google changes the package name, update this script’s GEMINI_NPM_PKG variable."
        overall_status=70
    else
        log "✅ AI Studio CLI ready: $(command -v aistudio || echo 'aistudio')"
    fi
fi

# -------------------- OpenAI CLI --------------------
if $DO_OPENAI; then
    log "=== OpenAI CLI (pipx: openai) ==="
    kill_running_bin "openai"
    if ! pipx_install_or_update "openai" "openai"; then
        err "Failed to install/update OpenAI CLI via pipx"
        overall_status=70
    else
        log "✅ OpenAI CLI ready: $(command -v openai || echo 'openai')"
    fi
fi

# -------------------- summary --------------------
if [[ $overall_status -eq 0 ]]; then
    log "All requested CLIs are installed/updated successfully."
else
    warn "Some installs/updates reported issues (exit $overall_status). Review messages above."
fi

exit $overall_status
