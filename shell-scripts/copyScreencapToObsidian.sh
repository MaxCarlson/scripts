#!/bin/zsh

# Define source and destination directories
source_dir="$HOME/Pictures/Screenshots"
destination_dir="$HOME/Documents/Obsidian Vault/assets/images"

# Find the latest file in the source directory
latest_file=$(ls -t "${source_dir}" | head -n 1)

# Check if a file was found
if [[ -z "$latest_file" ]]; then
    echo "No files found in ${source_dir}."
    exit 1
fi

# Copy the latest file to the destination directory
cp "${source_dir}/${latest_file}" "${destination_dir}/"

echo "Copied ${latest_file} to ${destination_dir}."

