# File: scripts/pyscripts/tests/test_unify_shell_ls_yaml.py
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import unify_shell as us  # noqa: E402


def test_directory_loader_merges_yaml(tmp_path, monkeypatch):
    # create directory with aliases.yml + ls.yml
    unified = tmp_path / "unified"
    unified.mkdir()
    (unified / "aliases.yml").write_text("""
- name: mkcd
  desc: python mkcd
  python_impl: mkcd
""", encoding="utf-8")
    (unified / "ls.yml").write_text("""
- name: ll
  desc: eza long
  requires: [eza]
  posix: "eza -l"
  powershell: "eza -l"
""", encoding="utf-8")

    # don't depend on actual eza in PATH during test
    monkeypatch.setattr(us, "_all_requirements_present", lambda reqs: True)

    entries = us.load_aliases(unified)
    names = sorted(e.name for e in entries)
    assert names == ["ll", "mkcd"]

    z = us.generate_zsh(entries)
    p = us.generate_pwsh(entries)
    assert "alias ll='dot run ll'" in z
    assert "function mkcd()" in z
    assert "function ll {" in p
    assert "function mkcd {" in p
