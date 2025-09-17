# tests/ingest_test.py
from pathlib import Path
from agt.ingest import materialize_at_refs, render_attachments_block

def test_materialize_at_refs(tmp_path: Path):
    (tmp_path / "a.txt").write_text("content a")
    (tmp_path / "b.txt").write_text("content b")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_text("content c")

    # Test single file
    text, files = materialize_at_refs(f"@{tmp_path / 'a.txt'}", cwd=tmp_path)
    assert text.strip() == ""
    assert len(files) == 1
    assert files[0][0].name == "a.txt"
    assert files[0][1] == "content a"

    # Test glob
    text, files = materialize_at_refs(f"@{tmp_path / '*.txt'}", cwd=tmp_path)
    assert text.strip() == ""
    assert len(files) == 2
    assert {p.name for p, _ in files} == {"a.txt", "b.txt"}

    # Test recursive glob
    text, files = materialize_at_refs(f"@{tmp_path / '**/*.txt'}", cwd=tmp_path)
    assert text.strip() == ""
    assert len(files) == 3
    assert {p.name for p, _ in files} == {"a.txt", "b.txt", "c.txt"}
    
    # Test missing file
    text, files = materialize_at_refs("@nonexistent.txt", cwd=tmp_path)
    assert text == "@nonexistent.txt"
    assert len(files) == 0

def test_render_attachments_block(tmp_path: Path):
    files = [
        (tmp_path / "a.txt", "content a"),
        (tmp_path / "b.txt", "content b"),
    ]
    output = render_attachments_block(files, root_hint=str(tmp_path))
    assert "ReadManyFiles Result" in output
    assert "2 file(s)" in output
    assert "`a.txt`" in output
    assert "`b.txt`" in output
    assert "<<FILE:" in output
    assert "content a" in output
    assert "<<ENDFILE>>" in output
