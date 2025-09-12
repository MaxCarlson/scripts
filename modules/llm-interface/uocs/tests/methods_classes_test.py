import textwrap
from pathlib import Path
from uocs.uocs_v2 import UOCSApplicator


def w(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(s).lstrip(), encoding="utf-8")


def test_replace_method_with_signature_change(tmp_path: Path):
    src = tmp_path / "m/pkg.py"
    w(
        src,
        """
    class Worker:
        def setup(self, n):
            return n
        def run(self, n):
            return n*2
    """,
    )
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "mc-1"},
        "files": [
            {
                "op": "edit",
                "path": "m/pkg.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "replace",
                        "unit": {
                            "kind": "method",
                            "qualified": "m.pkg.run",
                            "class": "m.pkg.Worker",
                            "sig_old": "def run(self, n):",
                        },
                        "new": {
                            "sig": "def run(self, n: int, *, verbose: bool=False):",
                            "code": "def run(self, n: int, *, verbose: bool=False):\n    return n*2\n",
                        },
                    }
                ],
            }
        ],
    }
    res = UOCSApplicator(tmp_path, dry_run=False).apply(doc)
    text = src.read_text(encoding="utf-8")
    assert any(r.status == "applied" for r in res)
    assert "def run(self, n: int, *, verbose: bool=False):" in text


def test_insert_method_before_symbol(tmp_path: Path):
    src = tmp_path / "m/pkg.py"
    w(
        src,
        """
    class Worker:
        def setup(self): pass
    """,
    )
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "mc-2"},
        "files": [
            {
                "op": "edit",
                "path": "m/pkg.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "insert",
                        "unit": {
                            "kind": "method",
                            "qualified": "m.pkg.Worker.run",
                            "class": "m.pkg.Worker",
                        },
                        "where": {"insert": "before_symbol", "symbol": "m.pkg.setup"},
                        "new": {
                            "sig": "def run(self):",
                            "code": "def run(self):\n    return 0\n",
                        },
                    }
                ],
            }
        ],
    }
    res = UOCSApplicator(tmp_path, dry_run=False).apply(doc)
    text = src.read_text(encoding="utf-8")
    assert any(r.status == "applied" for r in res)
    assert "def run(self)" in text


def test_delete_class(tmp_path: Path):
    src = tmp_path / "m/pkg.py"
    w(
        src,
        """
    class A: 
        def x(self): return 1
    class B:
        def y(self): return 2
    """,
    )
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "mc-3"},
        "files": [
            {
                "op": "edit",
                "path": "m/pkg.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "delete",
                        "unit": {
                            "kind": "class",
                            "qualified": "m.pkg.A",
                            "sig_old": "class A:",
                        },
                    }
                ],
            }
        ],
    }
    res = UOCSApplicator(tmp_path, dry_run=False).apply(doc)
    assert any(r.status == "applied" for r in res)
    t = src.read_text(encoding="utf-8")
    assert "class A" not in t and "class B" in t
