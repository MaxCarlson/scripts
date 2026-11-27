import hashlib
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
    _, result = run(home, 'continue', 'P', 'A', '-d')
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


def test_list_history_count_expands_newest_activation_rows_in_scoped_and_global_json(tmp_path):
    home = tmp_path / "registry"
    run(home, "register", "P", "A", "-p", "codex", "-i", "same-id")
    run(home, "register", "P", "A", "-p", "agy", "-i", "agy-id", "-s")
    run(home, "register", "P", "A", "-p", "codex", "-i", "same-id", "-s")

    scoped = json.loads(run(home, "list", "-g", "P", "-N", "2", "-j")[1])
    history = scoped["slots"][0]["activation_history"]
    assert [item["native_session_id"] for item in history] == ["same-id", "agy-id"]
    assert history[0]["selected"] is True
    assert history[1]["selected"] is False
    assert all(item["activated_at"] for item in history)

    global_result = json.loads(run(home, "list", "-N", "1", "-j")[1])
    assert global_result["conversations"][0]["slots"][0]["activation_history"][0]["native_session_id"] == "same-id"

    default = json.loads(run(home, "list", "-g", "P", "-N", "0", "-j")[1])
    assert "activation_history" not in default["slots"][0]


def test_list_completed_filter_is_consistent_between_global_and_scoped_views(tmp_path):
    home = tmp_path / "registry"
    for name in ("Active", "Inactive", "Completed"):
        run(home, "register", "P", name)
    run(home, "slot", "disable", "-g", "P", "-n", "Inactive", "-a")
    run(home, "slot", "complete", "-g", "P", "-n", "Completed", "-a")

    for args in (("list", "-g", "P", "-j"), ("list", "-j")):
        data = json.loads(run(home, *args)[1])
        slots = data["slots"] if "slots" in data else data["conversations"][0]["slots"]
        assert {slot["state"] for slot in slots} == {"active", "inactive"}
    for args in (("list", "-g", "P", "-A", "-j"), ("list", "-A", "-j")):
        data = json.loads(run(home, *args)[1])
        slots = data["slots"] if "slots" in data else data["conversations"][0]["slots"]
        assert {slot["state"] for slot in slots} == {"active", "inactive", "completed"}


def test_scoped_listing_includes_registry_gui_last_activity(tmp_path):
    from agent_continuity.dispatcher_cli import _listing

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "A", provider="codex", session_id="session")
    gui = dispatcher.list_guis()[0]
    args = build_parser().parse_args(["list", "-g", "P", "-j"])

    result = _listing(dispatcher, args)

    assert result["last_activity_at"] == gui["last_activity_at"]


@pytest.mark.parametrize(("environment_selector", "cwd"), [
    ("windows", "C:\\source\\work"),
    ("wsl:Ubuntu", "/home/test/source-work"),
])
def test_option_four_new_launch_inherits_departing_environment_and_cwd(
    tmp_path, monkeypatch, environment_selector, cwd
):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _switch_after_exit

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    if environment_selector == "wsl:Ubuntu":
        monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
        monkeypatch.setattr("agent_continuity.dispatcher_cli.shutil.which",
                            lambda name: "wsl.exe" if name.casefold() in {"wsl.exe", "wsl"} else None)
    dispatcher.register("P", "A", provider="codex", session_id="windows-session")
    dispatcher.attach_session(gui="P", name="A", provider="agy", session_id="prior-agy",
                              environment_selector="wsl:Ubuntu", cwd="/home/test/project", apply=True)
    dispatcher.attach_session(gui="P", name="A", provider="codex", session_id="source-recorded",
                              environment_selector=environment_selector, cwd=cwd, apply=True)
    slot = dispatcher.get_slot(gui="P", name="A")
    captured = {}
    original_begin_launch = dispatcher.begin_launch

    def capture_begin_launch(**kwargs):
        captured.update(kwargs)
        return original_begin_launch(**kwargs)

    monkeypatch.setattr(dispatcher, "begin_launch", capture_begin_launch)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: 0)

    assert _switch_after_exit(dispatcher, slot, "agy", input_stream=StringIO("n\ny\n"),
                              output_stream=StringIO()) == 0
    assert captured["environment_selector"] == slot["current"]["environment_id"]
    assert captured["cwd"] == cwd


def test_option_four_aborts_new_launch_when_selection_changes_during_prompt(tmp_path, monkeypatch):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _switch_after_exit

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "A", provider="codex", session_id="original")
    slot = dispatcher.get_slot(gui="P", name="A")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: 0)

    def competing_confirmation(*args, **kwargs):
        dispatcher.attach_session(gui="P", name="A", provider="codex", session_id="competing",
                                  apply=True)
        return True

    monkeypatch.setattr("agent_continuity.dispatcher_cli._ask_confirmation", competing_confirmation)
    with pytest.raises(ContinuityError, match="selection changed"):
        _switch_after_exit(dispatcher, slot, "agy", input_stream=StringIO(),
                           output_stream=StringIO())

    current = dispatcher.get_slot(gui="P", name="A")
    assert current["current"]["native_session_id"] == "competing"
    assert dispatcher.list_pending_launches(gui="P") == []


def test_option_four_reuses_recorded_environment_and_native_cwd(tmp_path, monkeypatch):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _switch_after_exit

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "A", provider="codex", session_id="source")
    dispatcher.attach_session(gui="P", name="A", provider="agy", session_id="prior-agy",
                              environment_selector="wsl:Ubuntu", cwd="/home/reviewer/work", apply=True)
    dispatcher.attach_session(gui="P", name="A", provider="codex", session_id="departing-codex",
                              environment_selector="windows", cwd="C:\\source", apply=True)
    slot = dispatcher.get_slot(gui="P", name="A")
    target_identity = ("agy", slot["history"][1]["environment_id"], "prior-agy")
    launched = {}

    def fake_run_pane(dispatcher, **kwargs):
        selected = dispatcher.get_slot_by_id(kwargs["slot_id"])["current"]
        native = dispatcher.materializer.get_session(selected["provider"], selected["environment_id"],
                                                     selected["native_session_id"])
        launched.update(identity=(selected["provider"], selected["environment_id"],
                                  selected["native_session_id"]), cwd=native.cwd_native)
        return 0

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", fake_run_pane)

    assert _switch_after_exit(dispatcher, slot, "agy", input_stream=StringIO("r\n"),
                              output_stream=StringIO()) == 0
    assert launched["identity"] == target_identity
    assert launched["cwd"] == "/home/reviewer/work"


def test_option_four_rejects_unsupported_recorded_environment_without_pending_launch(tmp_path):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _switch_after_exit

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "A")
    dispatcher.attach_session(gui="P", name="A", provider="codex", session_id="source",
                              environment_selector="unrecognized-environment", cwd="/unknown/path", apply=True)
    slot = dispatcher.get_slot(gui="P", name="A")

    with pytest.raises(ContinuityError, match="unknown environment"):
        _switch_after_exit(dispatcher, slot, "agy", input_stream=StringIO("y\n"), output_stream=StringIO())

    current = dispatcher.get_slot(gui="P", name="A")
    assert current["current"]["native_session_id"] == "source"
    assert dispatcher.list_pending_launches(gui="P") == []


def test_option_four_refuses_windows_session_from_wsl_without_guessing(tmp_path, monkeypatch):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _switch_after_exit

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "A", provider="codex", session_id="source")
    slot = dispatcher.get_slot(gui="P", name="A")
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "wsl")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")

    with pytest.raises(ContinuityError, match="Cannot launch the selected windows environment"):
        _switch_after_exit(dispatcher, slot, "agy", input_stream=StringIO("y\n"), output_stream=StringIO())

    assert dispatcher.list_pending_launches(gui="P") == []


def test_option_four_reuse_aborts_if_selection_changes_during_prompt(tmp_path, monkeypatch):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _switch_after_exit

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "A", provider="codex", session_id="source")
    dispatcher.attach_session(gui="P", name="A", provider="agy", session_id="prior-agy", apply=True)
    dispatcher.attach_session(gui="P", name="A", provider="codex", session_id="departing-codex", apply=True)
    slot = dispatcher.get_slot(gui="P", name="A")
    attach = dispatcher.attach_session
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: 0)

    def competing_attach(**kwargs):
        attach(gui="P", name="A", provider="codex", session_id="competing", apply=True)
        return attach(**kwargs)

    monkeypatch.setattr(dispatcher, "attach_session", competing_attach)
    with pytest.raises(ContinuityError, match="selection changed"):
        _switch_after_exit(dispatcher, slot, "agy", input_stream=StringIO("r\n"), output_stream=StringIO())

    assert dispatcher.get_slot(gui="P", name="A")["current"]["native_session_id"] == "competing"


def test_option_four_cancel_returns_to_post_exit_menu_for_inactive_choice(tmp_path, monkeypatch):
    import subprocess

    from agent_continuity.dispatcher_cli import _run_pane

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "A", provider="codex", session_id="session")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *a, **k: ["fake-resume"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process",
                        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0))
    output = StringIO()

    assert _run_pane(dispatcher, slot_id=dispatcher.get_slot(gui="P", name="A")["slot_id"],
                     launch_id=None, input_stream=StringIO("4\nn\n3\n"), output_stream=output) == 0

    assert dispatcher.get_slot(gui="P", name="A")["state"] == "inactive"
    assert output.getvalue().count("Showing 1 of 1 agents") == 1
    assert output.getvalue().count("[4] Switch provider (Codex / AGY / Claude; default AGY)") == 2


def test_list_rejects_negative_history_count(tmp_path):
    with pytest.raises(ContinuityError, match="history count"):
        run(tmp_path / "registry", "list", "-N", "-1")


def test_exit_option_five_resumes_only_inactive_exact_same_gui_session(tmp_path, monkeypatch):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _switch_to_existing_agent

    class TTY(StringIO):
        def isatty(self):
            return True

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Source", provider="codex", session_id="source-id")
    dispatcher.register("P", "Target", provider="agy", session_id="target-id")
    dispatcher.register("Other", "OtherTarget", provider="codex", session_id="other-id")
    dispatcher.set_slot_state(gui="P", name="Target", state="inactive", apply=True)
    dispatcher.set_slot_state(gui="Other", name="OtherTarget", state="inactive", apply=True)
    source = dispatcher.get_slot(gui="P", name="Source")

    def choose(items, **kwargs):
        assert [item["name"] for item in items] == ["Target"]
        assert kwargs["filter_key"] == "search_text"
        return "selected", items[0]

    monkeypatch.setattr("agent_continuity.interactive.select_item", choose)
    launched = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launched.append(kwargs["slot_id"]) or 0)
    assert _switch_to_existing_agent(dispatcher, source, input_stream=TTY(""), output_stream=TTY()) == 0
    assert launched == [dispatcher.get_slot(gui="P", name="Target")["slot_id"]]
    assert dispatcher.get_slot(gui="P", name="Source")["state"] == "inactive"
    assert dispatcher.get_slot(gui="P", name="Target")["state"] == "active"
    assert [row["native_session_id"] for row in dispatcher.get_slot(gui="P", name="Target")["history"]] == ["target-id", "target-id"]
    assert dispatcher.get_slot(gui="Other", name="OtherTarget")["state"] == "inactive"


def test_exit_option_five_refuses_stale_picker_session_without_mutating_slots(tmp_path, monkeypatch):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _switch_to_existing_agent

    class TTY(StringIO):
        def isatty(self):
            return True

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Source", provider="codex", session_id="source")
    dispatcher.register("P", "Target", provider="agy", session_id="old-target")
    dispatcher.set_slot_state(gui="P", name="Target", state="inactive", apply=True)
    source = dispatcher.get_slot(gui="P", name="Source")

    def change_during_picker(items, **kwargs):
        selected = dict(items[0])
        dispatcher.attach_session(gui="P", name="Target", provider="agy", session_id="new-target",
                                  apply=True, provenance="concurrent-change")
        return "selected", selected

    monkeypatch.setattr("agent_continuity.interactive.select_item", change_during_picker)
    assert _switch_to_existing_agent(dispatcher, source, input_stream=TTY(""), output_stream=TTY()) == 2
    assert dispatcher.get_slot(gui="P", name="Source")["state"] == "active"
    assert dispatcher.get_slot(gui="P", name="Target")["state"] == "inactive"
    assert dispatcher.get_slot(gui="P", name="Target")["current"]["native_session_id"] == "new-target"


def test_exit_option_five_rejects_destination_with_missing_or_pending_session(tmp_path, monkeypatch):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _switch_to_existing_agent

    class TTY(StringIO):
        def isatty(self):
            return True

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Source", provider="codex", session_id="source-id")
    dispatcher.create_slot(gui="P", name="NoSession", apply=True)
    dispatcher.set_slot_state(gui="P", name="NoSession", state="inactive", apply=True)
    source = dispatcher.get_slot(gui="P", name="Source")
    assert _switch_to_existing_agent(dispatcher, source, input_stream=TTY(""), output_stream=TTY()) == 0
    assert dispatcher.get_slot(gui="P", name="Source")["state"] == "active"


def test_exit_option_six_requires_confirmation_before_slot_or_pending_launch(tmp_path, monkeypatch):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _create_agent_after_exit

    class TTY(StringIO):
        def isatty(self):
            return True

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Source", provider="codex", session_id="source-id")
    source = dispatcher.get_slot(gui="P", name="Source")
    assert _create_agent_after_exit(dispatcher, source, input_stream=TTY("New\n1\n\nno\n"),
                                    output_stream=TTY()) == 0
    assert [row["name"] for row in dispatcher.list_slots(gui="P", active_only=False)] == ["Source"]
    assert dispatcher.list_pending_launches() == []


def test_exit_option_six_prepares_new_slot_only_after_explicit_authorization(tmp_path, monkeypatch):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _create_agent_after_exit

    class TTY(StringIO):
        def isatty(self):
            return True

    work = tmp_path / "work"
    work.mkdir()
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Source", provider="codex", session_id="source-id")
    source = dispatcher.get_slot(gui="P", name="Source")
    seen = []

    def fake_run(dispatcher, **kwargs):
        seen.append(kwargs)
        return 0

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", fake_run)
    assert _create_agent_after_exit(dispatcher, source, input_stream=TTY(f"New\n2\n{work}\ny\n"),
                                    output_stream=TTY()) == 0
    target = dispatcher.get_slot(gui="P", name="New")
    assert target["state"] == "active" and not target["current"]
    assert dispatcher.list_pending_launches()[0]["slot_id"] == target["slot_id"]
    assert seen[0]["transition_source"]["slot_id"] == source["slot_id"]


def test_review_and_return_round_trip_preserves_exact_cross_provider_sessions(tmp_path, monkeypatch):
    from argparse import Namespace
    from io import StringIO

    from agent_continuity.dispatcher_cli import _return, _review

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    original_cwd = tmp_path / "original"
    reviewer_cwd = tmp_path / "reviewer"
    original_cwd.mkdir()
    reviewer_cwd.mkdir()
    dispatcher.create_gui("P", apply=True)
    dispatcher.create_slot(gui="P", name="Implementer", apply=True)
    dispatcher.attach_session(gui="P", name="Implementer", provider="codex", session_id="original-native",
                              cwd=str(original_cwd), apply=True, provenance="test-cwd")
    dispatcher.create_slot(gui="P", name="IndependentReview", apply=True)
    dispatcher.attach_session(gui="P", name="IndependentReview", provider="agy", session_id="review-native",
                              cwd=str(reviewer_cwd), apply=True, provenance="test-cwd")
    dispatcher.set_slot_state(gui="P", name="IndependentReview", state="inactive", apply=True)
    launched = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launched.append(kwargs["slot_id"]) or 0)

    review_args = Namespace(gui="P", agent_name="Implementer", reviewer_agent="IndependentReview",
                            provider="agy", new=False, apply=True, cwd=str(reviewer_cwd), environment=None)
    assert _review(dispatcher, review_args, StringIO(), StringIO()) == 0
    original = dispatcher.get_slot(gui="P", name="Implementer")
    reviewer = dispatcher.get_slot(gui="P", name="IndependentReview")
    assert original["state"] == "inactive" and original["current"]["native_session_id"] == "original-native"
    assert reviewer["state"] == "active" and reviewer["current"]["native_session_id"] == "review-native"
    cycle = dispatcher.active_review_cycle(slot_id=original["slot_id"])
    assert cycle and cycle["reviewer_slot_id"] == reviewer["slot_id"]
    assert dispatcher.get_slot(gui="P", name="IndependentReview")["history"][-1]["native_session_id"] == "review-native"

    assert _return(dispatcher, Namespace(gui="P", agent_name="Implementer", apply=True),
                   StringIO(), StringIO()) == 0
    original = dispatcher.get_slot(gui="P", name="Implementer")
    reviewer = dispatcher.get_slot(gui="P", name="IndependentReview")
    assert original["state"] == "active" and original["current"]["native_session_id"] == "original-native"
    assert reviewer["state"] == "inactive" and reviewer["current"]["native_session_id"] == "review-native"
    assert dispatcher.active_review_cycle(slot_id=original["slot_id"]) is None
    assert len(original["history"]) == 2 and len(reviewer["history"]) == 2
    listed = json.loads(run(tmp_path / "registry", "list", "-g", "P", "-j")[1])
    assert next(row for row in listed["slots"] if row["name"] == "Implementer")["current_session_id"] == "original-native"
    _, continue_json = run(tmp_path / "registry", "continue", "-g", "P", "-n", "Implementer", "-j", "-d")
    assert json.loads(continue_json)["slot"]["current"]["native_session_id"] == "original-native"
    assert dispatcher.materializer.get_session("codex", original["current"]["environment_id"],
                                               "original-native").cwd_native == str(original_cwd)
    assert dispatcher.materializer.get_session("agy", reviewer["current"]["environment_id"],
                                               "review-native").cwd_native == str(reviewer_cwd)
    cycles = dispatcher._rows("SELECT status FROM dispatcher_review_cycles")
    assert [row["status"] for row in cycles] == ["returned"]
    dispatcher.materializer.db_path.unlink()
    dispatcher.materializer.rebuild_from_spools()
    assert dispatcher._rows("SELECT status FROM dispatcher_review_cycles") == [{"status": "returned"}]


def test_inactive_original_can_review_and_return_reactivates_same_session(tmp_path, monkeypatch):
    from argparse import Namespace
    from io import StringIO

    from agent_continuity.dispatcher_cli import _return, _review

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Implementer", provider="codex", session_id="original-native")
    dispatcher.register("P", "Reviewer", provider="agy", session_id="review-native")
    dispatcher.set_slot_state(gui="P", name="Implementer", state="inactive", apply=True)
    dispatcher.set_slot_state(gui="P", name="Reviewer", state="inactive", apply=True)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: 0)

    args = Namespace(gui="P", agent_name="Implementer", reviewer_agent="Reviewer",
                     provider="agy", new=False, apply=True, cwd=None, environment=None)
    assert _review(dispatcher, args, StringIO(), StringIO()) == 0
    original = dispatcher.get_slot(gui="P", name="Implementer")
    reviewer = dispatcher.get_slot(gui="P", name="Reviewer")
    assert original["state"] == "inactive"
    assert _session_identity_for_test(original) == ("codex", original["current"]["environment_id"], "original-native")
    assert reviewer["state"] == "active"
    assert reviewer["current"]["native_session_id"] == "review-native"

    assert _return(dispatcher, Namespace(gui="P", agent_name="Implementer", apply=True),
                   StringIO(), StringIO()) == 0
    original = dispatcher.get_slot(gui="P", name="Implementer")
    reviewer = dispatcher.get_slot(gui="P", name="Reviewer")
    assert original["state"] == "active"
    assert original["current"]["native_session_id"] == "original-native"
    assert reviewer["state"] == "inactive"
    assert [row["native_session_id"] for row in original["history"]] == ["original-native", "original-native"]


def _session_identity_for_test(slot):
    current = slot["current"]
    return current["provider"], current["environment_id"], current["native_session_id"]


def test_inactive_original_can_create_reviewer_after_explicit_new_authorization(tmp_path, monkeypatch):
    import subprocess
    from argparse import Namespace
    from io import StringIO

    from agent_continuity.dispatcher_cli import _review

    class TTY(StringIO):
        def isatty(self):
            return True

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Implementer", provider="codex", session_id="original-native")
    dispatcher.set_slot_state(gui="P", name="Implementer", state="inactive", apply=True)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv",
                        lambda *a, **k: ["fake-bootstrap"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *a, **k: ["fake-resume"])
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        output = ('{"conversation_id":"review-created","status":"SUCCESS"}'
                  if argv == ["fake-bootstrap"] else "")
        return subprocess.CompletedProcess(argv, 0, stdout=output)

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)
    args = Namespace(gui="P", agent_name="Implementer", reviewer_agent="Reviewer", provider="agy",
                     new=True, apply=True, cwd=None, environment=None)

    assert _review(dispatcher, args, TTY("1\n"), TTY()) == 0

    original = dispatcher.get_slot(gui="P", name="Implementer")
    reviewer = dispatcher.get_slot(gui="P", name="Reviewer")
    assert original["state"] == "inactive"
    assert original["current"]["native_session_id"] == "original-native"
    assert reviewer["state"] == "active"
    assert reviewer["current"]["native_session_id"] == "review-created"
    cycle = dispatcher.active_review_cycle(slot_id=original["slot_id"])
    assert cycle and cycle["reviewer_session_id"] == "review-created"
    assert calls == [["fake-bootstrap"], ["fake-resume"]]


def test_review_dry_run_does_not_register_reviewer(tmp_path):
    from argparse import Namespace
    from io import StringIO

    from agent_continuity.dispatcher_cli import _review

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Implementer", provider="codex", session_id="original")
    args = Namespace(gui="P", agent_name="Implementer", reviewer_agent="Reviewer", provider="agy",
                     new=False, apply=False, cwd=None, environment=None)
    assert _review(dispatcher, args, StringIO(), StringIO()) == 0
    assert [row["name"] for row in dispatcher.list_slots(gui="P", active_only=False)] == ["Implementer"]
    assert dispatcher.list_pending_launches() == []


def test_review_new_session_uses_fake_bootstrap_and_atomically_selects_exact_id(tmp_path, monkeypatch):
    import subprocess
    from argparse import Namespace
    from io import StringIO

    from agent_continuity.dispatcher_cli import _review

    class TTY(StringIO):
        def isatty(self):
            return True

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Implementer", provider="codex", session_id="original")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv", lambda *a, **k: ["fake-bootstrap"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *a, **k: ["fake-resume"])
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        output = '{"conversation_id":"review-created","status":"SUCCESS"}' if argv == ["fake-bootstrap"] else ""
        return subprocess.CompletedProcess(argv, 0, stdout=output)

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)
    args = Namespace(gui="P", agent_name="Implementer", reviewer_agent="Reviewer", provider="agy",
                     new=True, apply=True, cwd=str(tmp_path), environment=None)
    assert _review(dispatcher, args, TTY("1\n"), TTY()) == 0
    original = dispatcher.get_slot(gui="P", name="Implementer")
    reviewer = dispatcher.get_slot(gui="P", name="Reviewer")
    assert original["state"] == "inactive"
    assert reviewer["state"] == "active"
    assert reviewer["current"]["native_session_id"] == "review-created"
    assert dispatcher.active_review_cycle(slot_id=original["slot_id"])["reviewer_session_id"] == "review-created"
    assert dispatcher.list_pending_launches() == []
    assert seen == [["fake-bootstrap"], ["fake-resume"]]


def test_review_bootstrap_failure_keeps_pending_cycle_and_refuses_automatic_retry(tmp_path, monkeypatch):
    import subprocess
    from argparse import Namespace
    from io import StringIO

    from agent_continuity.dispatcher_cli import _review

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Implementer", provider="codex", session_id="original")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv", lambda *a, **k: ["fake-bootstrap"])
    calls = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process",
                        lambda argv, **kwargs: calls.append(argv) or subprocess.CompletedProcess(argv, 1, stdout=""))
    args = Namespace(gui="P", agent_name="Implementer", reviewer_agent="Reviewer", provider="agy",
                     new=True, apply=True, cwd=None, environment=None)
    assert _review(dispatcher, args, StringIO(""), StringIO()) == 1
    original = dispatcher.get_slot(gui="P", name="Implementer")
    reviewer = dispatcher.get_slot(gui="P", name="Reviewer")
    assert original["state"] == "active" and reviewer["state"] == "active" and reviewer["current"] is None
    assert dispatcher.open_review_cycle(slot_id=original["slot_id"])["status"] == "pending"
    with pytest.raises(ContinuityError, match="open review cycle"):
        _review(dispatcher, args, StringIO(""), StringIO())
    assert calls == [["fake-bootstrap"]]


def test_exit_option_six_fake_bootstrap_deactivates_source_only_after_capture(tmp_path, monkeypatch):
    import subprocess
    from io import StringIO

    from agent_continuity.dispatcher_cli import _create_agent_after_exit

    class TTY(StringIO):
        def isatty(self):
            return True

    cwd = tmp_path / "work"
    cwd.mkdir()
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Source", provider="codex", session_id="source-id")
    source = dispatcher.get_slot(gui="P", name="Source")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv", lambda *a, **k: ["fake-bootstrap"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *a, **k: ["fake-resume"])

    def fake_run(argv, **kwargs):
        output = ('{"type":"thread.started","thread_id":"new-agent-id"}\n{"type":"turn.completed"}'
                  if argv == ["fake-bootstrap"] else "")
        return subprocess.CompletedProcess(argv, 0, stdout=output)

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)
    output = TTY()
    result = _create_agent_after_exit(dispatcher, source,
                                      input_stream=TTY(f"New\n1\n{cwd}\ny\n1\n"), output_stream=output)
    new_agent = dispatcher.get_slot(gui="P", name="New")
    assert result == 0, output.getvalue()
    assert dispatcher.get_slot(gui="P", name="Source")["state"] == "inactive"
    assert new_agent["state"] == "active" and new_agent["current"]["native_session_id"] == "new-agent-id"
    assert dispatcher.list_pending_launches() == []


def test_exit_option_six_failed_bootstrap_keeps_source_active_and_pending_for_recovery(tmp_path, monkeypatch):
    import subprocess
    from io import StringIO

    from agent_continuity.dispatcher_cli import _create_agent_after_exit

    class TTY(StringIO):
        def isatty(self):
            return True

    cwd = tmp_path / "work"
    cwd.mkdir()
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Source", provider="codex", session_id="source-id")
    source = dispatcher.get_slot(gui="P", name="Source")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv", lambda *a, **k: ["fake-bootstrap"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process",
                        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, stdout=""))
    result = _create_agent_after_exit(dispatcher, source,
                                      input_stream=TTY(f"New\n1\n{cwd}\ny\n"), output_stream=TTY())
    assert result == 1
    assert dispatcher.get_slot(gui="P", name="Source")["state"] == "active"
    pending = dispatcher.list_pending_launches()
    new_agent = dispatcher.get_slot(gui="P", name="New")
    assert len(pending) == 1 and pending[0]["slot_id"] == new_agent["slot_id"]
    assert new_agent["current"] is None


def test_concurrent_agent_transitions_only_commit_one_stale_head(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "Source", provider="codex", session_id="source")
    dispatcher.register("P", "Target", provider="agy", session_id="target")
    dispatcher.set_slot_state(gui="P", name="Target", state="inactive", apply=True)
    source = dispatcher.get_slot(gui="P", name="Source")
    target = dispatcher.get_slot(gui="P", name="Target")
    args = dict(gui="P", source_slot_id=source["slot_id"], destination_slot_id=target["slot_id"],
                provider="agy", environment_id=target["current"]["environment_id"], session_id="target",
                source_state="inactive", destination_state="active",
                expected_source=("codex", source["current"]["environment_id"], "source"),
                expected_destination=("agy", target["current"]["environment_id"], "target"), apply=True)

    def transition():
        try:
            dispatcher.complete_agent_transition(**args)
            return "applied"
        except ContinuityError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: transition(), range(2)))
    assert sorted(outcomes) == ["applied", "stale"]
    assert dispatcher.get_slot(gui="P", name="Source")["state"] == "inactive"
    assert dispatcher.get_slot(gui="P", name="Target")["state"] == "active"
    assert len(dispatcher.get_slot(gui="P", name="Target")["history"]) == 2


def test_exit_option_five_prioritizes_linked_original_and_returns_review_cycle(tmp_path, monkeypatch):
    from io import StringIO

    from agent_continuity.dispatcher_cli import _review_cycle_payload, _switch_to_existing_agent

    class TTY(StringIO):
        def isatty(self):
            return True

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    for name, provider, session in (("Original", "codex", "original"),
                                    ("Reviewer", "agy", "reviewer"),
                                    ("Other", "codex", "other")):
        dispatcher.register("P", name, provider=provider, session_id=session)
    dispatcher.set_slot_state(gui="P", name="Reviewer", state="inactive", apply=True)
    dispatcher.set_slot_state(gui="P", name="Other", state="inactive", apply=True)
    original = dispatcher.get_slot(gui="P", name="Original")
    reviewer = dispatcher.get_slot(gui="P", name="Reviewer")
    cycle = _review_cycle_payload(original, reviewer["slot_id"], reviewer["current"])
    dispatcher.complete_agent_transition(
        gui="P", source_slot_id=original["slot_id"], destination_slot_id=reviewer["slot_id"],
        provider="agy", environment_id=reviewer["current"]["environment_id"], session_id="reviewer",
        source_state="inactive", destination_state="active",
        expected_source=("codex", original["current"]["environment_id"], "original"),
        expected_destination=("agy", reviewer["current"]["environment_id"], "reviewer"),
        review_cycle=cycle, apply=True,
    )
    reviewer = dispatcher.get_slot(gui="P", name="Reviewer")
    chosen = []

    def choose(items, **kwargs):
        assert [row["name"] for row in items][:2] == ["Original", "Other"]
        chosen.append(items[0]["name"])
        return "selected", items[0]

    monkeypatch.setattr("agent_continuity.interactive.select_item", choose)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: 0)
    assert _switch_to_existing_agent(dispatcher, reviewer, input_stream=TTY(""), output_stream=TTY()) == 0
    assert chosen == ["Original"]
    assert dispatcher.get_slot(gui="P", name="Original")["state"] == "active"
    assert dispatcher.get_slot(gui="P", name="Reviewer")["state"] == "inactive"
    assert dispatcher._rows("SELECT status FROM dispatcher_review_cycles")[0]["status"] == "returned"


def test_retry_after_partial_registration(tmp_path, monkeypatch):
    import pytest

    from agent_continuity.dispatcher import DispatcherService
    service = DispatcherService(home_dir=tmp_path / 'registry')
    original = service.continuity._emit_and_materialize
    calls = 0
    def interrupted(events):
        nonlocal calls
        calls += 1
        if calls == 1 and len(events) > 2:
            original(events[:2])
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


def test_inactive_picker_dry_run_does_not_change_lifecycle_or_history(tmp_path, monkeypatch):
    from argparse import Namespace

    from agent_continuity.dispatcher_cli import _run_picker

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "A", provider="codex", session_id="native")
    dispatcher.set_slot_state(gui="P", name="A", state="inactive", apply=True)
    before = dispatcher.get_slot(gui="P", name="A")

    class TTYInput(StringIO):
        def isatty(self):
            return True

    class TTYOutput(StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("agent_continuity.interactive.select_item", lambda *a, **k: ("selected", {
        **before, "gui_alias": "P", "provider": "codex", "runtime_status": "NOT OBSERVED",
        "current_session_id": "native", "search_text": "p a codex native",
    }))
    input_stream = TTYInput("y\n")
    output_stream = TTYOutput()
    assert _run_picker(dispatcher, Namespace(gui=None, all=False, apply=False), input_stream, output_stream) == 0

    after = dispatcher.get_slot(gui="P", name="A")
    assert after["state"] == "inactive"
    assert after["history"] == before["history"]


def test_named_continue_checks_runtime_before_reactivation_mutation(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register("P", "A", provider="codex", session_id="native")
    dispatcher.set_slot_state(gui="P", name="A", state="inactive", apply=True)
    before = dispatcher.get_slot(gui="P", name="A")
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "continue", "-g", "P", "-n", "A", "--reactivate", "-a"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._session_in_use", lambda *a: True)

    with pytest.raises(ContinuityError, match="already in use"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())

    after = dispatcher.get_slot(gui="P", name="A")
    assert after["state"] == "inactive"
    assert after["history"] == before["history"]


def test_runtime_lease_is_nonblocking_and_lifetime_scoped(tmp_path):
    from agent_continuity.dispatcher_cli import _session_runtime_lock, _try_session_runtime_lock
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    with _session_runtime_lock(dispatcher, "session-test.lock"):
        assert _try_session_runtime_lock(dispatcher, "session-test.lock")
    assert not _try_session_runtime_lock(dispatcher, "session-test.lock")


def test_positional_start_dry_run_without_launch_is_explicit(tmp_path):
    home = tmp_path / "registry"
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "codex", "-d"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert DispatcherService(home_dir=home).list_guis() == []


def test_start_without_selected_session_initializes_by_default(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    parser = build_parser()
    launches = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launches.append(kwargs["launch_id"]) or 0)

    args = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "codex"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    service = DispatcherService(home_dir=home)
    slot = service.get_slot(gui="P", name="A")
    pending = service.list_pending_launches(gui="P")
    assert slot["current"] is None
    assert len(pending) == 1
    assert launches == [pending[0]["launch_id"]]


def test_start_new_flag_without_apply_authorizes_replacement_and_keeps_history(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("P", "A", provider="codex", session_id="prior-session")
    launches = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launches.append(kwargs["launch_id"]) or 0)
    parser = build_parser()

    args = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "codex", "-N"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    slot = service.get_slot(gui="P", name="A")
    assert [item["native_session_id"] for item in slot["history"]] == ["prior-session"]
    assert len(service.list_pending_launches(gui="P")) == 1
    assert launches[0] == service.list_pending_launches(gui="P")[0]["launch_id"]


def test_positional_start_new_apply_creates_pending_without_mocked_provider_call(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "codex", "--new", "-a"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: 0)
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    service = DispatcherService(home_dir=home)
    assert service.get_slot(gui="P", name="A")["state"] == "active"
    assert service.list_pending_launches(gui="P")


def test_named_start_preview_matches_positional_and_does_not_register(tmp_path):
    home = tmp_path / "registry"
    parser = build_parser()
    output = StringIO()

    assert dispatch(
        parser.parse_args(["-H", str(home), "start", "-g", "P", "-n", "A", "-p", "codex", "-d"]),
        parser,
        input_stream=StringIO(),
        output_stream=output,
    ) == 0

    service = DispatcherService(home_dir=home)
    assert service.list_guis() == []
    assert "would register" in output.getvalue().lower()
    assert "dry-run" in output.getvalue().lower()


def test_named_start_first_session_without_new_or_apply_registers_and_reserves_once(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    parser = build_parser()
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: 0)

    args = parser.parse_args(["-H", str(home), "start", "-g", "P", "-n", "A", "-p", "codex"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    service = DispatcherService(home_dir=home)
    assert [gui["alias"] for gui in service.list_guis()] == ["P"]
    assert len(service.list_slots(gui="P", active_only=False)) == 1
    assert len(service.list_pending_launches(gui="P")) == 1


def test_named_start_legacy_apply_without_new_still_initializes_first_session(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    parser = build_parser()
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **kw: 0)
    args = parser.parse_args(["-H", str(home), "start", "-g", "P", "-n", "A", "-p", "codex", "-a"])

    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    service = DispatcherService(home_dir=home)
    assert service.get_slot(gui="P", name="A")["current"] is None
    assert len(service.list_pending_launches(gui="P")) == 1


def test_start_with_selected_session_resumes_without_creating_duplicate_launch(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("P", "A", provider="codex", session_id="selected")
    launches = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kw: launches.append(kw["launch_id"]) or 0)
    parser = build_parser()

    args = parser.parse_args(["-H", str(home), "start", "-g", "P", "-n", "A", "-p", "codex"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    assert launches == [None]
    assert service.get_slot(gui="P", name="A")["current"]["native_session_id"] == "selected"
    assert service.list_pending_launches(gui="P") == []


def test_start_with_different_provider_requires_explicit_switch_command(tmp_path):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("P", "A", provider="codex", session_id="selected")
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "agy", "-a"])

    with pytest.raises(ContinuityError, match="provider differs.*switch"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())

    assert [item["native_session_id"] for item in service.get_slot(gui="P", name="A")["history"]] == ["selected"]


def test_prepare_start_rejects_a_stale_selected_session_snapshot(tmp_path):
    service = DispatcherService(home_dir=tmp_path / "registry")
    service.register("P", "A", provider="codex", session_id="old")
    expected = service.get_slot(gui="P", name="A")["current"]
    service.attach_session(gui="P", name="A", provider="codex", session_id="new", apply=True)

    with pytest.raises(ContinuityError, match="selection changed"):
        service.prepare_start(
            gui="P", name="A", provider="agy", expected_current=(
                expected["provider"], expected["environment_id"], expected["native_session_id"]
            ), apply=True,
        )

    assert service.list_pending_launches(gui="P") == []


def test_start_refuses_second_pending_launch_before_any_new_provider_call(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.create_gui("P", apply=True)
    service.create_slot(gui="P", name="A", apply=True)
    first = service.begin_launch(gui="P", name="A", provider="codex", apply=True)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda *a, **kw: pytest.fail("pending launch must not be retried"))
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "codex"])

    with pytest.raises(ContinuityError, match="already pending"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())

    assert [item["launch_id"] for item in service.list_pending_launches(gui="P")] == [
        first["details"]["launch_id"]
    ]


def test_start_refuses_to_replace_an_in_use_selected_session(tmp_path):
    from agent_continuity.dispatcher_cli import _session_runtime_lock

    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("P", "A", provider="codex", session_id="running")
    current = service.get_slot(gui="P", name="A")["current"]
    lock_key = hashlib.sha256(
        f"{current['provider']}\0{current['environment_id']}\0{current['native_session_id']}".encode()
    ).hexdigest()[:24]
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "codex"])

    with _session_runtime_lock(service, f"session-{lock_key}.lock"), pytest.raises(ContinuityError, match="in use"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())

    assert [item["native_session_id"] for item in service.get_slot(gui="P", name="A")["history"]] == ["running"]


def test_start_requires_explicit_reactivation_for_inactive_slot(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.create_gui("P", apply=True)
    service.create_slot(gui="P", name="A", apply=True)
    service.set_slot_state(gui="P", name="A", state="inactive", apply=True)
    parser = build_parser()
    denied = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "codex", "-N", "-a"])

    with pytest.raises(ContinuityError, match="inactive.*reactivate"):
        dispatch(denied, parser, input_stream=StringIO(), output_stream=StringIO())
    assert service.list_pending_launches(gui="P") == []

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **kw: 0)
    allowed = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "codex", "-N", "-r", "-a"])
    assert dispatch(allowed, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert service.get_slot(gui="P", name="A")["state"] == "active"
    assert len(service.list_pending_launches(gui="P")) == 1


def test_start_new_prompt_cancel_leaves_selected_session_and_history_unchanged(tmp_path, monkeypatch):
    class TTYInput(StringIO):
        def isatty(self):
            return True

    class TTYOutput(StringIO):
        def isatty(self):
            return True

    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("P", "A", provider="codex", session_id="selected")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda *a, **kw: pytest.fail("canceled new start must not launch"))
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "start", "P", "A", "-p", "agy", "-N"])
    output = TTYOutput()

    assert dispatch(args, parser, input_stream=TTYInput("n\n"), output_stream=output) == 0

    slot = service.get_slot(gui="P", name="A")
    assert [item["native_session_id"] for item in slot["history"]] == ["selected"]
    assert service.list_pending_launches(gui="P") == []
    assert "canceled" in output.getvalue().lower()


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
