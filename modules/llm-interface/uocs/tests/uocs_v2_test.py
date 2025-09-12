import json
from pathlib import Path
import subprocess
import sys
import textwrap

from uocs.uocs_v2 import UOCSApplicator


def write(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def test_replace_function(tmp_path: Path):
    src = tmp_path / "app/mod.py"
    write(
        src,
        textwrap.dedent(
            """
    def foo(a, b):
        return a + b
    """
        ).lstrip(),
    )

    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "t1"},
        "files": [
            {
                "op": "edit",
                "path": "app/mod.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "replace",
                        "unit": {
                            "kind": "function",
                            "qualified": "app.mod.foo",
                            "class": None,
                            "sig_old": "def foo(a, b):",
                        },
                        "new": {
                            "sig": "def foo(a, b, c=0):",
                            "code": "def foo(a, b, c=0):\n    return a + b + c\n",
                        },
                    }
                ],
            }
        ],
    }

    app = UOCSApplicator(tmp_path, dry_run=False)
    results = app.apply(doc)
    assert any(r.status == "applied" for r in results)
    text = src.read_text(encoding="utf-8")
    assert "def foo(a, b, c=0):" in text


def test_insert_after_symbol(tmp_path: Path):
    src = tmp_path / "app/mod.py"
    write(
        src,
        textwrap.dedent(
            """
    def setup():
        pass

    def other():
        pass
    """
        ).lstrip(),
    )

    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "t2"},
        "files": [
            {
                "op": "edit",
                "path": "app/mod.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "insert",
                        "unit": {
                            "kind": "function",
                            "qualified": "app.mod.run",
                            "class": None,
                        },
                        "where": {"insert": "after_symbol", "symbol": "app.mod.setup"},
                        "new": {
                            "sig": "def run():",
                            "code": "def run():\n    return 0\n",
                        },
                    }
                ],
            }
        ],
    }
    app = UOCSApplicator(tmp_path, dry_run=False)
    results = app.apply(doc)
    assert any(r.status == "applied" for r in results)
    text = src.read_text(encoding="utf-8")
    assert "def run()" in text


def test_delete_function_with_anchor(tmp_path: Path):
    src = tmp_path / "app/mod.py"
    write(
        src,
        textwrap.dedent(
            """
    def dead():
        return 1
    """
        ).lstrip(),
    )

    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "t3"},
        "files": [
            {
                "op": "edit",
                "path": "app/mod.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "delete",
                        "unit": {
                            "kind": "function",
                            "qualified": "app.mod.dead",
                            "sig_old": "def dead():",
                        },
                        "anchor": {
                            "by": "text",
                            "value": "def dead():",
                            "max_lines": 3,
                        },
                    }
                ],
            }
        ],
    }
    app = UOCSApplicator(tmp_path, dry_run=False)
    results = app.apply(doc)
    assert any(r.status == "applied" for r in results)
    text = src.read_text(encoding="utf-8")
    assert "def dead()" not in text


def test_new_delete_rename_file(tmp_path: Path):
    nf = tmp_path / "pkg/util.py"
    df = tmp_path / "obsolete.py"
    write(df, "print('x')\n")
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "t4"},
        "files": [
            {
                "op": "new_file",
                "path": "pkg/util.py",
                "language": "python",
                "content": "def x():\n    return 1\n",
            },
            {"op": "delete_file", "path": "obsolete.py"},
            {"op": "rename_file", "from": "pkg/util.py", "to": "pkg/util2.py"},
        ],
    }
    from uocs.uocs_v2 import UOCSApplicator

    app = UOCSApplicator(tmp_path, dry_run=False)
    results = app.apply(doc)
    statuses = [r.status for r in results]
    assert statuses == ["applied", "applied", "applied"]
    assert (tmp_path / "pkg/util2.py").exists()
    assert not (tmp_path / "pkg/util.py").exists()
    assert not (tmp_path / "obsolete.py").exists()
