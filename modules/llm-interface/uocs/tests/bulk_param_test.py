import textwrap
from pathlib import Path
from uocs.uocs_v2 import UOCSApplicator


def w(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(s).lstrip(), encoding="utf-8")


def test_bulk_edits_across_many_files(tmp_path: Path):
    # Generate 40 files across 5 subfolders, 5 functions each = 200 functions
    file_paths = []
    for sub in range(5):
        for f in range(8):
            rel = f"pkg{sub}/mod{f}.py"
            file_paths.append(rel)
            body = []
            for i in range(5):
                body.append(f"def f{i}(a, b):\n    return a+b\n")
            w(tmp_path / rel, "\n".join(body))

    # Build UOCS doc with ~200 replaces (add c=0), plus 40 inserts and 40 deletes
    files_ops = []
    for rel in file_paths:
        unit_ops = []
        # Replace all f0..f4
        for i in range(5):
            unit_ops.append(
                {
                    "op": "replace",
                    "unit": {
                        "kind": "function",
                        "qualified": f"{rel.replace('/','.')[:-3]}.f{i}",
                        "sig_old": f"def f{i}(a, b):",
                    },
                    "new": {
                        "sig": f"def f{i}(a, b, c=0):",
                        "code": f"def f{i}(a, b, c=0):\n    return a+b+c\n",
                    },
                }
            )
        # Insert new function at bottom
        unit_ops.append(
            {
                "op": "insert",
                "unit": {
                    "kind": "function",
                    "qualified": f"{rel.replace('/','.')[:-3]}.g",
                },
                "where": {"insert": "bottom"},
                "new": {"sig": "def g():", "code": "def g():\n    return 42\n"},
            }
        )
        # Delete f4 to simulate churn
        unit_ops.append(
            {
                "op": "delete",
                "unit": {
                    "kind": "function",
                    "qualified": f"{rel.replace('/','.')[:-3]}.f4",
                    "sig_old": "def f4(a, b):",
                },
            }
        )
        files_ops.append(
            {"op": "edit", "path": rel, "language": "python", "unit_ops": unit_ops}
        )

    doc = {"uocs_version": "2.0", "meta": {"id": "bulk-1"}, "files": files_ops}
    res = UOCSApplicator(tmp_path, dry_run=False).apply(doc)

    # Make sure we applied a lot of ops
    applied = sum(1 for r in res if r.status == "applied")
    assert applied >= 200  # at least the replacements should land

    # Spot-check a few random files
    check = tmp_path / "pkg3/mod5.py"
    t = check.read_text(encoding="utf-8")
    assert "def f0(a, b, c=0)" in t
    assert "def g()" in t
    assert "def f4(" not in t
