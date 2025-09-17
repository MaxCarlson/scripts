#!/bin/bash
# Bash script to find the largest file recursively in a directory, with options to ignore hidden files and folders,
# ignore files that match a pattern, accept only files that match a pattern, and avoid searching folders that match a pattern.
# It also converts file size to KB/MB/GB with two decimal places.

ignore_hidden=false
ignore_pattern=""
accept_pattern=""
ignore_folder_pattern=""
dir="."

# Parse command line options
while getopts ":d:ip:a:f:" opt; do
  case $opt in
    d)
      dir="$OPTARG"
      ;;
    i)
      ignore_hidden=true
      ;;
    p)
      ignore_pattern="$OPTARG"
      ;;
    a)
      accept_pattern="$OPTARG"
      ;;
    f)
      ignore_folder_pattern="$OPTARG"
      ;;
    \?)
      echo "Invalid option: -$OPTARG" >&2
      exit 1
      ;;
  esac
done

# Function to convert size to human-readable format
convert_size() {
  local size=$1
  if [ "$size" -lt 1024 ]; then
    echo "${size}B"
  elif [ "$size" -lt $((1024 * 1024)) ]; then
    echo "$(awk "BEGIN {printf \"%.2f\", $size/1024}")KB"
  elif [ "$size" -lt $((1024 * 1024 * 1024)) ]; then
    echo "$(awk "BEGIN {printf \"%.2f\", $size/(1024*1024)}")MB"
  else
    echo "$(awk "BEGIN {printf \"%.2f\", $size/(1024*1024*1024)}")GB"
  fi
}

# Function to find the largest file
find_largest_file() {
  if $ignore_hidden; then
    find_cmd="find \"$dir\" -type f ! -path '*/.*'"
  else
    find_cmd="find \"$dir\" -type f"
  fi

  if [ -n "$ignore_pattern" ]; then
    find_cmd="$find_cmd ! -name \"$ignore_pattern\""
  fi

  if [ -n "$accept_pattern" ]; then
    find_cmd="$find_cmd -name \"$accept_pattern\""
  fi

  if [ -n "$ignore_folder_pattern" ]; then
    find_cmd="$find_cmd ! -path \"*/$ignore_folder_pattern/*\""
  fi

  largest_file=$(eval "$find_cmd -exec du -b {} + | sort -nr | head -n 1")

  size=$(echo "$largest_file" | awk '{print $1}')
  file=$(echo "$largest_file" | awk '{print $2}')
  
  # Check if size is not empty
  if [ -n "$size" ]; then
    readable_size=$(convert_size $size)
  else
    readable_size="0B"
  fi

  echo "Largest File: $file"
  echo "Size: $readable_size"
}

# Execute the function
find_largest_file
