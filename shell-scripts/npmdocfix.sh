#!/usr/bin/env bash
# npm doctor auto-fix for Termux & Linux
# - Parses `npm doctor` output
# - On Termux: upgrades Node/npm via `pkg` (never `npm -g npm@…`)
# - On non-Termux: can upgrade npm globally (opt-in)
# - Cleans npm cache
# - Removes stale reify temp dirs that cause ENOTEMPTY
# - Optionally reinstalls a global package
#
# Usage:
#   ./npmdocfix.sh [-p|--package <name>] [-y|--yes] [--dry-run]
#                  [--no-reinstall] [--force-npm-install]
#
# Examples:
#   ./npmdocfix.sh --package @anthropic-ai/claude-code -y
#   ./npmdocfix.sh --dry-run

set -euo pipefail

PKG_NAME=""
ASSUME_YES=false
DRY_RUN=false
DO_REINSTALL=true
FORCE_NPM_INSTALL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--package)
            PKG_NAME="${2:-}"
            [[ -n "$PKG_NAME" ]] || { echo "ERROR: --package needs a value" >&2; exit 64; }
            shift 2
            ;;
        -y|--yes)
            ASSUME_YES=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --no-reinstall)
            DO_REINSTALL=false
            shift
            ;;
        --force-npm-install)
            FORCE_NPM_INSTALL=true
            shift
            ;;
        -h|--help)
            sed -n '1,120p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown arg: $1" >&2
            exit 64
            ;;
    esac
done

log()   { printf "%s\n" "$*"; }
warn()  { printf "WARN: %s\n" "$*" >&2; }
err()   { printf "ERROR: %s\n" "$*" >&2; }
run()   { if $DRY_RUN; then printf "[dry-run] %s\n" "$*"; else printf "→ %s\n" "$*"; eval "$@"; fi; }
confirm() {
    if $ASSUME_YES; then return 0; fi
    read -r -p "${1:-Proceed?} [y/N] " ans
    [[ "${ans,,}" =~ ^y(es)?$ ]]
}

is_termux() {
    [[ -n "${ANDROID_DATA:-}" && -d /data/data/com.termux/files ]]
}

npm_root_global() {
    npm root -g 2>/dev/null || true
}

kill_pkg_processes() {
    local name="$1"
    run "pkill -f '$name' 2>/dev/null || true"
    run "pkill -f 'node.*$name' 2>/dev/null || true"
}

# Remove npm's temp reify dirs like ".<name>-XXXX" at depth 1 (incl. @scopes)
clean_stale_temp_dirs() {
    local root="$1"
    local count=0

    if [[ -d "$root" ]]; then
        while IFS= read -r -d '' d; do
            run "rm -rf '$d'"
            ((count++)) || true
        done < <(find "$root" -maxdepth 1 -mindepth 1 -type d -name '.*-*' -print0)
    fi

    while IFS= read -r -d '' scope; do
        while IFS= read -r -d '' d; do
            run "rm -rf '$d'"
            ((count++)) || true
        done < <(find "$scope" -maxdepth 1 -mindepth 1 -type d -name '.*-*' -print0)
    done < <(find "$root" -maxdepth 1 -mindepth 1 -type d -name '@*' -print0)

    log "Removed $count stale npm temp dir(s) under $root"
}

# If a global package dir looks half-installed (no package.json), remove it
remove_half_installed_pkg() {
    local root="$1" pkg="$2" dir

    if [[ "$pkg" == @*/* ]]; then
        dir="$root/${pkg%%/*}/${pkg#*/}"
    else
        dir="$root/$pkg"
    fi

    [[ -d "$dir" ]] || return 0

    if [[ ! -f "$dir/package.json" ]]; then
        warn "Half-installed $pkg at $dir — removing"
        run "rm -rf '$dir'"
    fi
}

parse_doctor_and_fix() {
    local doc="$1"
    local status=0

    # npm recommendation: "Use npm v11.6.2"
    local rec_npm cur_npm
    rec_npm="$(grep -Eo 'Use npm v[0-9]+\.[0-9]+\.[0-9]+' "$doc" | awk '{print $3}' || true)"
    cur_npm="$(npm -v 2>/dev/null || echo 0.0.0)"

    if [[ -n "$rec_npm" && "$cur_npm" != "$rec_npm" ]]; then
        log "npm doctor recommends npm $rec_npm (current $cur_npm)"
        if is_termux && ! $FORCE_NPM_INSTALL; then
            log "Termux detected → npm is bundled with nodejs. Global 'npm i -g npm@…' is blocked."
            if confirm "Upgrade Node/npm via 'pkg up -y && pkg install -y nodejs'?"; then
                run "pkg up -y && pkg install -y nodejs"
            else
                warn "Skipped nodejs/npm upgrade on Termux"
                status=70
            fi
        else
            if confirm "Update npm to $rec_npm globally with npm?"; then
                run "npm i -g npm@${rec_npm}"
            else
                warn "Skipped npm update"
                status=70
            fi
        fi
    fi

    # node recommendation: "Use node v24.10.0 (current: v24.9.0)"
    local rec_node cur_node target
    rec_node="$(grep -Eo 'Use node v[0-9]+\.[0-9]+\.[0-9]+' "$doc" | awk '{print $3}' || true)"
    cur_node="$(node -v 2>/dev/null | sed 's/^v//' || echo 0.0.0)"
    target="${rec_node#v}"

    if [[ -n "$target" && "$cur_node" != "$target" ]]; then
        log "npm doctor recommends node $target (current $cur_node)"
        if is_termux; then
            if confirm "Attempt Node upgrade via 'pkg up -y && pkg install -y nodejs' (exact version may differ)?"; then
                run "pkg up -y && pkg install -y nodejs"
            else
                warn "Skipped Node upgrade on Termux"
                status=70
            fi
        elif command -v n >/dev/null 2>&1; then
            if confirm "Install Node $target using 'n'?"; then
                run "sudo n ${target} || n ${target}"
            else
                warn "Skipped Node upgrade"
                status=70
            fi
        elif command -v fnm >/dev/null 2>&1; then
            if confirm "Install Node $target using 'fnm'?"; then
                run "fnm install ${target} && fnm use ${target}"
            else
                warn "Skipped Node upgrade"
                status=70
            fi
        else
            warn "No Node version manager found. Install $target using your manager and re-run."
            status=70
        fi
    fi

    return $status
}

TMPDIR="${TMPDIR:-/tmp}"
DOC_OUT="$(mktemp "${TMPDIR%/}/npm-doctor-XXXX.txt")"
trap 'rm -f "$DOC_OUT"' EXIT

log "Running npm doctor ..."
npm doctor | tee "$DOC_OUT" || true

GLOBAL_ROOT="$(npm_root_global)"
if [[ -z "$GLOBAL_ROOT" || ! -d "$GLOBAL_ROOT" ]]; then
    err "Could not determine global node_modules (npm root -g)."
    exit 70
fi
log "Global node_modules: $GLOBAL_ROOT"

overall=0
if ! parse_doctor_and_fix "$DOC_OUT"; then
    overall=70
fi

log "Verifying npm cache ..."
run "npm cache verify || true"
log "Cleaning npm cache ..."
run "npm cache clean --force"

log "Cleaning stale npm temp dirs (fixes ENOTEMPTY) ..."
clean_stale_temp_dirs "$GLOBAL_ROOT"

if [[ -n "$PKG_NAME" ]]; then
    log "Preparing to reinstall: $PKG_NAME"
    kill_pkg_processes "$PKG_NAME"
    remove_half_installed_pkg "$GLOBAL_ROOT" "$PKG_NAME"
    if $DO_REINSTALL; then
        if confirm "Reinstall $PKG_NAME now?"; then
            run "npm i -g '$PKG_NAME' --no-audit --no-fund"
            log "✅ Reinstalled $PKG_NAME"
        else
            warn "Skipped reinstall of $PKG_NAME"
            overall=70
        fi
    fi
fi

log "Re-running npm doctor ..."
npm doctor | tee "$DOC_OUT" || true

if grep -q '^npm error Some problems found' "$DOC_OUT"; then
    warn "npm doctor still reports problems. See above."
    exit 70
fi

log "All done."
exit $overall
