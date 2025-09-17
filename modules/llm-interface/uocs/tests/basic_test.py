import textwrap
from pathlib import Path
from uocs.uocs_v2 import UOCSApplicator


def w(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(s).lstrip(), encoding="utf-8")


def test_replace_function_simple(tmp_path: Path):
    src = tmp_path / "app/mod.py"
    w(
        src,
        """
    def foo(a, b):
        return a + b
    """,
    )

    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "basic-1"},
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
                            "sig_old": "def foo(a, b):",
                        },
                        "new": {
                            "sig": "def foo(a, b, c=0):",
                            "code": "def foo(a, b, c=0):\n    return a+b+c\n",
                        },
                    }
                ],
            }
        ],
    }

    app = UOCSApplicator(tmp_path, dry_run=False)
    res = app.apply(doc)
    assert any(r.status == "applied" for r in res)
    assert "def foo(a, b, c=0):" in src.read_text(encoding="utf-8")


def test_insert_after_symbol_then_delete(tmp_path: Path):
    src = tmp_path / "app/mod.py"
    w(
        src,
        """
    def setup():
        return 1
    """,
    )

    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "basic-2"},
        "files": [
            {
                "op": "edit",
                "path": "app/mod.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "insert",
                        "unit": {"kind": "function", "qualified": "app.mod.run"},
                        "where": {"insert": "after_symbol", "symbol": "app.mod.setup"},
                        "new": {
                            "sig": "def run():",
                            "code": "def run():\n    return 0\n",
                        },
                    },
                    {
                        "op": "delete",
                        "unit": {
                            "kind": "function",
                            "qualified": "app.mod.setup",
                            "sig_old": "def setup():",
                        },
                    },
                ],
            }
        ],
    }

    app = UOCSApplicator(tmp_path, dry_run=False)
    res = app.apply(doc)
    text = src.read_text(encoding="utf-8")
    assert any(r.status == "applied" for r in res)
    assert "def setup()" not in text
    assert "def run()" in text


def test_new_delete_rename_file(tmp_path: Path):
    nf = tmp_path / "pkg/util.py"
    old = tmp_path / "obsolete.py"
    w(old, "print('x')\n")

    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "basic-3"},
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
    app = UOCSApplicator(tmp_path, dry_run=False)
    res = app.apply(doc)
    assert [r.status for r in res] == ["applied", "applied", "applied"]
    assert (tmp_path / "pkg/util2.py").exists()
    assert not (tmp_path / "pkg/util.py").exists()
    assert not old.exists()


def test_noop_when_already_applied(tmp_path: Path):
    src = tmp_path / "app/mod.py"
    w(
        src,
        """
    def foo(a, b, c=0):
        return a+b+c
    """,
    )
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "basic-4"},
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
                            "sig_old": "def foo(a, b, c=0):",
                        },
                        "new": {
                            "sig": "def foo(a, b, c=0):",
                            "code": "def foo(a, b, c=0):\n    return a+b+c\n",
                        },
                    }
                ],
            }
        ],
    }
    res = UOCSApplicator(tmp_path, dry_run=False).apply(doc)
    assert any(r.status in ("noop", "applied") for r in res)
