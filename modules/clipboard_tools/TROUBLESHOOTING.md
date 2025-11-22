# Clipboard Tools – PATH & PowerShell Function Conflicts

This note documents the “`c2c` runs but ignores args / picks wrong Python” problem, what caused it, and how we mitigated it. Use it as a quick reference the next time the clipboard CLI feels “silent” or resolves to the wrong executable.

## Symptom
- `c2c`, `pclip`, `rwc`, etc. showed no output or skipped args.
- `Get-Command c2c` sometimes returned a PowerShell `Function` wrapping `pyscripts/copy_to_clipboard.py`, other times the global `Python313\Scripts\c2c.exe`, and in the repo it was `.venv\Scripts\c2c.exe`.
- When outside `scripts/`, PATH pointed to `C:\Users\mcarls\AppData\Local\Programs\Python\Python313\Scripts\c2c.exe` instead of the repo venv.

## Root Causes
1) **PowerShell function shadowing**  
   `dotfiles/dynamic/setup_pyscripts_functions.ps1` was generated from `pyscripts/alias_and_func_defs.txt` and created functions named `c2c`, `pclip`, `rwc`, etc. Those functions swallowed args and bypassed the module entrypoints.

2) **PATH precedence**  
   Outside the repo, PATH listed `Python313\Scripts` before `scripts\.venv\Scripts`, so `c2c` resolved to the globally installed console script (or failed if not installed).

## Fixes Applied
- Removed the clipboard functions from `setup_pyscripts_functions.ps1` (leaving only non-clipboard helpers) and cleared the existing clipboard functions from the current session.
- Commented the clipboard entries in `pyscripts/alias_and_func_defs.txt` to prevent regeneration of those functions.
- Installed `clipboard_tools` into the global Python 3.13 as a safety net so even when PATH resolves to the global console script, it still runs the same version as the repo venv.
- Kept the repo shims in `scripts/bin/*.cmd` pointing at `.venv\Scripts\*.exe`.

## What to Do if It Reappears
1) **Check what PowerShell sees:**  
   `Get-Command c2c | Format-List CommandType,Definition,Path`  
   - If `CommandType` is `Function`, remove it:  
     `Remove-Item Function:c2c,pclip,rwc,otc,otcw,apc,cb2c,cb2cf,cld,crx,rwcp,otca,otcwa,otcwp -ErrorAction SilentlyContinue`
   - If it’s an `Application` but points to the wrong Python, adjust PATH or uninstall the global package.

2) **Prefer the repo venv everywhere:**  
   Ensure `C:\Users\mcarls\Repos\scripts\.venv\Scripts` (or `C:\Users\mcarls\Repos\scripts\bin`) is before `C:\Users\mcarls\AppData\Local\Programs\Python\Python313\Scripts` in PATH.

3) **Regenerate dynamic files safely:**  
   If you re-run `pyscripts/setup.py`, leave the clipboard entries commented in `pyscripts/alias_and_func_defs.txt` so they aren’t reintroduced into PowerShell.

4) **Last resort (global):**  
   - Remove global copies: `py -3.13 -m pip uninstall clipboard_tools`  
   - Or reinstall matching version: `py -3.13 -m pip install --upgrade --no-deps .\\modules\\clipboard_tools`

## Current State (after fixes)
- In repo (`C:\Users\mcarls\Repos\scripts`): `Get-Command c2c` → `.venv\Scripts\c2c.exe`
- Outside repo: resolves to global `Python313\Scripts\c2c.exe` but runs the same `clipboard_tools` version (0.1.2). Prefer PATH tweak if you want the venv everywhere.

### Why you still see Python3.13 outside `scripts/`
`Get-Command c2c` shows `C:\Users\mcarls\AppData\Local\Programs\Python\Python313\Scripts\c2c.exe` when you’re in another repo because that path is earlier in PATH. Functionally it’s fine (same package version), but if you want every shell to use the repo venv, move `C:\Users\mcarls\Repos\scripts\.venv\Scripts` or `C:\Users\mcarls\Repos\scripts\bin` ahead of the global Python3.13 Scripts entry, or uninstall `clipboard_tools` from the global Python.
