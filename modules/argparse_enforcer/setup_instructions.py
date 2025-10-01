"""
Cross-platform argcomplete setup instructions.
"""
import sys
import os


def get_shell_info():
    """Detect the current shell and OS."""
    os_name = sys.platform
    shell = os.environ.get("SHELL", "")

    if "win32" in os_name or "cygwin" in os_name:
        # Windows - check for PowerShell
        if "pwsh" in os.environ.get("PSModulePath", "").lower():
            return "windows", "pwsh"
        elif os.environ.get("PSModulePath"):
            return "windows", "powershell"
        else:
            return "windows", "cmd"
    elif "linux" in os_name:
        if "zsh" in shell:
            return "linux", "zsh"
        elif "bash" in shell:
            return "linux", "bash"
        else:
            return "linux", "unknown"
    elif "darwin" in os_name:
        if "zsh" in shell:
            return "macos", "zsh"
        elif "bash" in shell:
            return "macos", "bash"
        else:
            return "macos", "unknown"
    else:
        return "unknown", "unknown"


def get_setup_instructions():
    """Get argcomplete setup instructions for the current platform."""
    os_name, shell = get_shell_info()

    instructions = {
        "header": "\n" + "="*70 + "\n  Argcomplete Setup Instructions\n" + "="*70 + "\n",
        "install": "",
        "activation": "",
        "script_specific": "",
        "verify": "",
        "notes": ""
    }

    # Installation instructions
    instructions["install"] = """
1. INSTALL ARGCOMPLETE:
   pip install argcomplete

   Or if using the module's dependencies:
   pip install -r requirements.txt
"""

    # Platform-specific activation
    if os_name == "windows" and shell == "pwsh":
        instructions["activation"] = """
2. ACTIVATE ARGCOMPLETE (PowerShell 7+):

   Add to your PowerShell profile ($PROFILE):

   # Enable argcomplete for Python scripts
   Register-ArgumentCompleter -Native -CommandName python -ScriptBlock {
       param($wordToComplete, $commandAst, $cursorPosition)
       $env:_ARGCOMPLETE = 1
       $env:_ARGCOMPLETE_SHELL = 'powershell'
       $env:_ARGCOMPLETE_SUPPRESS_SPACE = 1
       $env:COMP_LINE = $commandAst.ToString()
       $env:COMP_POINT = $cursorPosition
       python $commandAst.CommandElements[1].Value 8>&1 9>&1 |
           ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }
   }

   To edit your profile:
   notepad $PROFILE

   Or create it if it doesn't exist:
   if (!(Test-Path -Path $PROFILE)) { New-Item -ItemType File -Path $PROFILE -Force }
   notepad $PROFILE
"""
        instructions["verify"] = """
3. VERIFY SETUP:

   Restart PowerShell, then try:
   python your_script.py --<TAB>
"""

    elif os_name == "windows" and shell == "powershell":
        instructions["activation"] = """
2. ACTIVATE ARGCOMPLETE (Windows PowerShell 5.1):

   Note: Argcomplete support is limited in PowerShell 5.1.
   Consider upgrading to PowerShell 7+ for better support.

   Alternatively, use Windows Subsystem for Linux (WSL) with bash/zsh.
"""
        instructions["verify"] = """
3. VERIFY SETUP:

   Consider using PowerShell 7+ or WSL for full argcomplete support.
"""

    elif os_name in ["linux", "macos"] and shell == "bash":
        instructions["activation"] = """
2. ACTIVATE ARGCOMPLETE (Bash):

   Option A - Global activation (recommended):
   Run once:
   activate-global-python-argcomplete --user

   Then add to your ~/.bashrc:
   eval "$(register-python-argcomplete your_script_name)"

   Option B - Per-script activation:
   Add to your ~/.bashrc:
   eval "$(register-python-argcomplete your_script_name)"

   Apply changes:
   source ~/.bashrc
"""
        instructions["verify"] = """
3. VERIFY SETUP:

   Restart your terminal or run:
   source ~/.bashrc

   Then try:
   your_script_name --<TAB>
"""

    elif os_name in ["linux", "macos"] and shell == "zsh":
        instructions["activation"] = """
2. ACTIVATE ARGCOMPLETE (Zsh):

   Add to your ~/.zshrc:

   # Enable bash completion compatibility
   autoload -U bashcompinit
   bashcompinit

   # Activate argcomplete
   eval "$(register-python-argcomplete your_script_name)"

   Apply changes:
   source ~/.zshrc
"""
        instructions["verify"] = """
3. VERIFY SETUP:

   Restart your terminal or run:
   source ~/.zshrc

   Then try:
   your_script_name --<TAB>
"""

    else:
        instructions["activation"] = """
2. ACTIVATE ARGCOMPLETE:

   For detailed instructions, visit:
   https://github.com/kislyuk/argcomplete#installation
"""
        instructions["verify"] = """
3. VERIFY SETUP:

   Refer to argcomplete documentation for your platform.
"""

    # Script-specific instructions
    instructions["script_specific"] = """
4. FOR YOUR SCRIPT:

   If you've installed your script as a command-line tool:
   eval "$(register-python-argcomplete YOUR_COMMAND_NAME)"

   Or add this line near the top of your script (after argparse setup):
   # PYTHON_ARGCOMPLETE_OK
"""

    # Additional notes
    instructions["notes"] = """
5. NOTES:

   - Tab completion will work for argument names (--file, -f, etc.)
   - EnforcedArgumentParser automatically enables argcomplete by default
   - To disable: EnforcedArgumentParser(enable_autocomplete=False)
   - Completion may not work in all terminals/shells
   - For more info: https://github.com/kislyuk/argcomplete
"""

    return instructions


def print_setup_instructions():
    """Print setup instructions for the current platform."""
    instructions = get_setup_instructions()

    print(instructions["header"])
    print(instructions["install"])
    print(instructions["activation"])
    print(instructions["script_specific"])
    print(instructions["verify"])
    print(instructions["notes"])
    print("="*70 + "\n")


def check_argcomplete_installed():
    """Check if argcomplete is installed and provide guidance."""
    try:
        import argcomplete
        return True, f"Argcomplete is installed (version {argcomplete.__version__})"
    except ImportError:
        return False, "Argcomplete is NOT installed"


def print_quick_status():
    """Print quick status and setup check."""
    os_name, shell = get_shell_info()
    installed, status = check_argcomplete_installed()

    print("\n" + "="*70)
    print("  Argcomplete Status")
    print("="*70)
    print(f"\nDetected OS: {os_name}")
    print(f"Detected Shell: {shell}")
    print(f"Argcomplete Status: {status}")

    if not installed:
        print("\nTo enable tab completion, argcomplete must be installed:")
        print("  pip install argcomplete")
        print("\nThen run: python -m argparse_enforcer.setup_instructions")
        print("  to see setup instructions for your platform.")
    else:
        print("\nArgcomplete is installed! Make sure it's activated in your shell.")
        print("Run: python -m argparse_enforcer.setup_instructions")
        print("  to see activation instructions for your platform.")

    print("="*70 + "\n")


if __name__ == "__main__":
    print_setup_instructions()
