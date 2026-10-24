from web_ui_tools.terminal import TerminalTextSanitizer


def test_sanitizer_strips_control_sequences_and_preserves_plain_text() -> None:
    sanitizer = TerminalTextSanitizer()
    value = sanitizer.feed("hello\x1b[31m red\x1b[0m\r\n\x1b]0;unsafe title\x07done\x07")
    assert value == "hello red\r\ndone"


def test_sanitizer_keeps_escape_and_utf8_chunk_boundaries_safe() -> None:
    sanitizer = TerminalTextSanitizer()
    chunks = ["before\x1b[", "31mred\x1b]0;bad", "\x1b\\ after <script>bad</script>\x00"]
    assert "".join(sanitizer.feed(chunk) for chunk in chunks) == "beforered after <script>bad</script>"


def test_sanitizer_bounds_unterminated_control_sequence_state() -> None:
    sanitizer = TerminalTextSanitizer(max_sequence_length=8)
    value = sanitizer.feed("start\x1b]" + "x" * 50 + " visible")
    assert value.endswith("visible")
    assert len(value) < 64
