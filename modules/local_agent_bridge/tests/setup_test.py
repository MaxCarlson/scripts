"""Installer contracts exercised only in isolated profile trees."""
import json

import pytest

from local_agent_bridge.setup.installer import apply_plan, remove_installation
from local_agent_bridge.setup.planner import build_plan


def test_fresh_install_repeat_and_remove_preserves_unrelated_config(tmp_path):
    home = tmp_path / 'home'
    plan = build_plan(home, strategy='copy', environ={})
    assert not home.exists()
    assert not plan.conflicts
    apply_plan(plan)
    agents = home / '.codex/AGENTS.md'
    assert agents.read_text().count('local-agent-bridge:begin') == 1
    assert (home / '.gemini/antigravity-cli/skills/local-agent-handoff/SKILL.md').exists()
    assert (home / '.config/opencode/agents/local-reviewer.md').exists()
    again = build_plan(home, strategy='copy', environ={})
    assert all(op.action == 'unchanged' for op in again.operations)
    config = home / '.gemini/antigravity-cli/mcp_config.json'
    data = json.loads(config.read_text())
    data['unrelated'] = {'keep': True}
    config.write_text(json.dumps(data))
    result = remove_installation(home, execute=True, environ={})
    assert result['code'] == 0
    assert json.loads(config.read_text()) == {'unrelated': {'keep': True}}
    assert not (home / '.agents/skills/local-agent-handoff').exists()


def test_unknown_skill_conflicts_and_apply_has_no_partial_effect(tmp_path):
    home = tmp_path / 'home'
    skill = home / '.agents/skills/local-agent-handoff'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('user resource')
    plan = build_plan(home, strategy='copy', environ={})
    assert plan.conflicts
    with pytest.raises(ValueError, match='conflict'):
        apply_plan(plan)
    assert not (home / '.codex/config.toml').exists()
    assert (skill / 'SKILL.md').read_text() == 'user resource'


def test_stale_plan_rejected_before_writes(tmp_path):
    home = tmp_path / 'home'
    plan = build_plan(home, strategy='copy', environ={})
    config = home / '.codex/config.toml'
    config.parent.mkdir(parents=True)
    config.write_text('model = "user-change"\n')
    with pytest.raises(ValueError, match='stale'):
        apply_plan(plan)
    assert config.read_text() == 'model = "user-change"\n'
    assert not (home / '.codex/AGENTS.md').exists()


def test_block_edit_follows_symlink_and_preserves_user_text_on_removal(tmp_path):
    home = tmp_path / 'home'
    target = tmp_path / 'dotfiles-agents.md'
    target.write_text('# Existing instructions\n')
    link = home / '.codex/AGENTS.md'
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('file symlinks require Windows privilege')
    apply_plan(build_plan(home, strategy='copy', environ={}))
    assert link.is_symlink()
    target.write_text(target.read_text() + '\nUser addition\n')
    result = remove_installation(home, execute=True, environ={})
    assert result['code'] == 0
    assert link.is_symlink()
    assert 'User addition' in target.read_text()
    assert 'local-agent-bridge:begin' not in target.read_text()


def test_toml_comments_and_bridge_options_survive(tmp_path):
    home = tmp_path / 'home'
    config = home / '.codex/config.toml'
    config.parent.mkdir(parents=True)
    config.write_text('# personal\nmodel="mine" # keep\n'
                      '[mcp_servers.opencode_worker]\ntool_timeout_sec=91 # extra\n')
    apply_plan(build_plan(home, strategy='copy', environ={}))
    text = config.read_text()
    assert '# personal' in text and 'model="mine" # keep' in text
    assert 'tool_timeout_sec=91 # extra' in text
    assert remove_installation(home, execute=True, environ={})['code'] == 0
    assert 'tool_timeout_sec=91 # extra' in config.read_text()
    assert 'command =' not in config.read_text()


def test_owned_copy_drift_is_preserved(tmp_path):
    home = tmp_path / 'home'
    apply_plan(build_plan(home, strategy='copy', environ={}))
    skill = home / '.agents/skills/local-agent-handoff/SKILL.md'
    skill.write_text('user edit')
    assert build_plan(home, strategy='copy', environ={}).conflicts
    assert remove_installation(home, execute=True, environ={})['code'] == 3
    assert skill.read_text() == 'user edit'


def test_adoption_preserves_active_instructions(tmp_path):
    home = tmp_path / 'home'
    agents = home / '.gemini/GEMINI.md'
    agents.parent.mkdir(parents=True)
    agents.write_text('# Newer active instructions\nKeep my rules.\n')
    apply_plan(build_plan(home, strategy='copy', adopt=('agy.instructions',), environ={}))
    assert 'Keep my rules.' in agents.read_text()
    assert agents.read_text().count('local-agent-bridge:begin') == 1
    assert remove_installation(home, execute=True, environ={})['code'] == 0
    assert agents.read_text() == '# Newer active instructions\nKeep my rules.\n'


def test_rollback_restores_prior_files(tmp_path, monkeypatch):
    from local_agent_bridge.setup import installer
    home = tmp_path / 'home'
    plan = build_plan(home, strategy='copy', environ={})
    original = installer.install_operation
    counter = [0]

    def fail_third(operation, *args, **kwargs):
        counter[0] += 1
        if counter[0] == 3:
            raise OSError('injected write failure')
        return original(operation, *args, **kwargs)

    monkeypatch.setattr(installer, 'install_operation', fail_third)
    with pytest.raises(OSError, match='injected'):
        apply_plan(plan)
    assert not (home / '.codex/AGENTS.md').exists()
    assert not (home / '.codex/config.toml').exists()


def test_saved_plan_summary_does_not_include_config_secrets(tmp_path):
    home = tmp_path / 'home'
    config = home / '.codex/config.toml'
    config.parent.mkdir(parents=True)
    config.write_text('private_token="do-not-print-me"\n')
    summary = json.dumps(build_plan(home, strategy='copy', environ={}).summary())
    assert 'do-not-print-me' not in summary


@pytest.mark.parametrize('strategy', ['copy', 'auto'])
def test_generic_local_generic_switch_keeps_generic_rules(tmp_path, strategy):
    home = tmp_path / 'home'
    apply_plan(build_plan(home, strategy=strategy, mode='generic', environ={}))
    agents = home / '.codex/AGENTS.md'
    assert 'local-agent-bridge:begin' not in agents.read_text()
    assert not (home / '.config/opencode/agents/local-worker.md').exists()
    apply_plan(build_plan(home, strategy=strategy, mode='local', environ={}))
    assert agents.read_text().count('local-agent-bridge:begin') == 1
    apply_plan(build_plan(home, strategy=strategy, mode='generic', environ={}))
    assert '# Global instructions' in agents.read_text()
    assert 'local-agent-bridge:begin' not in agents.read_text()
    assert not (home / '.agents/skills/local-agent-handoff').exists()
    assert not (home / '.config/opencode/agents/local-worker.md').exists()
    assert 'opencode_worker' not in (home / '.codex/config.toml').read_text()
    assert all(op.action == 'unchanged' for op in build_plan(home, strategy=strategy, mode='generic', environ={}).operations)


def test_named_insertion_is_pure_and_requires_unique_slot():
    from local_agent_bridge.setup.profiles import render_template
    source = '# Before\n<!-- local_agent:insert capabilities -->\n# After\n'
    assert render_template(source, {'capabilities': 'FEATURE'}).index('FEATURE') < source.index('# After') + 10
    assert 'FEATURE' not in source
    assert 'FEATURE' not in render_template(source, {})
    with pytest.raises(ValueError, match='one insertion'):
        render_template(source + source, {'capabilities': 'FEATURE'})


def test_current_lock_blocks_installation(tmp_path):
    import os
    home = tmp_path / 'home'
    state = home / '.local/share/local-agent'
    state.mkdir(parents=True)
    (state / 'setup.lock').write_text(json.dumps({'pid': os.getpid()}))
    with pytest.raises(ValueError, match='Another setup process'):
        apply_plan(build_plan(home, strategy='copy', environ={}))
    assert not (home / '.codex/AGENTS.md').exists()


def test_malformed_config_fails_before_writes(tmp_path):
    home = tmp_path / 'home'
    config = home / '.codex/config.toml'
    config.parent.mkdir(parents=True)
    config.write_text('this is not toml')
    plan = build_plan(home, strategy='copy', environ={})
    assert plan.conflicts
    with pytest.raises(ValueError):
        apply_plan(plan)
    assert config.read_text() == 'this is not toml'


def test_runtime_alias_switch_preserves_options_and_receipt(tmp_path):
    from local_agent_bridge.setup.runtime_config import save_codex, save_json
    home = tmp_path / 'home'
    oc = home / '.config/opencode/opencode.json'
    oc.parent.mkdir(parents=True)
    oc.write_text('{"model":"lmstudio/old"}')
    apply_plan(build_plan(home, strategy='copy', environ={}))
    codex = home / '.codex/config.toml'
    codex.write_text(codex.read_text().replace('[mcp_servers.opencode_worker]',
        '[mcp_servers.opencode_worker]\ntool_timeout_sec = 91 # mine'))
    save_json(oc, {'model': 'lmstudio/new'}, home)
    save_codex(codex, 'new', 4096, home)
    # The agy connection is also intentionally switched by the legacy run path.
    for relative in ['.gemini/antigravity-cli/mcp_config.json', '.gemini/config/mcp_config.json']:
        path = home / relative
        data = json.loads(path.read_text())
        data['mcpServers']['opencode_worker']['env']['OPENCODE_DEFAULT_MODEL'] = 'new'
        save_json(path, data, home)
    assert 'tool_timeout_sec = 91 # mine' in codex.read_text()
    assert not build_plan(home, strategy='copy', environ={}).conflicts


def test_unrelated_permission_rule_survives_removal(tmp_path):
    home = tmp_path / 'home'
    apply_plan(build_plan(home, strategy='copy', environ={}))
    path = home / '.gemini/antigravity-cli/settings.json'
    data = json.loads(path.read_text())
    data['permissions']['allow'].append('my-unrelated-rule')
    path.write_text(json.dumps(data))
    assert remove_installation(home, execute=True, environ={})['code'] == 0
    assert json.loads(path.read_text())['permissions']['allow'] == ['my-unrelated-rule']


def test_mode_change_plan_previews_retired_resources(tmp_path):
    home = tmp_path / 'home'
    apply_plan(build_plan(home, strategy='copy', environ={}))
    summary = build_plan(home, strategy='copy', mode='generic', environ={}).summary()
    retired = {op['resource_id'] for op in summary['operations'] if op['retire']}
    assert 'codex.skill' in retired and 'shared.local-worker' in retired


def test_generic_mode_disables_preexisting_module_bridge(tmp_path):
    import tomllib
    from local_agent_bridge.setup.manifest import bridge_settings
    from local_agent_bridge.setup.runtime_config import save_codex
    home = tmp_path / 'home'
    save_codex(home / '.codex/config.toml', 'existing', 4096, home)
    path = home / '.gemini/antigravity-cli/mcp_config.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'mcpServers': {'opencode_worker': bridge_settings('existing')}}))
    apply_plan(build_plan(home, strategy='copy', mode='local', environ={}))
    apply_plan(build_plan(home, strategy='copy', mode='generic', environ={}))
    assert tomllib.loads((home / '.codex/config.toml').read_text())['mcp_servers']['opencode_worker']['enabled'] is False
    assert json.loads(path.read_text())['mcpServers']['opencode_worker']['disabled'] is True


def test_adopt_legacy_skill_in_place_without_duplicate(tmp_path):
    home = tmp_path / 'home'
    old = home / '.codex/skills/test-verify'
    old.mkdir(parents=True)
    (old / 'SKILL.md').write_text('existing legacy skill')
    apply_plan(build_plan(home, strategy='copy', adopt=('codex.custom-skill.test-verify',), environ={}))
    assert not (home / '.agents/skills/test-verify').exists()
    assert not build_plan(home, strategy='copy', environ={}).conflicts
    assert remove_installation(home, execute=True, environ={})['code'] == 0
    assert (old / 'SKILL.md').read_text() == 'existing legacy skill'


def test_receipt_publication_failure_rolls_back(tmp_path, monkeypatch):
    from local_agent_bridge.setup import installer
    home = tmp_path / 'home'
    original = installer.atomic_write

    def fail_receipt(path, *args, **kwargs):
        if path.name == 'receipt.json':
            raise OSError('receipt write failed')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(installer, 'atomic_write', fail_receipt)
    with pytest.raises(OSError, match='receipt write failed'):
        apply_plan(build_plan(home, strategy='copy', environ={}))
    assert not (home / '.codex/AGENTS.md').exists()
    assert not (home / '.local/share/local-agent/receipt.json').exists()


def test_incomplete_rollback_preserves_concurrent_edits(tmp_path, monkeypatch):
    from local_agent_bridge.setup import installer
    home = tmp_path / 'home'
    original = installer.install_operation
    first = [None]

    def concurrent_failure(op):
        if first[0] is None:
            original(op)
            first[0] = op.path
        else:
            first[0].write_text('concurrent user change')
            raise OSError('write failure')

    monkeypatch.setattr(installer, 'install_operation', concurrent_failure)
    with pytest.raises(RuntimeError, match='Incomplete rollback'):
        apply_plan(build_plan(home, strategy='copy', environ={}))
    assert first[0].read_text() == 'concurrent user change'
    result = installer.recover_installation(home, environ={})
    assert result['code'] == 5
    assert first[0].read_text() == 'concurrent user change'


def test_adopting_existing_local_snippet_keeps_generic_baseline_separate(tmp_path):
    from local_agent_bridge.setup.manifest import assets
    home = tmp_path / 'home'
    path = home / '.codex/AGENTS.md'
    path.parent.mkdir(parents=True)
    snippet = (assets() / 'instructions/coordinator.snippet.md').read_text()
    path.write_text('# Existing base\n\n' + snippet)
    apply_plan(build_plan(home, strategy='copy', adopt=('codex.instructions',), environ={}))
    apply_plan(build_plan(home, strategy='copy', mode='generic', environ={}))
    assert 'Existing base' in path.read_text()
    assert snippet.strip() not in path.read_text()


def test_authored_source_changes_invalidate_plan_and_update_generic_profile(tmp_path, monkeypatch):
    import shutil
    from local_agent_bridge.setup import planner
    from local_agent_bridge.setup.manifest import assets
    source = tmp_path / 'resources'
    shutil.copytree(assets(), source, ignore=shutil.ignore_patterns('__pycache__'))
    monkeypatch.setattr(planner, 'assets', lambda: source)
    home = tmp_path / 'home'
    initial = build_plan(home, strategy='copy', mode='generic', environ={})
    custom = source / 'dotfiles_llms/custom_agents/skills/test-verify/SKILL.md'
    custom.write_text(custom.read_text() + '\nChanged source\n')
    with pytest.raises(ValueError, match='stale'):
        apply_plan(initial)
    apply_plan(build_plan(home, strategy='copy', mode='generic', environ={}))
    template = source / 'profiles/AGENTS.md'
    template.write_text(template.read_text() + '\nNew generic rule\n')
    apply_plan(build_plan(home, strategy='copy', mode='generic', environ={}))
    assert 'New generic rule' in (home / '.codex/AGENTS.md').read_text()


def test_atomic_replace_retries_windows_denial_without_overwriting_changes(tmp_path, monkeypatch):
    from local_agent_bridge.setup import files
    if files.os.name != 'nt':
        pytest.skip('Windows replacement policy')
    target = tmp_path / 'config'
    target.write_text('before')
    original = files.os.replace
    calls = [0]

    def deny_once(source, destination):
        calls[0] += 1
        if calls[0] == 1:
            raise PermissionError('transient reader')
        return original(source, destination)

    monkeypatch.setattr(files.os, 'replace', deny_once)
    files.atomic_write(target, b'after')
    assert calls[0] == 2 and target.read_text() == 'after'

    def concurrent_change(source, destination):
        target.write_text('new user content')
        raise PermissionError('transient reader')

    monkeypatch.setattr(files.os, 'replace', concurrent_change)
    with pytest.raises(ValueError, match='Concurrent change'):
        files.atomic_write(target, b'do not apply')
    assert target.read_text() == 'new user content'


def test_opencode_retrieval_tools_are_opt_in_and_receipt_managed(tmp_path):
    home = tmp_path / 'home'
    opt_in = build_plan(home, strategy='copy', environ={}, code_retrieval=True)
    resource = next(op for op in opt_in.operations if op.resource_id == 'shared.code-retrieval.code_locate')
    assert resource.path == home / '.config/opencode/tools/code_locate.js'
    assert resource.kind == 'file'
    apply_plan(opt_in)
    installed = resource.path
    assert installed.is_file()

    preserved = build_plan(home, strategy='copy', environ={})
    assert preserved.code_retrieval is True
    assert next(op for op in preserved.operations
                if op.resource_id == 'shared.code-retrieval.code_locate').action == 'unchanged'

    remove_feature = build_plan(home, strategy='copy', environ={}, code_retrieval=False)
    assert any(op.resource_id == 'shared.code-retrieval.code_locate' and op.details.get('retire')
               for op in remove_feature.operations)
    apply_plan(remove_feature)
    assert not installed.exists()


def test_opencode_checkpoint_compaction_plugin_is_opt_in_and_receipt_managed(tmp_path):
    home = tmp_path / "home"
    opt_in = build_plan(home, strategy="copy", environ={}, checkpoint_compaction=True)
    resource = next(op for op in opt_in.operations if op.resource_id == "shared.checkpoint-compaction.plugin")
    assert resource.path == home / ".config/opencode/plugins/local_agent_checkpoint.js"
    apply_plan(opt_in)
    assert resource.path.is_file()

    preserved = build_plan(home, strategy="copy", environ={})
    assert preserved.checkpoint_compaction is True
    assert next(op for op in preserved.operations if op.resource_id == resource.resource_id).action == "unchanged"

    remove = build_plan(home, strategy="copy", environ={}, checkpoint_compaction=False)
    assert any(op.resource_id == resource.resource_id and op.details.get("retire") for op in remove.operations)
    apply_plan(remove)
    assert not resource.path.exists()
