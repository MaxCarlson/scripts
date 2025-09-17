# File: scripts/pyscripts/tests/test_unify_shell_lt.py
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import unify_shell as us  # noqa: E402


def test_codegen_wraps_python_impl_function():
    entries = [
        us.Entry(name="lt", desc="tree view", python_impl="lt"),
    ]
    zsh = us.generate_zsh(entries)
    pw = us.generate_pwsh(entries)
    assert "function lt()" in zsh
    assert "function lt" in pw


def test_py_lt_python_fallback(tmp_path, monkeypatch, capsys):
    # Ensure eza/tree not used so we hit fallback
    monkeypatch.setattr(us, "_have", lambda name: False)

    # Build a small tree:
    # root/
    #   a/
    #     a1/
    #   b/
    (tmp_path / "a" / "a1").mkdir(parents=True)
    (tmp_path / "b").mkdir(parents=True)

    # depth 1 should include 'a' and 'b' but not 'a/a1'
    rc = us.py_lt(["1", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "a" in out
    assert "b" in out
    assert "a/a1" not in out

    # depth 2 should now include a/a1
    rc = us.py_lt(["2", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "a/a1" in out
