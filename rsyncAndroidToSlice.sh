#!/bin/bash

# Default values
SOURCE_FOLDER="./"
SSH_USER="mcarls"
BASE_IP="192.168.50"
LAST_OCTET="105"
DELETE_SOURCE="false"
DEST_FOLDER="~/"

# Function to print usage
usage() {
    echo "Usage: $0 [-u user] [-D] -p remote_path [source_folder] [base_ip] [last_octet]"
    echo "Example: $0 -u mcarls -D -p /path/on/remote/machine /path/to/source_folder 192.168.1 105"
    exit 1
}

# Parse options
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -u|--user) SSH_USER="$2"; shift ;;
        -D|--delete-source) DELETE_SOURCE="true" ;;
        -p|--path) DEST_FOLDER="$2"; shift ;;
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

# Construct the full destination IP address
DEST_IP="${BASE_IP}.${LAST_OCTET}"

# Rsync command with options
RSYNC_CMD="rsync -avzP"

# If delete-source option is enabled, add the remove-source-files flag
if [[ "$DELETE_SOURCE" == "true" ]]; then
    RSYNC_CMD="${RSYNC_CMD} --remove-source-files"
fi

# Execute the rsync command
$RSYNC_CMD "$SOURCE_FOLDER" "${SSH_USER}@${DEST_IP}:${DEST_FOLDER}"

# Exit with success message
if [ $? -eq 0 ]; then
    echo "Rsync transfer completed successfully."
else
    echo "Rsync transfer failed."
    exit 1
fi

