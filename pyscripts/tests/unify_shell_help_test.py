# File: scripts/pyscripts/tests/test_unify_shell_help.py
import sys
from io import StringIO
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import unify_shell as us  # noqa: E402


def test_list_filters_and_sorts(monkeypatch, capsys):
    entries = [
        us.Entry(name="zeta", desc="last"),
        us.Entry(name="alpha", desc="first"),
        us.Entry(name="gitlog", desc="git log"),
    ]
    # requirements satisfied
    monkeypatch.setattr(us, "_all_requirements_present", lambda reqs: True)

    # no filter → alpha, gitlog, zeta (sorted)
    rc = us.py_list([], entries)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("alpha")
    assert out.splitlines()[1].startswith("gitlog")
    assert out.splitlines()[2].startswith("zeta")

    # filter by substring 'git'
    rc = us.py_list(["git"], entries)
    assert rc == 0
    out = capsys.readouterr().out
    lines = out.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("gitlog")
