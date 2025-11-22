import rgcodeblock_cli as cli

def test_cli_list_languages(capsys):
    rc = cli.main(["-L"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "python" in out and "brace" in out and "ruby" in out and "lua" in out
