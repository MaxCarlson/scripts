import textwrap
from pathlib import Path
from uocs.uocs_v2 import UOCSApplicator


def w(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(s).lstrip(), encoding="utf-8")


def test_reapply_is_noop(tmp_path: Path):
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
        "meta": {"id": "noop-1"},
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

    app = UOCSApplicator(tmp_path, dry_run=False)
    first = app.apply(doc)
    second = app.apply(doc)
    assert any(r.status in ("applied", "noop") for r in first)
    assert any(r.status == "noop" for r in second)
