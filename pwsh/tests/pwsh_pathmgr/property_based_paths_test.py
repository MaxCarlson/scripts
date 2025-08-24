import os, platform
from pathlib import Path
import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=50).filter(lambda s: all(c not in s for c in "\0\n\r")))
def test_path_variants_are_printed_safely(repo_root, fake_home, cli, set_shell, s):
    # property test only for printing (no write)
    set_shell("bash")
    weird = repo_root / "scripts" / "bin" / s
    weird.parent.mkdir(parents=True, exist_ok=True)
    weird.mkdir(exist_ok=True)
    p = cli(["-p", "-t", str(weird)])
    assert p.returncode == 0
    out = p.stdout + p.stderr
    assert str(weird) in out
