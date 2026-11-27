from io import StringIO

from agent_continuity import terminal_format as fmt
from agent_continuity.dispatcher_cli import _render_listing
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
    assert fmt.display_width(_agent_selector_line(agent, 69)) <= 69
    assert fmt.display_width(_agent_selector_line(agent, 110)) <= 110


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
    assert "\n\nGUI two" in text


def test_human_renderer_never_emits_ansi_when_color_is_disabled():
    output = StringIO()
    _render_listing({"gui": "P", "last_activity_at": None, "slots": [], "shown": 0,
                    "total": 0, "omitted": 0}, output, "never")
    assert "\x1b[" not in output.getvalue()
