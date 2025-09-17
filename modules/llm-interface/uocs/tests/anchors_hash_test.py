import textwrap
from pathlib import Path
from uocs.uocs_v2 import UOCSApplicator, sha256_normalized_block


def w(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(s).lstrip(), encoding="utf-8")


def test_anchor_requires_unique_match(tmp_path: Path):
    src = tmp_path / "a/mod.py"
    w(
        src,
        """
    def dup(): pass
    def dup(): pass
    """,
    )
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "ah-1"},
        "files": [
            {
                "op": "edit",
                "path": "a/mod.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "delete",
                        "unit": {
                            "kind": "function",
                            "qualified": "a.mod.dup",
                            "sig_old": "def dup():",
                        },
                        "anchor": {"by": "text", "value": "def dup():", "max_lines": 3},
                    }
                ],
            }
        ],
    }
    res = UOCSApplicator(tmp_path, dry_run=False).apply(doc)
    # Should skip due to non-unique anchor (appears twice)
    assert any(r.status == "skipped" for r in res)
    assert src.read_text(encoding="utf-8").count("def dup()") == 2


def test_old_hash_allows_sig_mismatch(tmp_path: Path):
    src = tmp_path / "a/m.py"
    content = """
    def foo(a, b):
        return a+b
    """
    w(src, content)
    old_hash = sha256_normalized_block(
        textwrap.dedent(content).lstrip().splitlines(True)[0] + "        return a+b\n"
    )
    # Build doc where sig_old won't match, but old_hash should
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "ah-2"},
        "files": [
            {
                "op": "edit",
                "path": "a/m.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "replace",
                        "unit": {
                            "kind": "function",
                            "qualified": "a.m.foo",
                            "sig_old": "def foo(x, y):",
                            "old_hash": old_hash,
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
    assert any(r.status == "applied" for r in res)
    assert "def foo(a, b, c=0):" in src.read_text(encoding="utf-8")


def test_anchor_line_limit(tmp_path: Path):
    src = tmp_path / "a/m.py"
    w(
        src,
        """
    def target():
        x = 1
        y = 2
        z = 3
        w = 4
    """,
    )
    # anchor longer than max_lines should be rejected
    long_anchor = "def target():\n    x = 1\n    y = 2\n    z = 3\n    w = 4\n    q = 5"
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "ah-3"},
        "files": [
            {
                "op": "edit",
                "path": "a/m.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "delete",
                        "unit": {
                            "kind": "function",
                            "qualified": "a.m.target",
                            "sig_old": "def target():",
                        },
                        "anchor": {"by": "text", "value": long_anchor, "max_lines": 5},
                    }
                ],
            }
        ],
    }
    res = UOCSApplicator(tmp_path, dry_run=False).apply(doc)
    assert any(r.status == "skipped" for r in res)
    assert "def target()" in src.read_text(encoding="utf-8")
