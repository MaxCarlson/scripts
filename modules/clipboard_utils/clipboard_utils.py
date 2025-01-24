import sys
import subprocess
import platform

def get_clipboard():
    """Retrieve clipboard contents, supporting Termux, Ubuntu, and PowerShell."""
    try:
        system = platform.system()

        if "Android" in system:  # Termux (Android)
            return subprocess.run(["termux-clipboard-get"], capture_output=True, text=True, check=True).stdout.strip()
        elif system == "Linux":  # Ubuntu/Linux
            return subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, check=True).stdout.strip()
        elif system == "Windows":  # Windows (PowerShell)
            return subprocess.run(["powershell", "-command", "Get-Clipboard"], capture_output=True, text=True, check=True).stdout.strip()
        else:
            print("Unsupported OS.")
            sys.exit(1)
    except Exception as e:
        print(f"Error fetching clipboard: {e}")
        sys.exit(1)

def set_clipboard(text):
    """Set clipboard contents, supporting Termux, Ubuntu, and PowerShell."""
    try:
        system = platform.system()

        if "Android" in system:  # Termux (Android)
            subprocess.run(["termux-clipboard-set"], input=text, text=True, check=True)
        elif system == "Linux":  # Ubuntu/Linux
            subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)
        elif system == "Windows":  # Windows (PowerShell)
            subprocess.run(["powershell", "-command", f"Set-Clipboard -Value '{text}'"], text=True, check=True)
        else:
            print("Unsupported OS.")
            sys.exit(1)

    except Exception as e:
        print(f"Error setting clipboard: {e}")
        sys.exit(1)
