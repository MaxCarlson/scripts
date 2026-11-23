import json
from io import StringIO

import pytest

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import build_parser, dispatch
from agent_continuity.errors import ContinuityError


def run(home, *args):
    parser = build_parser()
    output = StringIO()
    code = dispatch(parser.parse_args(['-H', str(home), *args]), parser, input_stream=StringIO(), output_stream=output)
    return code, output.getvalue()


def test_registration_and_global_listing(tmp_path):
    home = tmp_path / 'registry'
    assert run(home, 'register', 'Project', 'Agent', '-p', 'codex', '-i', 'session-1')[0] == 0
    _, output = run(home, 'list', '-j')
    result = json.loads(output)
    assert result['conversations'][0]['slots'][0]['current_session_id'] == 'session-1'


def test_registration_idempotence_conflict_and_rebuild(tmp_path):
    import pytest

    from agent_continuity.dispatcher import DispatcherService
    from agent_continuity.errors import ContinuityError
    home = tmp_path / 'registry'
    service = DispatcherService(home_dir=home)
    first = service.register('Project', 'Agent', provider='codex', session_id='one')
    second = service.register('PROJECT', 'AGENT', provider='codex', session_id='one')
    assert not second['events']
    assert first['details'] == second['details']
    with pytest.raises(ContinuityError, match='different session'):
        service.register('Project', 'Agent', provider='agy', session_id='two')
    service.register('Project', 'Agent', provider='agy', session_id='two', select=True)
    before = service.get_slot(gui='Project', name='Agent')
    service.materializer.db_path.unlink()
    service.materializer.rebuild_from_spools()
    after = service.get_slot(gui='Project', name='Agent')
    assert before['history'] == after['history']
    assert [x['native_session_id'] for x in after['history']] == ['one', 'two']


def test_empty_and_scoped_listing(tmp_path):
    home = tmp_path / 'registry'
    assert json.loads(run(home, 'list', '-j')[1])['total'] == 0
    run(home, 'register', 'P', 'Active')
    run(home, 'register', 'P', 'Inactive')
    run(home, 'register', 'P', 'Completed')
    run(home, 'slot', 'disable', '-g', 'P', '-n', 'Inactive', '-a')
    run(home, 'slot', 'complete', '-g', 'P', '-n', 'Completed', '-a')
    data = json.loads(run(home, 'list', 'P', '-j', '-l', '1')[1])
    assert data['slots'][0]['name'] == 'Active'
    assert (data['total'], data['omitted']) == (2, 1)
    data = json.loads(run(home, 'list', '-g', 'P', '-j', '-A')[1])
    assert [x['state'] for x in data['slots']] == ['active', 'inactive', 'completed']


def test_registration_dry_run_and_invalid_arguments(tmp_path):
    import pytest

    from agent_continuity.errors import ContinuityError
    home = tmp_path / 'registry'
    run(home, 'register', 'P', 'A', '-p', 'codex', '-i', 'id', '-d')
    assert json.loads(run(home, 'list', '-j')[1])['total'] == 0
    with pytest.raises(ContinuityError):
        run(home, 'register', 'P', 'A', '-p', 'codex')
    with pytest.raises(ContinuityError):
        run(home, 'register', 'P', '-g', 'Q')
    assert json.loads(run(home, 'list', '-j')[1])['total'] == 0


def test_named_registration_and_legacy_positional_preview(tmp_path):
    home = tmp_path / 'registry'
    run(home, 'register', '-g', 'P', '-n', 'A', '-p', 'codex', '-i', 'full-session')
    _, result = run(home, 'continue', 'P', 'A')
    assert 'Dry-run' in result
    _, result = run(home, 'gui', 'list')
    assert 'P' in result


def test_concurrent_registration_reuses_records(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from agent_continuity.dispatcher import DispatcherService
    home = tmp_path / 'registry'
    module = Path(__file__).resolve().parents[1]
    script = "import sys; from agent_continuity.dispatcher import DispatcherService; DispatcherService(home_dir=sys.argv[1]).register('P','A',provider='codex',session_id='id')"
    env = dict(os.environ, PYTHONPATH=str(module))
    processes = [subprocess.Popen([sys.executable, '-c', script, str(home)], cwd=module, env=env) for _ in range(3)]
    assert [process.wait(timeout=30) for process in processes] == [0, 0, 0]
    dispatcher = DispatcherService(home_dir=home)
    assert len(dispatcher.list_guis()) == 1
    assert len(dispatcher.get_slot(gui='P', name='A')['history']) == 1
    dispatcher.materializer.rebuild_from_spools()
    assert len(dispatcher.get_slot(gui='P', name='A')['history']) == 1


def test_long_unicode_and_color_disabled(tmp_path, monkeypatch):
    home = tmp_path / 'registry'
    name = '長い名前' * 12
    session = '0123456789' * 8
    run(home, 'register', '研究', name, '-p', 'agy', '-i', session)
    monkeypatch.setenv('NO_COLOR', '1')
    _, human = run(home, 'list', '研究', '-c', 'never')
    assert '\x1b[' not in human
    assert 'inactive' not in human
    data = json.loads(run(home, 'list', '研究', '-j')[1])
    assert data['slots'][0]['name'] == name
    assert data['slots'][0]['current_session_id'] == session


def test_explicit_limit_with_all_and_global_cap(tmp_path):
    home = tmp_path / 'registry'
    for index in range(12):
        run(home, 'register', 'P', f'A{index:02}')
    result = json.loads(run(home, 'list', '-j')[1])
    assert result['conversations'][0]['omitted'] == 2
    scoped = json.loads(run(home, 'list', 'P', '-A', '-l', '3', '-j')[1])
    assert scoped['total'] == 12
    assert scoped['shown'] == 3
    assert scoped['omitted'] == 9


def test_retry_after_partial_registration(tmp_path, monkeypatch):
    import pytest

    from agent_continuity.dispatcher import DispatcherService
    service = DispatcherService(home_dir=tmp_path / 'registry')
    original = service.continuity._emit_and_materialize
    calls = 0
    def interrupted(events):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError('simulated interruption')
        original(events)
    monkeypatch.setattr(service.continuity, '_emit_and_materialize', interrupted)
    with pytest.raises(OSError, match='interruption'):
        service.register('P', 'A', provider='codex', session_id='id')
    monkeypatch.setattr(service.continuity, '_emit_and_materialize', original)
    service.register('P', 'A', provider='codex', session_id='id')
    before = service.get_slot(gui='P', name='A')
    service.materializer.rebuild_from_spools()
    assert service.get_slot(gui='P', name='A')['history'] == before['history']
    assert len(before['history']) == 1


def test_flat_picker_non_tty_requires_explicit_target(tmp_path):
    parser = build_parser()
    output = StringIO()
    args = parser.parse_args(["-H", str(tmp_path / "registry"), "continue"])
    with pytest.raises(ContinuityError, match="interactive terminal"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=output)


def test_flat_picker_uses_searchable_all_fields_and_runtime(tmp_path, monkeypatch):
    from agent_continuity.interactive import filter_items
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("Project", "Agent", provider="codex", session_id="native-123")
    from agent_continuity.dispatcher_cli import _continue_items
    monkeypatch.setattr("agent_continuity.dispatcher_cli._session_in_use", lambda *args: True)
    items = _continue_items(dispatcher)
    assert items[0]["runtime_status"] == "IN USE"
    assert filter_items(items, "project", key="search_text")
    assert filter_items(items, "codex", key="search_text")
    assert filter_items(items, "native-123", key="search_text")


def test_runtime_lease_is_nonblocking_and_lifetime_scoped(tmp_path):
    from agent_continuity.dispatcher_cli import _session_runtime_lock, _try_session_runtime_lock
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    with _session_runtime_lock(dispatcher, "session-test.lock"):
        assert _try_session_runtime_lock(dispatcher, "session-test.lock")
    assert not _try_session_runtime_lock(dispatcher, "session-test.lock")


def test_positional_start_requires_explicit_authorization_without_launch(tmp_path):
    home = tmp_path / "registry"
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "codex"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert DispatcherService(home_dir=home).list_guis() == []


def test_positional_start_new_apply_creates_pending_without_mocked_provider_call(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "codex", "--new", "-a"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: 0)
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    service = DispatcherService(home_dir=home)
    assert service.get_slot(gui="P", name="A")["state"] == "active"
    assert service.list_pending_launches(gui="P")


def test_continue_historical_provider_and_exact_id_selection(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("P", "A", provider="agy", session_id="agy-one")
    service.register("P", "A", provider="codex", session_id="cx-two", select=True)
    parser = build_parser()
    seen = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda dispatcher, **kw: seen.append(kw["slot_id"]) or 0)
    args = parser.parse_args(["-H", str(home), "continue", "P", "A", "-p", "agy", "-a"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert service.get_slot(gui="P", name="A")["current"]["native_session_id"] == "agy-one"
    args = parser.parse_args(["-H", str(home), "continue", "P", "A", "-i", "cx-two", "-a"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert service.get_slot(gui="P", name="A")["current"]["native_session_id"] == "cx-two"
    assert len(seen) == 2


def test_continue_missing_historical_id_never_starts_a_new_session(tmp_path):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("P", "A", provider="agy", session_id="known")
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "continue", "P", "A", "-i", "missing"])
    with pytest.raises(ContinuityError, match="not in this agent's activation history"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())
    assert len(service.get_slot(gui="P", name="A")["history"]) == 1


def test_continue_provider_ambiguity_requires_exact_id(tmp_path):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("P", "A", provider="agy", session_id="one")
    service.register("P", "A", provider="codex", session_id="middle", select=True)
    service.register("P", "A", provider="agy", session_id="two", select=True)
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "continue", "P", "A", "-p", "agy"])
    with pytest.raises(ContinuityError, match="Multiple historical agy sessions"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())
