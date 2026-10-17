from local_agent_bridge.commands import main


def test_bare_help_and_isolated_plan_do_not_start_services(tmp_path, capsys):
    assert main([]) == 0
    assert 'setup' in capsys.readouterr().out
    home = tmp_path / 'empty'
    assert main(['setup', 'plan', '-H', str(home), '-s', 'copy', '-j']) == 0
    assert not home.exists()
    assert 'schema_version' in capsys.readouterr().out


def test_saved_plan_roundtrip_and_tampering(tmp_path, capsys):
    import json
    home = tmp_path / 'home'
    saved = tmp_path / 'plan.json'
    assert main(['setup', 'plan', '-H', str(home), '-s', 'copy', '-m', 'generic', '-o', str(saved)]) == 0
    assert main(['setup', 'apply', '-i', str(saved)]) == 0
    assert main(['setup', 'status', '-H', str(home), '-s', 'copy']) == 0
    value = json.loads(saved.read_text())
    value['operations'][0]['path'] = str(tmp_path / 'unrelated')
    saved.write_text(json.dumps(value))
    assert main(['setup', 'apply', '-i', str(saved)]) == 4
    assert not (tmp_path / 'unrelated').exists()
    capsys.readouterr()


def test_run_parser_keeps_management_in_model_group():
    from local_agent_bridge.cli import build_parser
    parser = build_parser(runtime_only=True)
    assert parser.parse_args(['-M', 'ls']).nickname == 'ls'
    assert '--delete-model' not in parser.format_help()
