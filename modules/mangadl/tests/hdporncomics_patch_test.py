from mangadl.hdporncomics_patch import patch_recovery_hint, sanitize_windows_name


def test_sanitize_windows_name_handles_invalid_reserved_and_long_names() -> None:
    assert sanitize_windows_name("CON.txt") == "_CON.txt"
    assert sanitize_windows_name("bad: name?.jpg") == "bad_ name_.jpg"
    value = sanitize_windows_name("x" * 200)
    assert len(value) == 180
    assert value.endswith("_" + value[-12:])


def test_patch_recovery_hint_identifies_known_windows_error() -> None:
    assert patch_recovery_hint(
        "OSError: [WinError 123] The filename, directory name, or volume label syntax is incorrect"
    )
    assert patch_recovery_hint("network timeout") is None
