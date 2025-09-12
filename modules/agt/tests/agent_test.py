from __future__ import annotations

from agt.agent import parse_tools, expand_attachments, build_prompt_with_attachments, apply_tools


def test_parse_tools_supports_both_fences(tmp_path):
    a = '```tool {"tool":"write_file","path":"x.txt","content":"hi"}```'
    b = '[[tool]] {"tool":"run","cmd":"echo ok"} [[/tool]]'
    tools = parse_tools(a + "\n" + b)
    kinds = {t["tool"] for t in tools}
    assert {"write_file", "run"} <= kinds


def test_attachments_and_prompt(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("AAA", encoding="utf-8")
    text, atts = expand_attachments(f"Hello @{f}")
    assert text == "Hello"
    assert atts and atts[0][0].endswith("a.txt")
    prompt = build_prompt_with_attachments(text, atts)
    assert "BEGIN_FILE" in prompt and "END_FILE" in prompt


def test_apply_tools_write_and_edit_and_run(monkeypatch, tmp_path):
    out1 = apply_tools('[[tool]] {"tool":"write_file","path":"p.txt","content":"one"} [[/tool]]',
                       ask=lambda *_: True)
    assert "Wrote" in out1[0]

    out2 = apply_tools('[[tool]] {"tool":"edit_file","path":"p.txt","patch":"two"} [[/tool]]',
                       ask=lambda *_: True)
    assert "Updated" in out2[0]

    # stub run
    from agt import agent as agent_mod
    orig = agent_mod.run_tool_run
    agent_mod.run_tool_run = lambda c, ask: "exit=0"
    try:
        out3 = apply_tools('[[tool]] {"tool":"run","cmd":"echo hi"} [[/tool]]', ask=lambda *_: True)
        assert "exit=0" in out3[0]
    finally:
        agent_mod.run_tool_run = orig
