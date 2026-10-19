from pathlib import Path


from lmstui.defaults import (
    clear_defaults,
    get_effective_defaults,
    load_defaults,
    parse_default_val,
    set_default,
)


def test_parse_default_val():
    assert parse_default_val("true") is True
    assert parse_default_val("True") is True
    assert parse_default_val("false") is False
    assert parse_default_val("123") == 123
    assert parse_default_val("0.7") == 0.7
    assert parse_default_val("hello world") == "hello world"
    assert parse_default_val('{"key": "val"}') == {"key": "val"}


def test_defaults_crud(tmp_path: Path):
    d_file = tmp_path / "defaults.json"

    # Initially empty
    data = load_defaults(d_file)
    assert data == {"global": {}, "models": {}}

    # Set global defaults
    set_default("stream", True, filepath=d_file)
    set_default("temperature", 0.7, filepath=d_file)

    eff = get_effective_defaults(filepath=d_file)
    assert eff["stream"] is True
    assert eff["temperature"] == 0.7

    # Set model-specific default overriding global
    set_default("temperature", 0.2, model="qwen38_23GB", filepath=d_file)
    set_default("system", "You are an AI", model="qwen38_23GB", filepath=d_file)

    # For other model, global temperature is 0.7
    eff_other = get_effective_defaults(model="llama3_8b", filepath=d_file)
    assert eff_other["temperature"] == 0.7
    assert "system" not in eff_other

    # For qwen38_23GB, temperature is 0.2 and stream is inherited as True
    eff_qwen = get_effective_defaults(model="qwen38_23GB", filepath=d_file)
    assert eff_qwen["temperature"] == 0.2
    assert eff_qwen["stream"] is True
    assert eff_qwen["system"] == "You are an AI"

    # Clear model specific default
    clear_defaults(model="qwen38_23GB", filepath=d_file)
    eff_qwen_after = get_effective_defaults(model="qwen38_23GB", filepath=d_file)
    assert eff_qwen_after["temperature"] == 0.7
    assert "system" not in eff_qwen_after

    # Clear all defaults
    clear_defaults(filepath=d_file)
    assert get_effective_defaults(filepath=d_file) == {}
