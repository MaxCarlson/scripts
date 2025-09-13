import textwrap
from pathlib import Path
from uocs.uocs_v2 import UOCSApplicator


def w(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(s).lstrip(), encoding="utf-8")


def test_anchor_authoritative_skips_when_not_unique(tmp_path: Path):
    src = tmp_path / "pkg/a.py"
    w(
        src,
        """
    def dup(): return 1
    def dup(): return 2
    """,
    )
    # Anchor appears twice -> must skip (even though AST could match a function by name)
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "anchor-auth-1"},
        "files": [
            {
                "op": "edit",
                "path": "pkg/a.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "delete",
                        "unit": {
                            "kind": "function",
                            "qualified": "pkg.a.dup",
                            "sig_old": "def dup():",
                        },
                        "anchor": {"by": "text", "value": "def dup():", "max_lines": 5},
                    }
                ],
            }
        ],
    }
    res = UOCSApplicator(tmp_path, dry_run=False).apply(doc)
    assert any(r.status == "skipped" for r in res)
    assert src.read_text(encoding="utf-8").count("def dup()") == 2


def test_anchor_unique_allows_delete(tmp_path: Path):
    src = tmp_path / "pkg/b.py"
    w(
        src,
        """
    def keep(): return 0
    def kill(): return 1
    """,
    )
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "anchor-auth-2"},
        "files": [
            {
                "op": "edit",
                "path": "pkg/b.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "delete",
                        "unit": {
                            "kind": "function",
                            "qualified": "pkg.b.kill",
                            "sig_old": "def kill():",
                        },
                        "anchor": {
                            "by": "text",
                            "value": "def kill():",
                            "max_lines": 3,
                        },
                    }
                ],
            }
        ],
    }
    res = UOCSApplicator(tmp_path, dry_run=False).apply(doc)
    t = src.read_text(encoding="utf-8")
    assert any(r.status == "applied" for r in res)
    assert "def kill()" not in t and "def keep()" in t
