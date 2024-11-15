#!/bin/bash

# Default values
SOURCE_FOLDER="./"
SSH_USER="mcarls"
BASE_IP="192.168.50"
LAST_OCTET="100"
DELETE_SOURCE="false"
DEST_FOLDER="~/"
CONVERT_TO_WSL_PATH="true"
SSH_PORT="2222"

# Function to print usage
usage() {
    echo "Usage: $0 [-u user] [-D] -p remote_path [source_folder] [base_ip] [last_octet] [-P port] [--no-wsl-path]"
    echo "Example: $0 -u mcarls -D -p C:/Users/mcarls/Downloads ~/storage/downloads/Seal/ 192.168.1 105 -P 2222"
    exit 1
}

# Function to convert Windows path to WSL path
convert_to_wsl_path() {
    local path="$1"
    if [[ "$path" =~ ^([a-zA-Z]):[\\/](.*) ]]; then
        local drive="${BASH_REMATCH[1],,}" # Convert drive letter to lowercase
        local subpath="${BASH_REMATCH[2]//\\//}" # Replace backslashes with slashes
        echo "/mnt/${drive}/${subpath}"
    else
        echo "$path" # Return the original path if it doesn't match Windows-style
    fi
}

# Parse options
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -u|--user) SSH_USER="$2"; shift ;;
        -D|--delete-source) DELETE_SOURCE="true" ;;
        -p|--path) DEST_FOLDER="$2"; shift ;;
        -P|--port) SSH_PORT="$2"; shift ;;
        --no-wsl-path) CONVERT_TO_WSL_PATH="false" ;;
        -h|--help) usage ;;
        *)
            if [ -z "$SOURCE_FOLDER_PROVIDED" ]; then
                SOURCE_FOLDER="$1"
                SOURCE_FOLDER_PROVIDED="true"
            elif [ -z "$BASE_IP_PROVIDED" ]; then
                BASE_IP="$1"
                BASE_IP_PROVIDED="true"
            elif [ -z "$LAST_OCTET_PROVIDED" ]; then
                LAST_OCTET="$1"
                LAST_OCTET_PROVIDED="true"
            else
                echo "Unknown option or too many arguments."
                usage
            fi
            ;;
    esac
    shift
done

# Ensure that the destination path is provided
if [ -z "$DEST_FOLDER" ]; then
    echo "Error: Destination path is required."
    usage
fi

# Convert paths to WSL paths if the feature is enabled
if [[ "$CONVERT_TO_WSL_PATH" == "true" ]]; then
    DEST_FOLDER=$(convert_to_wsl_path "$DEST_FOLDER")
    SOURCE_FOLDER=$(convert_to_wsl_path "$SOURCE_FOLDER")
fi

# Construct the full destination IP address
DEST_IP="${BASE_IP}.${LAST_OCTET}"

# Print the destination IP for debugging
echo "Destination IP: $DEST_IP"

# Rsync command with options
RSYNC_CMD="rsync -av --progress --info=progress2 -e \"ssh -p $SSH_PORT\""

# If delete-source option is enabled, add the remove-source-files flag
if [[ "$DELETE_SOURCE" == "true" ]]; then
    RSYNC_CMD="${RSYNC_CMD} --remove-source-files"
fi

# Execute the rsync command
eval $RSYNC_CMD "$SOURCE_FOLDER" "${SSH_USER}@${DEST_IP}:${DEST_FOLDER}"

# Exit with success message
if [ $? -eq 0 ]; then
    echo "Rsync transfer completed successfully."
else
    echo "Rsync transfer failed."
    exit 1
fi
