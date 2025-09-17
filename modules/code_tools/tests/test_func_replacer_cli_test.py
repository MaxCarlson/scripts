import scripts.modules.code_tools.func_replacer as fr

def test_cli_with_source_file_and_no_backup(tmp_path, capsys):
    target = tmp_path / "t.py"
    target.write_text("def a():\n  return 1\n")
    src = tmp_path / "src.py"
    src.write_text("def a():\n  return 9\n")
    rc = fr.main([str(target), "-s", str(src), "-y", "-B"])
    assert rc == 0
    assert "Replaced lines" in capsys.readouterr().out
    assert not (tmp_path / "t.py.bak").exists()

def test_cli_clipboard_success_and_failure(tmp_path, monkeypatch):
    target = tmp_path / "t.rb"
    target.write_text("def a\n  1\nend\n")

    class DummyClip:
        @staticmethod
        def paste():
            return "def a\n  2\nend\n"
    monkeypatch.setattr(fr, "pyperclip", DummyClip)
    rc = fr.main([str(target), "-y"])
    assert rc == 0

    class BadClip:
        @staticmethod
        def paste():
            raise RuntimeError("clipboard fail")
    monkeypatch.setattr(fr, "pyperclip", BadClip)
    rc2 = fr.main([str(target)])
    assert rc2 != 0
