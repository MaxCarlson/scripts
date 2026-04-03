#!/bin/bash

# This script sets up the development environment by installing the main repository
# and its submodules (termdash and procparsers) in editable mode.

# Get the absolute path of the script's directory (which should be the repo root)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

echo "Installing main repository in editable mode..."
cd "$SCRIPT_DIR"
pip install -e .

echo "Installing termdash submodule in editable mode..."
cd "$SCRIPT_DIR/termdash"
pip install -e .

echo "Installing procparsers submodule in editable mode..."
cd "$SCRIPT_DIR/procparsers"
pip install -e .

echo "Setup complete."
