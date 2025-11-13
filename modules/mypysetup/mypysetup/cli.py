# mypysetup/cli.py
from __future__ import annotations
import argparse, os
from .installer import (
    status, install_missing, ensure_global_python, profile_paths,
    ensure_path_hint_lines, has_profile_lines, append_profile_lines,
    check_py_alignment, list_windows_py_versions, which, sysu
)
from .projects import create_project

def build_parser():
    p = argparse.ArgumentParser(
        prog="mps",
        description="mypysetup — cross-platform Python setup helper (uv/pipx/micromamba) + project bootstrap.",
    )
    # Status / Install
    p.add_argument("-S", "--status", action="store_true", help="Show tool and environment status.")
    p.add_argument("-I", "--install", action="store_true", help="Install missing tools (uv, pipx, micromamba).")
    # Project creation
    p.add_argument("-C", "--create", metavar="NAME", help="Create a new project folder.")
    p.add_argument("-k", "--kind", default="uv", choices=["uv","venv","none"], help="Project environment kind.")
    p.add_argument("-V", "--venv-dir", default=".venv", help="Venv dir name (when -k venv).")
    # Profile assistance
    p.add_argument("-P", "--patch-profile", action="store_true", help="Offer to patch profile files for PATH/completions.")
    # Print commands cheat-sheet
    p.add_argument("-p", "--print-cmds", action="store_true", help="Print basic commands to use the setup on this OS.")
    return p

def _print_kv(d: dict, indent=""):
    for k,v in d.items():
        if isinstance(v, dict):
            print(f"{indent}{k}:")
            _print_kv(v, indent+"  ")
        else:
            print(f"{indent}{k}: {v}")

def _maybe_align_py():
    align = check_py_alignment()
    if align["aligned"] is True:
        print(f"[OK] py launcher matches python: {align['python']}")
        return
    if align["aligned"] is False and align["python"] and align["py"]:
        print(f"[WARN] py ({align['py']}) != python ({align['python']}).")
        if os.name == "nt":
            versions = list_windows_py_versions()
            if versions:
                print("py launcher versions (py -0p):")
                for v,p in versions: print(f"  {v:<5} {p}")
            ans = input(f"Set user env to prefer {align['suggest_env']}? [y/N]: ").strip().lower()
            if ans == "y":
                pwsh, _ = profile_paths()
                lines = [f'$env:PY_PYTHON="{align["suggest_env"].split("=")[1]}"  # make py default version match python']
                if pwsh:
                    _patch_if_missing(pwsh, lines)
                    print(f"[OK] Proposed PY_PYTHON added to {pwsh}")
                else:
                    print("[INFO] Could not locate $PROFILE automatically; add manually:\n  " + lines[0])
        else:
            print("[INFO] Non-Windows: py alignment not applicable.")
    else:
        print("[INFO] Could not determine py/python alignment (one missing).")

def _patch_if_missing(profile_path, lines):
    markers = [ln.strip() for ln in lines]
    print(f"\nProfile: {profile_path}")
    for ln in lines: print("  + " + ln)
    if has_profile_lines(profile_path, markers):
        print("[SKIP] Detected similar lines already in profile.")
        return
    ans = input("Append these lines to your profile? [y/N]: ").strip().lower()
    if ans == "y":
        append_profile_lines(profile_path, lines)
        print("[OK] Appended.")

def _print_cmds():
    osname = sysu.os_name
    print(f"# Basic commands for {osname}\n")

    print("## Project creation")
    print("mps -C demo -k uv -V .venv    # uv-managed project with .venv")
    print("mps -C demo -k venv -V .venv  # stdlib venv")
    print("mps -C demo -k none           # no venv (system python)\n")

    print("## Tooling quickstart")
    print("mps -I                        # install missing uv/pipx/micromamba")
    print("mps -S                        # show status\n")

    if osname == "windows":
        print("## PowerShell profile (no '&&' in pwsh)")
        print("mps -P")
        print(" # Adds user bin PATH and uv completions to $PROFILE if approved.\n")
        print("## py launcher alignment")
        print("mps -I                        # then follow prompts to align 'py' with 'python'\n")
        print("## pipx")
        print("py -m pipx install ruff")
        print("py -m pipx ensurepath\n")
        print("## uv basics")
        print("uv add requests               # add a dep")
        print("uv add --group dev ruff pytest")
        print("uv sync                       # lock & install")
        print("uv run pytest -q\n")
        print("## micromamba (heavy DS stacks)")
        print("micromamba create -y -n ds -c conda-forge python=3.12 numpy scipy")
        print("micromamba activate ds")
        print("pip install polars\n")
    else:
        print("## Shell profile")
        print('mps -P                        # adds ~/.local/bin to PATH and uv completions')
        print("source ~/.zshrc   # or ~/.bashrc\n")
        print("## pipx")
        print("python3 -m pip install --user pipx")
        print("~/.local/bin/pipx ensurepath\n")
        print("## uv basics")
        print("uv add requests")
        print("uv add --group dev ruff pytest")
        print("uv sync")
        print("uv run pytest -q\n")
        print("## micromamba (heavy DS stacks)")
        print("micromamba create -y -n ds -c conda-forge python=3.12 numpy scipy")
        print("micromamba activate ds")
        print("pip install polars\n")

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    acted = False

    if args.print_cmds:
        _print_cmds()
        acted = True

    if args.status:
        st = status()
        _print_kv(st)
        acted = True

    if args.install:
        if not (which_py := ensure_global_python()):
            print("[INFO] Skipped tool install because no global Python is available (or install cancelled).")
        res = install_missing()
        print("\n[Install results]")
        _print_kv(res)
        _maybe_align_py()
        acted = True

    if args.patch_profile:
        pwsh, bash = profile_paths()
        path_lines = ensure_path_hint_lines()
        pwsh_lines = path_lines + ["(& uv generate-shell-completion powershell) | Out-String | Invoke-Expression"]
        bash_lines = path_lines + ["eval \"$(uv generate-shell-completion zsh)\"  # change to bash if needed"]
        if pwsh: _patch_if_missing(pwsh, pwsh_lines)
        if bash:  _patch_if_missing(bash, bash_lines)
        acted = True

    if args.create:
        res = create_project(args.create, kind=args.kind, venv_dir=args.venv_dir)
        print("\n[Create results]")
        _print_kv(res)
        acted = True

    if acted:
        return 0

    # Default: show status summary
    st = status()
    _print_kv(st)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
