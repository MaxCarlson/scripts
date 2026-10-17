from __future__ import annotations

from termdash.table import Table, render_table, _strip_ansi, _visible_len


def test_visible_len_strips_ansi():
    colored = "\033[32mHello\033[0m"
    assert _visible_len(colored) == 5
    assert _strip_ansi(colored) == "Hello"


def test_table_basic_rendering():
    headers = ["Name", "Age", "City"]
    rows = [
        ["Alice", 30, "New York"],
        ["Bob", 25, "Los Angeles"],
    ]
    output = render_table(headers=headers, rows=rows, style="rule")
    assert "Alice" in output
    assert "New York" in output
    assert "Bob" in output
    assert "┌" in output
    assert "└" in output


def test_table_alignments():
    headers = ["Item", "Count"]
    rows = [
        ["Alpha", 1],
        ["Beta", 100],
    ]
    output = render_table(headers=headers, rows=rows, alignments=["left", "right"], style="dash")
    assert "+" in output
    assert "|" in output
    lines = output.splitlines()
    assert len(lines) >= 4


def test_table_ansi_color_alignment():
    headers = ["Status", "Value"]
    rows = [
        ["\033[32mOK\033[0m", "100"],
        ["\033[31mFAIL\033[0m", "0"],
    ]
    t = Table(headers=headers, style="rule")
    t.add_rows(rows)
    rendered = t.render()
    lines = rendered.splitlines()
    # Check that width of all lines is identical in visual columns
    clean_lines = [_strip_ansi(line) for line in lines]
    lengths = {len(line) for line in clean_lines}
    assert len(lengths) == 1, f"Lines have mismatched visual widths: {lengths}"


def test_empty_table():
    assert render_table() == ""
    assert render_table(headers=["A", "B"], rows=[]) != ""


def test_width_enforced_and_long_color_clipped():
    rendered = render_table(
        headers=["Folder", "State"], rows=[["\033[32m" + "a" * 100 + "\033[0m", "ok"]], max_width=30
    )
    assert max(_visible_len(line) for line in rendered.splitlines()) <= 30
    assert "…" in rendered


def test_cjk_combining_cells_aligned():
    rendered = render_table(headers=["Title", "Count"], rows=[["日本語", "1"], ["e\u0301", "2"]], max_width=24)
    assert _visible_len("日本語") == 6
    assert _visible_len("e\u0301") == 1
    assert len({_visible_len(line) for line in rendered.splitlines()}) == 1


def test_tiny_terminal_and_multiline_cell():
    rendered = render_table(headers=["A", "B"], rows=[["long\nvalue", "text"]], max_width=5)
    assert all(_visible_len(line) <= 5 for line in rendered.splitlines())
    assert len(rendered.splitlines()) == 2


def test_panel_renderer_preserves_all_values_unicode_and_color():
    from termdash.table import render_table_panels, _visible_len

    headers = ["ID", "Strategy", "Estimated retained", "Estimated saved", "Mean SSIM"]
    rows = [["01", "\x1b[34m漫画-e\u0301-lossless\x1b[0m", "128.00 GiB", "42.00 GiB", "0.983"]]
    for width in (12, 40, 60, 80, 160):
        panels = render_table_panels(headers, rows, identity_columns=(0, 1), max_width=width)
        output = "\n".join(panels)
        assert "…" not in output
        for value in ("128.00 GiB", "42.00 GiB", "0.983"):
            assert value in output
        assert all(_visible_len(line) <= width for line in output.splitlines())
