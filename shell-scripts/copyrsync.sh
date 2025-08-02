#!/bin/bash

# copy_rsync - A cp-like command using rsync for progress tracking

copy_rsync() {
    local src_list=()
    local dest=""
    local verbose=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -v) verbose=true ;;  # Enable verbose mode
            --) shift; break ;;   # Stop processing flags
            -*) echo "Unknown option: $1"; return 1 ;;
            *)
                if [[ -z "$dest" ]]; then
                    src_list+=("$1")
                else
                    echo "Too many arguments provided."
                    return 1
                fi
                ;;
        esac
        shift
    done

    # Ensure at least two arguments (source and destination) exist
    if [[ ${#src_list[@]} -lt 2 ]]; then
        echo "Usage: copy_rsync [-v] <source1> [source2 ...] <destination>"
        return 1
    fi

    # Extract last argument as destination
    dest="${src_list[-1]}"
    unset "src_list[-1]"

    # Ensure rsync is installed
    if ! command -v rsync &>/dev/null; then
        echo "rsync is not installed. Falling back to cp -r..."
        cp -r "${src_list[@]}" "$dest"
        return
    fi

    # Build rsync command
    local options=("-ah" "--info=progress2")
    [[ "$verbose" == true ]] && options+=("-v")

    # Execute rsync with progress
    rsync "${options[@]}" "${src_list[@]}" "$dest"
}

# Call the function with passed arguments
copy_rsync "$@"
