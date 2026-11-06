import json

import pytest

from snips.config import (
    ConfigError,
    default_config,
    markdown_fence,
    parse_hotkey,
    serialize_config,
    template_payload,
    validate_config,
)


@pytest.mark.parametrize(
    ("shortcut", "display", "ahk"),
    [
        ("Ctrl+Alt+B", "Ctrl+Alt+B", "^!b"),
        ("Alt+Ctrl+F12", "Ctrl+Alt+F12", "^!f12"),
        ("Shift+Win+Space", "Shift+Win+Space", "+#Space"),
    ],
)
def test_parse_hotkey_normalizes_modifiers(shortcut, display, ahk):
    assert parse_hotkey(shortcut) == (display, ahk)


@pytest.mark.parametrize("shortcut", ["B", "Ctrl+Bogus+B", "Ctrl+Ctrl+B", "Ctrl+Alt+NoSuchKey"])
def test_parse_hotkey_rejects_invalid_shortcut(shortcut):
    with pytest.raises(ConfigError):
        parse_hotkey(shortcut)


def test_config_round_trip_preserves_unicode_and_multiline_template():
    config = default_config()
    config["bindings"][0]["content"] = "first\r\n  東京 🐈\n{{cursor}}tail"
    decoded = json.loads(serialize_config(config))
    assert validate_config(decoded)["bindings"][0]["content"] == "first\r\n  東京 🐈\n{{cursor}}tail"


def test_config_rejects_duplicate_hotkeys_even_when_disabled():
    config = default_config()
    config["bindings"][1]["hotkey"] = "Alt+Ctrl+B"
    with pytest.raises(ConfigError, match="Hotkey collision"):
        validate_config(config)


def test_template_cursor_position_and_no_marker():
    assert template_payload("head\n{{cursor}}\ntail") == ("head\n\ntail", 5)
    assert template_payload("plain") == ("plain", 0)


def test_markdown_fence_is_longer_than_embedded_backticks_and_preserves_text():
    text = "  start\r\n```\n    東京\n``````\t"
    result = markdown_fence(text)
    assert result == "```````\n" + text + "\n```````"
    assert result.split("\n", 1)[1].startswith(text + "\n")
