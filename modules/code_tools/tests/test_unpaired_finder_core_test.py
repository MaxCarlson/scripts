from unpaired_finder import scan_text_for_unpaired

def test_unpaired_and_mismatch_and_open_lines():
    text = """(
[  ]{
}"""
    issues, opens = scan_text_for_unpaired(text)
    assert any(i.kind == 'unpaired_open' for i in issues)
    assert 1 in opens

    text2 = "(]"
    issues2, _ = scan_text_for_unpaired(text2)
    assert any(i.kind == 'mismatch' for i in issues2)
