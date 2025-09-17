#!/usr/bin/env python3
# scripts_setup/setup_pwsh_profile.py
import os, subprocess, sys
from pathlib import Path

def _pwsh_profile_paths():
    # CurrentUser for PowerShell 7+
    docs = Path.home() / "Documents"
    return [
        docs / "PowerShell" / "Microsoft.PowerShell_profile.ps1",        # pwsh
        docs / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",  # Windows PowerShell
    ]

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Add dynamic aliases + module import to PowerShell profile.")
    ap.add_argument("--scripts-dir", type=Path, required=True)
    ap.add_argument("--dotfiles-dir", type=Path, required=True)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    dyn = (args.dotfiles_dir / "dynamic").resolve()
    ps_aliases = dyn / "setup_pyscripts_aliases.ps1"
    ps_funcs   = dyn / "setup_pyscripts_functions.ps1"
    module_psm1 = (args.scripts_dir / "pwsh" / "ClipboardModule.psm1").resolve()

    snippet_lines = [
        "# ----- added by setup_pwsh_profile.py -----",
        f'$d = "{str(dyn)}"',
        f'$m = "{str(module_psm1)}"',
        'if (Test-Path (Join-Path $d "setup_pyscripts_aliases.ps1")) { . (Join-Path $d "setup_pyscripts_aliases.ps1") }',
        'if (Test-Path (Join-Path $d "setup_pyscripts_functions.ps1")) { . (Join-Path $d "setup_pyscripts_functions.ps1") }',
        'if (Test-Path $m) { Import-Module $m -ErrorAction SilentlyContinue }',
        "# ----- end added by setup_pwsh_profile.py -----",
        ""
    ]
    snippet = "\n".join(snippet_lines)

    for p in _pwsh_profile_paths():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            content = p.read_text(encoding="utf-8") if p.is_file() else ""
            if "setup_pwsh_profile.py" in content:
                if args.verbose: print(f"[INFO] Profile already contains our block: {p}")
                continue
            with open(p, "a", encoding="utf-8", newline="\n") as f:
                f.write("\n" + snippet)
            print(f"[OK] Updated PowerShell profile: {p}")
        except Exception as e:
            print(f"[WARN] Could not update PowerShell profile {p}: {e}")

if __name__ == "__main__":
    main()
