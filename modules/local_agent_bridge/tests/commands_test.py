from local_agent_bridge.commands import main
import local_agent_bridge.cli as cli_module


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


def test_gpu_headroom_uses_shared_used_free_and_total_bytes(monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "resolve_executable", lambda _: "nvidia-smi")
    monkeypatch.setattr(
        cli_module,
        "nvidia_gpus",
        lambda **kwargs: [{
            "name": "RTX",
            "mem_used": 4 * 1024**3,
            "mem_free": 8 * 1024**3,
            "mem_total": 12 * 1024**3,
        }],
    )

    cli_module.show_gpu_headroom()

    output = capsys.readouterr().out
    assert "Used: 4.00 GiB (4096 MiB)" in output
    assert "Free Headroom: 8.00 GiB (8192 MiB)" in output
    assert "Total: 12.00 GiB" in output
