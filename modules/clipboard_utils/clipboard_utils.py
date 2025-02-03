import os
import sys
import platform
import subprocess

def is_termux():
    """Detect if running inside Termux."""
    android_root = "ANDROID_ROOT" in os.environ
    shell_contains_termux = "com.termux" in os.environ.get("SHELL", "")
    is_wsl_env = "WSL" in platform.uname().release

    #print(f"DEBUG: ANDROID_ROOT exists? {android_root}")
    #print(f"DEBUG: SHELL contains 'com.termux'? {shell_contains_termux}")
    #print(f"DEBUG: Is WSL? {is_wsl_env}")

    return android_root and shell_contains_termux and not is_wsl_env

def is_wsl():
    """Detect if running inside WSL2."""
    return "microsoft" in platform.uname().release.lower()

def get_clipboard():
    """Retrieve clipboard contents, supporting Termux, Ubuntu, WSL2, and PowerShell."""
    try:
        if is_termux():
            return subprocess.run(["termux-clipboard-get"], capture_output=True, text=True, check=True).stdout.strip()

        system = platform.system()

        if system == "Linux":
            if is_wsl():
                return subprocess.run(["win32yank", "-o"], capture_output=True, text=True, check=True).stdout.strip()
            return subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, check=True)

        elif system == "Windows":
            return subprocess.run(["powershell", "-command", "Get-Clipboard"], capture_output=True, text=True, check=True).stdout.strip()

        else:
            print("Unsupported OS.")
            sys.exit(1)

    except Exception as e:
        print(f"Error fetching clipboard: {e}")
        sys.exit(1)

def set_clipboard(text):
    """Set clipboard contents, supporting Termux, Ubuntu, WSL2, and PowerShell."""
    try:
        if is_termux():
            subprocess.run(["termux-clipboard-set"], input=text, text=True, check=True)
            return

        system = platform.system()

        if system == "Linux":
            if is_wsl():
                subprocess.run(["win32yank", "-i"], input=text, text=True, check=True)
            else:
                subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)

        elif system == "Windows":
            subprocess.run(["powershell", "-command", f'Set-Clipboard -Value "{text}"'], text=True, check=True)

        else:
            print("Unsupported OS.")
            sys.exit(1)

    except Exception as e:
        print(f"Error setting clipboard: {e}")
        sys.exit(1)

