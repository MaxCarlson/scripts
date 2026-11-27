from io import StringIO

from agent_continuity import terminal_format as fmt
from agent_continuity.dispatcher_cli import (
    _render_doctor_report,
    _render_launch_preview,
    _render_listing,
    _render_terminal_launches,
    build_parser,
    dispatch,
)
from agent_continuity.interactive import _agent_selector_line, _gui_selector_line


def test_display_width_handles_ansi_wide_and_combining_text():
    assert fmt.display_width("\x1b[36mAGY\x1b[0m") == 3
    assert fmt.display_width("研究") == 4
    assert fmt.display_width("e\u0301") == 1
    assert fmt.display_width(fmt.clip_display("研究XYZ", 5)) <= 5


def test_color_modes_and_no_color_override(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert fmt.color_enabled("always", is_tty=False)
    assert not fmt.color_enabled("auto", is_tty=False)
    monkeypatch.setenv("NO_COLOR", "")
    assert not fmt.color_enabled("always", is_tty=True)
    assert "\x1b[36m" not in fmt.provider_color("codex", enabled=False)
    assert "\x1b[36m" in fmt.provider_color("codex", enabled=True)
    assert "\x1b[35m" in fmt.provider_color("agy", enabled=True)
    assert "\x1b[32m" in fmt.state_color("active", enabled=True)
    assert "\x1b[2;33m" in fmt.state_color("inactive", enabled=True)
    assert "\x1b[2m" in fmt.state_color("completed", enabled=True)


def test_selectors_clip_unicode_and_keep_columns_with_ansi():
    gui = {"alias": "研究所" * 10, "last_activity_at": "2026-11-23T12:00:00+00:00"}
    agent = {"name": "名前" * 10, "current_provider": "agy", "current_session_id": "session-123456789"}
    assert fmt.display_width(_gui_selector_line(gui, 58)) <= 58
    assert max(fmt.display_width(line) for line in _agent_selector_line(agent, 69).splitlines()) <= 69
    assert max(fmt.display_width(line) for line in _agent_selector_line(agent, 110).splitlines()) <= 110


def test_listing_compact_color_timestamp_runtime_and_gui_separators(monkeypatch):
    from agent_continuity import dispatcher_cli

    monkeypatch.setattr(dispatcher_cli.shutil, "get_terminal_size", lambda fallback: type("Size", (), {"columns": 72})())
    monkeypatch.setattr(dispatcher_cli, "_runtime_label", lambda *args, **kwargs: "IN USE")
    monkeypatch.delenv("NO_COLOR", raising=False)
    now = "2026-11-23T12:00:00+00:00"
    result = {"action": "list", "schema_version": 1, "total": 2, "shown": 2, "omitted": 0,
              "conversations": [
                  {"alias": "GUI one", "last_activity_at": now, "slots": [
                      {"name": "Alpha", "current_provider": "codex", "current_session_id": "id-a",
                       "state": "active", "last_activity_at": now}], "omitted": 0},
                  {"alias": "GUI two", "last_activity_at": now, "slots": [
                      {"name": "Beta", "current_provider": "agy", "current_session_id": "id-b",
                       "state": "inactive", "last_activity_at": now}], "omitted": 0},
              ]}
    output = StringIO()
    _render_listing(result, output, "always", dispatcher=object())
    text = output.getvalue()
    assert "CODEX" in text and "AGY" in text
    assert "IN USE" in text and "Last activity:" in text
    assert "GUI one" in text and "GUI two" in text
    assert "GUI one" in text and "GUI two" in text
    assert "─" in text


def test_human_renderer_never_emits_ansi_when_color_is_disabled():
    output = StringIO()
    _render_listing({"gui": "P", "last_activity_at": None, "slots": [], "shown": 0,
                    "total": 0, "omitted": 0}, output, "never")
    assert "\x1b[" not in output.getvalue()

    output = StringIO()
    _render_listing({"conversations": [
        {"alias": "First", "last_activity_at": None, "slots": [], "omitted": 0},
        {"alias": "Second", "last_activity_at": None, "slots": [], "omitted": 0},
    ], "shown": 2, "total": 2, "omitted": 0}, output, "never")
    assert "\n\nSecond" in output.getvalue()
    assert "─" not in output.getvalue()


def test_listing_colors_semantic_provider_and_unpadded_lifecycle_values(monkeypatch):
    from agent_continuity import dispatcher_cli

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(dispatcher_cli.shutil, "get_terminal_size", lambda fallback: type("Size", (), {"columns": 120})())
    result = {"gui": "GUI", "last_activity_at": None, "slots": [
        {"name": "Agent", "current_provider": "codex", "current_session_id": "native-session",
         "state": "active", "last_activity_at": None}], "shown": 1, "total": 1, "omitted": 0}
    output = StringIO()
    _render_listing(result, output, "always")
    rendered = output.getvalue()

    assert "\x1b[36mCODEX\x1b[0m" in rendered
    assert "\x1b[32mactive\x1b[0m" in rendered


def test_semantic_styles_cover_palette_and_reset_sequences(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    styles = {
        "gui": ("Research GUI", "94;1"),
        "agent": ("Reviewer", "93;1"),
        "provider_codex": ("CODEX", "36"),
        "provider_agy": ("AGY", "35"),
        "timestamp": ("2026-11-27 10:00", "90"),
        "session": ("native-session", "37"),
        "active": ("active", "32"),
        "inactive": ("inactive", "33"),
        "completed": ("completed", "2"),
        "runtime_in_use": ("IN USE", "1;32"),
        "runtime_not_observed": ("NOT OBSERVED", "2"),
        "pending": ("PENDING", "33"),
        "unknown": ("UNKNOWN", "38;5;146"),
        "failed": ("FAILED", "31"),
        "interrupted": ("INTERRUPTED", "38;5;208"),
        "unresolved": ("UNRESOLVED", "31"),
        "success": ("EXITED", "32"),
        "warning": ("LAUNCHING", "33"),
        "label": ("Repository:", "2;37"),
    }
    for semantic, (value, code) in styles.items():
        styled = fmt.semantic_color(value, semantic, enabled=True)
        assert styled == f"\x1b[{code}m{value}\x1b[0m"
        assert fmt.display_width(styled) == fmt.display_width(value)
    assert fmt.semantic_color("Reviewer", "agent", enabled=False) == "Reviewer"


def test_responsive_listing_widths_preserve_cell_bounds_and_json_purity(monkeypatch):
    import json

    from agent_continuity import dispatcher_cli

    result = {"gui": "GUI 研究所", "last_activity_at": None, "slots": [
        {"name": "e\u0301 reviewer", "current_provider": "agy", "current_session_id": "native-session-id-1234567890",
         "state": "inactive", "last_activity_at": None, "activation_history": [
             {"activated_at": None, "provider": "agy", "native_session_id": "native-session-id-1234567890", "selected": True}
         ]}], "shown": 1, "total": 1, "omitted": 0}
    monkeypatch.delenv("NO_COLOR", raising=False)
    for width in (40, 60, 80, 100, 120, 200):
        monkeypatch.setattr(dispatcher_cli.shutil, "get_terminal_size", lambda fallback, w=width: type("Size", (), {"columns": w})())
        output = StringIO()
        _render_listing(result, output, "always")
        lines = [line for line in output.getvalue().splitlines() if line]
        assert all(fmt.display_width(line) <= width for line in lines)
        if width >= 104:
            assert "Provider" in lines[1]

    json_text = json.dumps(result, ensure_ascii=False)
    assert "\x1b[" not in json_text


def test_120_column_listing_preserves_uuid_and_allocates_name_width_from_data(monkeypatch):
    from agent_continuity import dispatcher_cli

    monkeypatch.setattr(dispatcher_cli.shutil, "get_terminal_size", lambda fallback: type("Size", (), {"columns": 120})())
    native_id = "12345678-1234-4234-8234-123456789abc"
    result = {"gui": "GUI", "last_activity_at": None, "slots": [
        {"name": "A" * 48, "current_provider": "codex", "current_environment_id": "local",
         "current_session_id": native_id,
         "state": "active", "last_activity_at": None}], "shown": 1, "total": 1, "omitted": 0}
    output = StringIO()
    _render_listing(result, output, "never")
    assert native_id in output.getvalue()
    assert "A" * 48 not in output.getvalue()


def test_selectors_terminal_history_preview_and_cli_color_contract(tmp_path, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    gui = _gui_selector_line({"alias": "Research", "last_activity_at": None}, 100, enabled=True)
    agent = _agent_selector_line({"name": "Reviewer", "current_provider": "agy",
                                  "current_session_id": "native-session"}, 100, enabled=True)
    assert "\x1b[94;1mResearch\x1b[0m" in gui
    assert "\x1b[93;1mReviewer\x1b[0m" in agent
    assert "\x1b[35mAGY\x1b[0m" in agent
    assert fmt.display_width(agent) <= 100

    output = StringIO()
    _render_terminal_launches([{"launch_started_at": "2026-11-27T12:00:00Z", "status": "spawn_failed",
                                "gui_alias": "Project", "slot_name": "Agent", "provider": "codex",
                                "native_session_id": None}], output, show_terminal_id=False, color="always")
    rendered = output.getvalue()
    assert "\x1b[31mspawn_failed\x1b[0m" in rendered
    assert "\x1b[94;1mProject\x1b[0m" in rendered

    preview = StringIO()
    _render_launch_preview({"provider": "codex", "native_session_id": "exact-session",
                            "permission_settings": {"requested": ["workspace-write"],
                                                    "verified_effective": None}}, preview, "always")
    assert "\x1b[33m\"permission_settings\": \x1b[0m" in preview.getvalue()
    assert "\x1b[36m\"codex\"\x1b[0m" in preview.getvalue()
    assert "\x1b[37m\"exact-session\",\x1b[0m" in preview.getvalue()
    assert "verified_effective" in preview.getvalue()

    doctor = StringIO()
    _render_doctor_report({
        "registry": {"database": {"integrity": "ok"}, "accessible": True,
                     "home": "C:/registry", "mutation_lock": "available"},
        "agents": [{"gui": "Research", "name": "Reviewer", "provider": "agy",
                    "lifecycle": "inactive", "runtime": "NOT OBSERVED", "session_id": "session-xyz",
                    "duplicate_resume": "uncertain"}],
        "pending_launches": [], "inconsistencies": [], "limitations": [],
    }, doctor, "always")
    doctor_text = doctor.getvalue()
    assert "\x1b[94;1mResearch\x1b[0m" in doctor_text
    assert "\x1b[93;1mReviewer\x1b[0m" in doctor_text
    assert "\x1b[35mAGY\x1b[0m" in doctor_text
    assert "\x1b[2mNOT OBSERVED\x1b[0m" in doctor_text

    parser = build_parser()
    args = parser.parse_args(["-H", str(tmp_path), "list", "-c", "always", "-j"])
    json_output = StringIO()
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=json_output) == 0
    assert "\x1b[" not in json_output.getvalue()
    assert json_output.getvalue().lstrip().startswith("{")


def test_empty_groups_and_history_mark_selected_or_unresolved(monkeypatch):
    from agent_continuity import dispatcher_cli

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(dispatcher_cli.shutil, "get_terminal_size", lambda fallback: type("Size", (), {"columns": 80})())
    output = StringIO()
    _render_listing({"gui": "Empty", "last_activity_at": None, "slots": [], "shown": 0,
                     "total": 0, "omitted": 0}, output, "always")
    assert "(no agents)" in output.getvalue()

    output = StringIO()
    _render_listing({"gui": "History", "last_activity_at": None, "slots": [
        {"name": "Agent", "current_provider": "codex", "current_session_id": "CURRENT",
         "state": "active", "last_activity_at": None,
         "activation_history": [
             {"activated_at": None, "provider": "codex", "native_session_id": "CURRENT", "selected": True},
             {"activated_at": None, "provider": "agy", "native_session_id": "<session-id>", "unresolved": True},
         ]}], "shown": 1, "total": 1, "omitted": 0}, output, "always")
    rendered = output.getvalue()
    assert "selected" in rendered
    assert "<unresolved>" in rendered
    assert "\x1b[31m<unresolved>\x1b[0m" in rendered


def test_interactive_passes_requested_color_mode_to_nested_selectors(monkeypatch):
    from agent_continuity import interactive

    monkeypatch.delenv("NO_COLOR", raising=False)

    class TTYStringIO(StringIO):
        def isatty(self):
            return True

    class Dispatcher:
        def list_guis(self):
            return [{"alias": "GUI", "last_activity_at": None}]

        def list_slots(self, *, gui):
            return []

    responses = iter([("selected", {"alias": "GUI"}), ("back", None), ("exit", None)])
    observed_modes = []
    rendered_rows = []

    def select_item(*args, **kwargs):
        observed_modes.append(kwargs.get("color_mode"))
        response = next(responses)
        if response[0] == "selected":
            rendered_rows.append(kwargs["render_line"](response[1]))
        return response

    monkeypatch.setattr(interactive, "select_item", select_item)
    output = TTYStringIO()
    assert interactive.run_interactive(
        Dispatcher(), input_stream=TTYStringIO(), output_stream=output, color_mode="always"
    ) == 0

    assert observed_modes == ["always", "always", "always"]
    assert "\x1b[94;1mGUI\x1b[0m" in rendered_rows[0]


def test_dispatch_passes_color_mode_into_interactive_entrypoint(tmp_path, monkeypatch):
    from agent_continuity import dispatcher_cli, interactive

    class TTYStringIO(StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(dispatcher_cli, "DispatcherService", lambda **_kwargs: object())
    observed = []

    def run_interactive(_dispatcher, **kwargs):
        observed.append(kwargs["color_mode"])
        return 0

    monkeypatch.setattr(interactive, "run_interactive", run_interactive)
    parser = build_parser()
    args = parser.parse_args(["-H", str(tmp_path), "-c", "never"])
    assert dispatch(args, parser, input_stream=TTYStringIO(), output_stream=TTYStringIO()) == 0
    assert observed == ["never"]


def test_provider_selector_receives_the_explicit_color_mode(monkeypatch):
    from agent_continuity import interactive

    observed = []
    monkeypatch.setattr(interactive, "select_item",
                        lambda *_args, **kwargs: observed.append(kwargs["color_mode"]) or
                        ("selected", {"provider": "agy"}))
    assert interactive._provider_choice(StringIO(), StringIO(), color_mode="never") == "agy"
    assert observed == ["never"]


def test_windows_auto_color_temporarily_enables_and_restores_vt(monkeypatch):
    import os

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.setattr(fmt, "os", os, raising=False)
    monkeypatch.setattr(os, "name", "nt")
    state = {"mode": 0x0001}
    calls = []

    class TTYStringIO(StringIO):
        def isatty(self):
            return True

    output = TTYStringIO()
    monkeypatch.setattr(fmt, "_console_mode_for_stream", lambda stream: state["mode"])

    def set_mode(stream, mode):
        calls.append(mode)
        state["mode"] = mode
        return True

    monkeypatch.setattr(fmt, "_set_console_mode_for_stream", set_mode)

    with fmt.temporary_vt_processing(output, "auto") as enabled:
        assert enabled
        assert state["mode"] == 0x0005
        assert fmt.color_enabled("auto", is_tty=True, stream=output)

    assert state["mode"] == 0x0001
    assert calls == [0x0005, 0x0001]
