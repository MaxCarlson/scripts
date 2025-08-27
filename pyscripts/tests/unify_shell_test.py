# File: scripts/pyscripts/tests/test_unify_shell.py
import textwrap
from pathlib import Path
import yaml
import subprocess
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
import unify_shell as us  # noqa: E402


def write_yaml(tmp_path: Path, items):
    p = tmp_path / "aliases.yml"
    p.write_text(yaml.safe_dump(items), encoding="utf-8")
    return p


def test_load_and_uniqueness(tmp_path):
    y = write_yaml(
        tmp_path,
        [
            {"name": "a", "desc": "x", "posix": "echo hi"},
            {"name": "b", "desc": "y", "powershell": "Write-Host hi"},
        ],
    )
    entries = us.load_aliases(y)
    assert {e.name for e in entries} == {"a", "b"}


def test_duplicate_detection(tmp_path):
    y = write_yaml(tmp_path, [{"name": "a"}, {"name": "a"}])
    try:
        us.load_aliases(y)
        assert False, "Expected duplicate error"
    except ValueError as e:
        assert "Duplicate alias names" in str(e)


def test_codegen_includes_alias_names(tmp_path, monkeypatch):
    y = write_yaml(
        tmp_path,
        [
            {"name": "ll", "desc": "list", "posix": "ls -l"},
            {"name": "mkcd", "desc": "mk and cd", "python_impl": "mkcd"},
        ],
    )
    entries = us.load_aliases(y)
    zsh = us.generate_zsh(entries)
    pw = us.generate_pwsh(entries)
    assert "alias ll='dot run ll'" in zsh
    assert "function mkcd" in zsh
    assert "function ll" in pw
    assert "function mkcd" in pw


def test_py_mkcd_prints_path(tmp_path, capsys):
    rc = us.py_mkcd(["foo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert Path(out).name == "foo"
    assert Path(out).exists()


def test_py_rgmax_works_without_rg(tmp_path, monkeypatch, capsys):
    # simulate no rg on PATH
    monkeypatch.setattr(us, "_have", lambda _: False)
    p = tmp_path / "f.txt"
    p.write_text("hello hello world", encoding="utf-8")
    rc = us.py_rgmax(["hello", "1", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "f.txt" in out
