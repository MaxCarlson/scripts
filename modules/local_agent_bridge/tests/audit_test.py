"""Regression checks for the independent 2.0.0 audit; never call local models."""
import json
from pathlib import Path
import os
import shutil
import subprocess

import pytest

from local_agent_bridge import cli
from local_agent_bridge.commands import build_parser


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'HOME_DIR', tmp_path)
    for name, relative in {
        'OPENCODE_CONFIG_PATH': '.config/opencode/opencode.json',
        'CODEX_CONFIG_PATH': '.codex/config.toml',
        'AGY_GLOBAL_MCP_PATH': '.gemini/config/mcp_config.json',
        'AGY_CLI_MCP_PATH': '.gemini/antigravity-cli/mcp_config.json',
        'AGY_CLI_SETTINGS_PATH': '.gemini/antigravity-cli/settings.json',
        'AGY_GLOBAL_CONFIG_PATH': '.gemini/config/config.json',
    }.items():
        monkeypatch.setattr(cli, name, tmp_path / relative)
    monkeypatch.setattr(cli, 'get_loaded_instance', lambda _: (None, ''))
    monkeypatch.setattr(cli, 'AGY_MCP_CACHE_DIRS', [])
    return cli.OPENCODE_CONFIG_PATH


def write_models(path, active='one', **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        'provider': {'lmstudio': {'models': {'one': {'name': 'first'}, 'two': {'name': 'second'}}}},
        'model': 'lmstudio/' + active, **extra,
    }))


def test_cli_uses_requested_name_and_examples():
    text = build_parser().format_help()
    assert 'usage: local-agent ' in text
    assert 'How to setup Global AGENTS.md and other LLM files' in text
    assert 'local-agent run -M qwen38_23GB' in text
    assert 'local-agent run' in cli.build_parser(runtime_only=True).format_help()


def test_rename_refuses_existing_alias_without_mutation(runtime):
    write_models(runtime)
    before = runtime.read_bytes()
    with pytest.raises(RuntimeError, match='already exists'):
        cli.handle_rename_model('one', 'two', 1234, 4096)
    assert runtime.read_bytes() == before


def test_remove_last_alias_preserves_unrelated_opencode_settings(runtime):
    write_models(runtime, permission={'bash': 'ask'}, agent={'custom': {'description': 'keep'}})
    data = json.loads(runtime.read_text())
    del data['provider']['lmstudio']['models']['two']
    runtime.write_text(json.dumps(data))
    cli.handle_delete_model('one', 4096)
    remaining = json.loads(runtime.read_text())
    assert remaining['permission'] == {'bash': 'ask'}
    assert remaining['agent']['custom']['description'] == 'keep'
    assert 'model' not in remaining


def test_remove_unknown_alias_has_no_side_effects(runtime, monkeypatch):
    write_models(runtime)
    before = runtime.read_bytes()
    monkeypatch.setattr(cli, 'get_loaded_instance', lambda _: pytest.fail('must validate alias first'))
    with pytest.raises(RuntimeError, match='does not exist'):
        cli.handle_delete_model('missing', 4096)
    assert runtime.read_bytes() == before


def test_remove_inactive_alias_keeps_active_bridge(runtime, monkeypatch):
    write_models(runtime, active='two')
    selected = []
    monkeypatch.setattr(cli, 'update_codex_mcp_toml', lambda nick, _: selected.append(nick))
    monkeypatch.setattr(cli, 'update_agy_mcp_configs', lambda nick, _: selected.append(nick))
    cli.handle_delete_model('one', 4096)
    assert selected == []


def test_runtime_added_model_field_is_removed_with_owned_bridge(tmp_path):
    from local_agent_bridge.setup.installer import apply_plan, remove_installation
    from local_agent_bridge.setup.planner import build_plan
    from local_agent_bridge.setup.runtime_config import save_codex
    home = tmp_path / 'home'
    apply_plan(build_plan(home, clients=('codex',), strategy='copy', environ={}))
    config = home / '.codex/config.toml'
    save_codex(config, 'new-alias', 4096, home)
    assert remove_installation(home, clients=('codex',), execute=True, environ={})['code'] == 0
    assert not config.exists() or 'opencode_worker' not in config.read_text()


def test_disabled_codex_bridge_is_not_reported_enabled(runtime, monkeypatch, capsys):
    cli.CODEX_CONFIG_PATH.parent.mkdir(parents=True)
    cli.CODEX_CONFIG_PATH.write_text('[mcp_servers.opencode_worker]\nenabled = false\n')
    monkeypatch.setattr(cli, 'parse_lms_variants', lambda: ('models', [], []))
    monkeypatch.setattr(cli, 'run_cmd', lambda *a, **k: type('Result', (), {'stdout': ''})())
    cli.handle_ls_command()
    output = capsys.readouterr().out
    assert "'opencode_worker' disabled" in output
    assert "'opencode_worker' enabled" not in output


def test_codex_defaults_have_only_history_keys_in_history(tmp_path):
    import tomllib
    from local_agent_bridge.setup.installer import apply_plan
    from local_agent_bridge.setup.planner import build_plan
    home = tmp_path / 'home'
    apply_plan(build_plan(home, clients=('codex',), mode='generic', strategy='copy', environ={}))
    config = tomllib.loads((home / '.codex/config.toml').read_text())
    assert set(config['history']) <= {'persistence', 'max_bytes'}
    assert config['file_opener'] == 'vscode'
    assert config['project_doc_fallback_filenames'] == ['CLAUDE.md', 'GEMINI.md']


def test_shell_hook_preserves_paths_with_spaces(tmp_path):
    shell = shutil.which('sh') or ('C:/Program Files/Git/bin/sh.exe' if os.name == 'nt' else None)
    if not shell or not Path(shell).exists():
        pytest.skip('POSIX shell unavailable')
    home = tmp_path / 'home with spaces'
    output = tmp_path / 'plan with spaces.json'
    hook = Path(__file__).resolve().parents[1] / 'integrations/setup-agents.sh'
    result = subprocess.run([shell, str(hook), '--dry-run', '-m', 'generic', '-s', 'copy',
                             '-H', str(home), '-o', str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())['home'] == str(home)
    assert not home.exists()


def test_powershell_environment_dry_run_never_applies(tmp_path):
    shell = shutil.which('pwsh')
    if not shell:
        pytest.skip('PowerShell unavailable')
    hook = Path(__file__).resolve().parents[1] / 'integrations/setup-agents.ps1'
    script = tmp_path / 'probe.ps1'
    script.write_text('function global:local-agent { $args | ConvertTo-Json -Compress }\n'
                      'function global:local_agent { $args | ConvertTo-Json -Compress }\n'
                      '& $env:AUDIT_HOOK -Mode generic\n')
    result = subprocess.run([shell, '-NoProfile', '-File', str(script)], text=True, capture_output=True,
                            env={**os.environ, 'DOTFILES_DRY_RUN': '1', 'AUDIT_HOOK': str(hook)})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[:2] == ['setup', 'plan']


def test_shell_mode_comes_from_receipt_modes_only(tmp_path):
    shell = shutil.which('sh') or ('C:/Program Files/Git/bin/sh.exe' if os.name == 'nt' else None)
    if not shell or not Path(shell).exists():
        pytest.skip('POSIX shell unavailable')
    shell_home = tmp_path / 'shell-home'
    receipt = shell_home / '.local/share/local-agent/receipt.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({'modes': {'codex': 'generic', 'agy': 'generic'}, 'unrelated': 'local'}))
    output = tmp_path / 'plan.json'
    hook = Path(__file__).resolve().parents[1] / 'integrations/setup-agents.sh'
    result = subprocess.run([shell, str(hook), '--dry-run', '-s', 'copy', '-H', str(tmp_path / 'target'),
                             '-o', str(output)], capture_output=True, text=True,
                            env={**os.environ, 'HOME': str(shell_home)})
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())['mode'] == 'generic'


def test_runtime_custom_port_survives_setup_status(tmp_path):
    from local_agent_bridge.setup.installer import apply_plan
    from local_agent_bridge.setup.planner import build_plan
    from local_agent_bridge.setup.runtime_config import save_codex, save_json
    home = tmp_path / 'home'
    oc = home / '.config/opencode/opencode.json'
    oc.parent.mkdir(parents=True)
    oc.write_text('{"model":"lmstudio/one"}')
    apply_plan(build_plan(home, strategy='copy', environ={}))
    save_codex(home / '.codex/config.toml', 'one', 5001, home)
    for relative in ['.gemini/config/mcp_config.json', '.gemini/antigravity-cli/mcp_config.json']:
        path = home / relative
        data = json.loads(path.read_text())
        data['mcpServers']['opencode_worker']['env']['OPENCODE_BASE_URL'] = 'http://127.0.0.1:5001'
        save_json(path, data, home)
    plan = build_plan(home, strategy='copy', environ={})
    assert not plan.conflicts
    assert all(op.action == 'unchanged' for op in plan.operations)


def test_runtime_paths_honor_setup_environment(tmp_path):
    import sys
    result = subprocess.run([sys.executable, '-c',
        'import json;from local_agent_bridge import cli;'
        'print(json.dumps([str(cli.CODEX_CONFIG_PATH),str(cli.OPENCODE_CONFIG_PATH)]))'],
        capture_output=True, text=True, env={**os.environ,
            'CODEX_HOME': str(tmp_path / 'codex'), 'XDG_CONFIG_HOME': str(tmp_path / 'xdg')})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [str(tmp_path / 'codex/config.toml'),
                                       str(tmp_path / 'xdg/opencode/opencode.json')]


@pytest.mark.parametrize('damage', ['missing', 'corrupt'])
def test_removal_rejects_bad_backup_before_touching_profile(tmp_path, damage):
    from local_agent_bridge.setup.installer import apply_plan, remove_installation
    from local_agent_bridge.setup.planner import build_plan
    home = tmp_path / 'home'
    profile = home / '.codex/AGENTS.md'
    profile.parent.mkdir(parents=True)
    profile.write_text('Original personal rules\n')
    apply_plan(build_plan(home, clients=('codex',), strategy='copy',
                          adopt=('codex.instructions',), environ={}))
    installed = profile.read_bytes()
    receipt = json.loads((home / '.local/share/local-agent/receipt.json').read_text())
    backup = Path(receipt['resources']['codex.instructions']['original']['backup'])
    if damage == 'missing':
        backup.unlink()
    else:
        backup.write_text('damaged backup')
    result = remove_installation(home, clients=('codex',), execute=True, environ={})
    assert result['code'] == 3
    assert profile.read_bytes() == installed


def test_bootstrap_rejects_mixed_modes(tmp_path):
    from local_agent_bridge.setup.bootstrap import receipt_mode
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'modes': {'codex': 'local', 'agy': 'generic'}}))
    assert receipt_mode(receipt, ['codex']) == 'local'
    assert receipt_mode(receipt, ['agy']) == 'generic'
    with pytest.raises(ValueError, match='Mixed'):
        receipt_mode(receipt, ['codex', 'agy'])


def test_user_changed_defaults_are_preserved_and_relinquished(tmp_path):
    import tomllib
    from local_agent_bridge.setup.installer import apply_plan, remove_installation
    from local_agent_bridge.setup.planner import build_plan
    home = tmp_path / 'home'
    apply_plan(build_plan(home, clients=('codex',), mode='generic', strategy='copy', environ={}))
    config = home / '.codex/config.toml'
    config.write_text(config.read_text().replace('approval_policy = "untrusted"', 'approval_policy = "on-request"', 1))
    plan = build_plan(home, clients=('codex',), mode='generic', strategy='copy', environ={})
    assert not plan.conflicts
    apply_plan(plan)
    assert remove_installation(home, clients=('codex',), execute=True, environ={})['code'] == 0
    assert tomllib.loads(config.read_text())['approval_policy'] == 'on-request'


def test_legacy_history_settings_move_to_root_without_overriding_user_values(tmp_path):
    import tomllib
    from local_agent_bridge.setup.installer import apply_plan, remove_installation
    from local_agent_bridge.setup.planner import build_plan
    home = tmp_path / 'home'
    config = home / '.codex/config.toml'
    config.parent.mkdir(parents=True)
    original = 'file_opener="cursor"\n[history]\npersistence="save-all"\nfile_opener="vscode"\nhide_agent_reasoning=true\n'
    config.write_text(original)
    apply_plan(build_plan(home, clients=('codex',), mode='generic', strategy='copy', environ={}))
    parsed = tomllib.loads(config.read_text())
    assert set(parsed['history']) == {'persistence'}
    assert parsed['file_opener'] == 'cursor'
    assert parsed['hide_agent_reasoning'] is True
    again = build_plan(home, clients=('codex',), mode='generic', strategy='copy', environ={})
    assert all(op.action == 'unchanged' for op in again.operations)
    apply_plan(again)
    assert remove_installation(home, clients=('codex',), execute=True, environ={})['code'] == 0
    assert tomllib.loads(config.read_text()) == tomllib.loads(original)


@pytest.mark.parametrize('healthy', [True, False])
def test_run_does_not_kill_or_accept_an_existing_unusable_server(monkeypatch, healthy):
    monkeypatch.setattr(cli, 'http_get_json', lambda _: {'healthy': healthy})
    monkeypatch.setattr(cli, 'verify_opencode_provider', lambda *a: (False, 'stale model'))
    monkeypatch.setattr(cli, 'stop_process_on_port_windows', lambda _: pytest.fail('must not kill an unowned server'))
    monkeypatch.setattr(cli.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not start over an existing service'))
    monkeypatch.setattr(cli.time, 'sleep', lambda _: pytest.fail('must not wait on an unhealthy server'))
    with pytest.raises(RuntimeError, match='already running|unhealthy'):
        cli.run_opencode_server_foreground(4096, 1234, 'one', 'running', True, True)


def test_packaged_archive_hashes_are_current_and_portable():
    import hashlib
    from local_agent_bridge.setup.manifest import assets
    root = assets()
    manifest = json.loads((root / 'migration.json').read_text())
    assert manifest['packaged_hash_normalization'] == 'CRLF to LF'
    for item in manifest['files']:
        data = (root / 'dotfiles_llms' / item['path']).read_bytes().replace(b'\r\n', b'\n')
        assert hashlib.sha256(data).hexdigest() == item['packaged_sha256'], item['path']
