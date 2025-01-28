#!/bin/bash

find . -type f -name "setup.py.bak*" | while IFS= read -r bak_file; do
    dir=$(dirname "$bak_file")
    setup_file="$dir/setup.py"
    toml_file="$dir/pyproject.toml"

    # Restore setup.py
    mv -v "$bak_file" "$setup_file"

    # If pyproject.toml exists, compare timestamps
    if [[ -f "$toml_file" ]]; then
        # Get modification times (cross-platform)
        if [[ "$OSTYPE" == "darwin"* ]]; then  # macOS
            bak_mod=$(date -r "$bak_file" +%s)
            toml_mod=$(date -r "$toml_file" +%s)
        else  # Linux
            bak_mod=$(stat -c %Y "$bak_file")
            toml_mod=$(stat -c %Y "$toml_file")
        fi

        # Compute absolute difference and check if within 2 minutes (120 seconds)
        diff=$(awk -v a="$bak_mod" -v b="$toml_mod" 'BEGIN { print (a > b ? a - b : b - a) }')

        if (( diff <= 120 )); then
            rm -v "$toml_file"
        fi
    fi
done
