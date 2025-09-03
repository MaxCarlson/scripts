import scripts.modules.code_tools.unpaired_finder as uf

def test_cli_ok_and_errors(tmp_path, capsys):
    p = tmp_path / "ok.txt"
    p.write_text("(a[b]{c})\n")
    rc_ok = uf.main([str(p)])
    assert rc_ok == 0
    out_ok = capsys.readouterr().out
    assert "No brace issues" in out_ok

    p2 = tmp_path / "bad.txt"
    p2.write_text("(a[b]{c}\n")
    rc_bad = uf.main([str(p2)])
    assert rc_bad == 1
    out_bad = capsys.readouterr().out
    assert "Unpaired open" in out_bad or "Lines with unpaired openings" in out_bad

    rc_nf = uf.main([str(p2.parent / 'missing.txt')])
    assert rc_nf == 2
