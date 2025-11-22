import rgcodeblock_cli as cli

def test_search_and_extract_json_and_text_outputs(tmp_path, monkeypatch):
    p = tmp_path / "a.py"
    p.write_text("def f():\n    return x*2\n")
    monkeypatch.setattr(cli, "run_ripgrep", lambda pattern, root, extra: [
        cli.MatchEvent(path=p, line_number=2, lines_text="    return x*2\n", submatches=[(11,14,"x*2")]),
        cli.MatchEvent(path=p, line_number=2, lines_text="    return x*2\n", submatches=[(11,14,"x*2")]),
    ])
    result_json = cli.search_and_extract("x*2", tmp_path, output_format="json")
    assert "results" in result_json and result_json["stats"]["unique_blocks"] == 1
    result_text = cli.search_and_extract("x*2", tmp_path, output_format="text")
    assert "===" in result_text["text"]
    assert "\x1b[" in result_text["text"]

def test_search_and_extract_filters_and_passthrough_args(tmp_path, monkeypatch):
    captured = {}
    def spy(pattern, root, extra):
        captured["pattern"] = pattern
        captured["root"] = str(root)
        captured["extra"] = list(extra)
        return []
    monkeypatch.setattr(cli, "run_ripgrep", spy)
    _ = cli.search_and_extract("needle", tmp_path, include_ext=["py"], exclude_ext=["min.js"], globs=["!node_modules"], extra_args=["--hidden"], output_format="json")
    ex = captured["extra"]
    assert "-g" in ex and any(x.endswith("*.py") for x in ex)
    assert any(x.endswith("!*.min.js") for x in ex)
    assert any(x == "--hidden" for x in ex)

def test_fallback_context_for_unknown_language(tmp_path, monkeypatch):
    p = tmp_path / "a.unk"
    p.write_text("hello\nworld\nneedle here\nbye\n")
    monkeypatch.setattr(cli, "run_ripgrep", lambda pattern, root, extra: [
        cli.MatchEvent(path=p, line_number=3, lines_text="needle here\n", submatches=[(0,6,"needle")]),
    ])
    result = cli.search_and_extract("needle", tmp_path, output_format="json")
    assert "needle" in result["results"][0]["block"]
