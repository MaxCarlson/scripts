#!/usr/bin/env python3
"""
setup_wsl2.py

A script to install win32yank on WSL2 environments.

Requirements:
  - This script should be run on WSL2.
  - GitHub CLI (`gh`) must be installed.
  - `unzip` must be available.
  - Sudo permissions to move the binary to /usr/local/bin.
"""

import os
import sys
import subprocess
import platform
import tempfile
import shutil
import json
from pathlib import Path
from shutil import which

def is_wsl():
    """
    Check if the current environment is WSL2 by examining the platform's release string.
    """
    return "microsoft" in platform.uname().release.lower()

def is_win32yank_installed():
    """
    Check if win32yank is available in the PATH.
    """
    return which("win32yank") is not None

def get_latest_release_tag():
    """
    Use the GitHub CLI to query the repository releases via the GitHub API
    and return the tag name of the latest release.
    """
    try:
        result = subprocess.run(
            ["gh", "api", "repos/equalsraf/win32yank/releases"],
            capture_output=True, text=True, check=True
        )
        releases = json.loads(result.stdout)
        if not releases:
            print("❌ No releases found in the repository.")
            sys.exit(1)
        # Assuming the releases are sorted by creation date descending,
        # return the tag name of the first release.
        return releases[0]["tag_name"]
    except Exception as e:
        print(f"❌ Error fetching latest release tag: {e}")
        sys.exit(1)

def install_win32yank():
    """
    Install the latest release of win32yank using the GitHub CLI.
    """
    # Check if gh is installed
    try:
        subprocess.run(
            ["gh", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
    except Exception:
        print("❌ GitHub CLI (gh) is required but not installed.")
        print("Please install it from https://cli.github.com/ and try again.")
        sys.exit(1)

    tag = get_latest_release_tag()
    print(f"🔄 Latest release tag: {tag}")

    # Create a temporary directory for download and extraction.
    tmp_dir = Path(tempfile.mkdtemp())
    original_cwd = Path.cwd()
    os.chdir(tmp_dir)
    try:
        print("🔄 Downloading win32yank release...")
        subprocess.run(
            [
                "gh", "release", "download", tag,
                "--repo", "equalsraf/win32yank",
                "--pattern", "win32yank-x64.zip"
            ],
            check=True
        )
        print("🔄 Unzipping win32yank-x64.zip...")
        subprocess.run(["unzip", "win32yank-x64.zip"], check=True)
        print("🔄 Making win32yank.exe executable...")
        subprocess.run(["chmod", "+x", "win32yank.exe"], check=True)
        print("🔄 Moving win32yank to /usr/local/bin/win32yank ...")
        subprocess.run(["sudo", "mv", "win32yank.exe", "/usr/local/bin/win32yank"], check=True)
        print("✅ win32yank installed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error during win32yank installation: {e}")
        sys.exit(1)
    finally:
        os.chdir(original_cwd)
        shutil.rmtree(tmp_dir)

def main():
    if not is_wsl():
        print("⚠️ This script is intended for WSL2 environments. Exiting.")
        sys.exit(0)
    if is_win32yank_installed():
        print("✅ win32yank is already installed. No action needed.")
        sys.exit(0)
    else:
        install_win32yank()

if __name__ == "__main__":
    main()

