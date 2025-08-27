# File: scripts/pyscripts/tests/test_unify_shell_aliases_suite.py
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import unify_shell as us  # noqa: E402


def test_codegen_handles_aliases_and_functions(monkeypatch):
    # Avoid depending on actual presence of tools at test time.
    monkeypatch.setattr(us, "_all_requirements_present", lambda reqs: True)

    entries = [
        us.Entry(name="ll", desc="eza long", posix="eza -l", powershell="eza -l", requires=["eza"]),
        us.Entry(name="lt", desc="tree", python_impl="lt"),
        us.Entry(name="lt2", desc="tree depth 2", posix="lt 2", powershell="lt 2"),
        us.Entry(name="cdf", desc="cd via fd+fzf", posix='cd "$(fd -td . | fzf)"', powershell='$d = (fd.exe -td . | fzf.exe); if ($d) { Set-Location -LiteralPath $d }', requires=["fd", "fzf"]),
        us.Entry(name="glog", desc="git log", posix="git log --oneline", powershell="git log --oneline"),
    ]

    zsh = us.generate_zsh(entries)
    pw  = us.generate_pwsh(entries)

    # Zsh expectations
    assert "alias ll='dot run ll'" in zsh
    assert "function lt()" in zsh
    assert "alias lt2='dot run lt2'" in zsh
    assert "alias cdf='dot run cdf'" in zsh
    assert "alias glog='dot run glog'" in zsh

    # PowerShell expectations
    assert "function ll {" in pw
    assert "function lt {" in pw
    assert "function lt2 {" in pw
    assert "function cdf {" in pw
    assert "function glog {" in pw
