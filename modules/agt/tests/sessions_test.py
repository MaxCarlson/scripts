# tests/sessions_test.py
from agt.sessions import session_path, load_session, append_session

def test_session_path():
    p = session_path("test-session")
    assert p.name == "test-session.jsonl"
    assert p.parent.name == "sessions"

def test_load_and_append_session(tmp_path, monkeypatch):
    monkeypatch.setattr("agt.sessions.sessions_dir", lambda: tmp_path)
    
    # Test load non-existent
    msgs = load_session("test")
    assert msgs == []

    # Test append
    msg1 = {"role": "user", "content": "hello"}
    append_session("test", msg1)
    
    p = tmp_path / "test.jsonl"
    assert p.exists()
    assert p.read_text().strip() == '{"role": "user", "content": "hello"}'

    # Test load existing
    msgs = load_session("test")
    assert len(msgs) == 1
    assert msgs[0]["content"] == "hello"

    # Test append again
    msg2 = {"role": "assistant", "content": "hi"}
    append_session("test", msg2)
    msgs = load_session("test")
    assert len(msgs) == 2
