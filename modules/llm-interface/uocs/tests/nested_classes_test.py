import textwrap
from pathlib import Path
from uocs.uocs_v2 import UOCSApplicator


def w(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(s).lstrip(), encoding="utf-8")


def test_delete_method_in_nested_class(tmp_path: Path):
    src = tmp_path / "pkg/nest.py"
    w(
        src,
        """
    class Outer:
        class Inner:
            def m(self): 
                return "x"
    """,
    )
    doc = {
        "uocs_version": "2.0",
        "meta": {"id": "nested-1"},
        "files": [
            {
                "op": "edit",
                "path": "pkg/nest.py",
                "language": "python",
                "unit_ops": [
                    {
                        "op": "delete",
                        "unit": {
                            "kind": "method",
                            "qualified": "pkg.nest.m",
                            "class": "pkg.nest.Inner",
                            "sig_old": "def m(self):",
                        },
                    }
                ],
            }
        ],
    }
    res = UOCSApplicator(tmp_path, dry_run=False).apply(doc)
    t = src.read_text(encoding="utf-8")
    assert any(r.status in ("applied", "noop") for r in res)
    assert "def m(self)" not in t
