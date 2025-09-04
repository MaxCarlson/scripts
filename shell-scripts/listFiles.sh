#!/bin/bash

################################################################################
#
# This script lists all .cpp, .h, and .java files in the specified folder and
# its subdirectories, printing the filename without the path, followed by two
# tabs, and then the relative path from the root folder.
#
# Usage: ./listFiles.sh /path/to/root_folder
#
################################################################################

# Check if the root folder is provided as an argument
if [ -z "$1" ]; then
    echo "Usage: $0 /path/to/root_folder"
    exit 1
fi

# Define the root folder to search
root_folder="$1"

# Find .cpp, .h, and .java files and format the output using awk
find "$root_folder" -type f \( -name "*.cpp" -o -name "*.h" -o -name "*.java" \) -print | awk -v root="$root_folder" -F/ '
{
    filename = $NF
    filepath = $0
    sub(root, "", filepath)
    filenames[NR] = filename
    filepaths[NR] = filepath
    if (length(filename) > max_length) {
        max_length = length(filename)
    }
}
END {
    for (i = 1; i <= NR; i++) {
        printf "%-" max_length "s\t\t%s\n", filenames[i], filepaths[i]
    }
}'