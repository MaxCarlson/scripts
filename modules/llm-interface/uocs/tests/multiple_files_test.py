import textwrap
from pathlib import Path
from uocs.uocs_v2 import UOCSApplicator


def w(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(s).lstrip(), encoding="utf-8")


def make_repo(tmp: Path):
    # Deep tree with multiple modules
    files = {
        "pkg/a.py": """
            def a1(): return 1
            def a2(): return 2
        """,
        "pkg/sub/b.py": """
            def b1(x): return x
        """,
        "pkg/sub/c.py": """
            class C:
                def m(self): return 3
        """,
        "main.py": """
            def main(): return 'ok'
        """,
    }
    for rel, content in files.items():
        w(tmp / rel, content)


def test_multi_file_ops(tmp_path: Path):
    make_repo(tmp_path)
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "mf-1"},
        "files": [
            {
                "op": "edit",
                "path": "pkg/a.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "replace",
                        "unit": {
                            "kind": "function",
                            "qualified": "pkg.a.a2",
                            "sig_old": "def a2():",
                        },
                        "new": {
                            "sig": "def a2()->int:",
                            "code": "def a2()->int:\n    return 20\n",
                        },
                    },
                    {
                        "op": "insert",
                        "unit": {"kind": "function", "qualified": "pkg.a.a3"},
                        "where": {"insert": "bottom"},
                        "new": {
                            "sig": "def a3():",
                            "code": "def a3():\n    return 3\n",
                        },
                    },
                ],
            },
            {
                "op": "edit",
                "path": "pkg/sub/b.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "delete",
                        "unit": {
                            "kind": "function",
                            "qualified": "pkg.sub.b.b1",
                            "sig_old": "def b1(x):",
                        },
                    }
                ],
            },
            {
                "op": "edit",
                "path": "pkg/sub/c.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "replace",
                        "unit": {
                            "kind": "method",
                            "qualified": "pkg.sub.c.C.m",
                            "class": "pkg.sub.c.C",
                            "sig_old": "def m(self):",
                        },
                        "new": {
                            "sig": "def m(self)->int:",
                            "code": "def m(self)->int:\n    return 30\n",
                        },
                    }
                ],
            },
            {
                "op": "edit",
                "path": "main.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "insert",
                        "unit": {"kind": "function", "qualified": "main.helper"},
                        "where": {"insert": "top"},
                        "new": {
                            "sig": "def helper():",
                            "code": "def helper():\n    return 'h'\n",
                        },
                    }
                ],
            },
        ],
    }
    res = UOCSApplicator(tmp_path, dry_run=False).apply(doc)
    statuses = [r.status for r in res]
    # All operations should either apply or noop (depending on normalization)
    assert all(s in ("applied", "noop") for s in statuses)

    # Verify key changes
    assert "def a3()" in (tmp_path / "pkg/a.py").read_text(encoding="utf-8")
    assert "def b1(" not in (tmp_path / "pkg/sub/b.py").read_text(encoding="utf-8")
    assert "def m(self)->int" in (tmp_path / "pkg/sub/c.py").read_text(encoding="utf-8")
    assert "def helper()" in (tmp_path / "main.py").read_text(encoding="utf-8")
