import pytest
from flask import json
from web_ai_automator import api
from unittest.mock import patch, MagicMock

@pytest.fixture
def client():
    api.app.config["TESTING"] = True
    with api.app.test_client() as client:
        yield client

def test_initialize_and_close_session(client, tmp_path):
    config = {
        "url": "https://example.com/",
        "login_required": False,
        "login_method": "manual",
        "elements": {
            "input_field": {"by": "id", "value": "i"},
            "submit_button": {"by": "id", "value": "s"},
            "response_area": {"by": "id", "value": "r"}
        },
        "parameters": {}
    }
    config_path = tmp_path / "conf.json"
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    with open(config_dir / "conf.json", "w") as f:
        json.dump(config, f)

    with patch("web_ai_automator.automator.webdriver.Chrome"):
        with patch("web_ai_automator.api.CONFIG_DIR", str(config_dir)):
            # Initialize session
            resp = client.post("/initialize", json={"config_file": "conf.json"})
            data = resp.get_json()
            assert "session_id" in data
            sid = data["session_id"]

            # Set parameters (even if no effect)
            resp = client.post(f"/set_parameters/{sid}", json={})
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "parameters set"

            # Send prompt
            with patch.object(api.sessions[sid], "enter_prompt") as m_enter, \
                 patch.object(api.sessions[sid], "submit") as m_submit:
                resp = client.post(f"/send_prompt/{sid}", json={"prompt": "hi"})
                assert resp.status_code == 200
                assert resp.get_json()["status"] == "prompt sent"
                m_enter.assert_called_with("hi")
                m_submit.assert_called_once()

            # Get response
            with patch.object(api.sessions[sid], "get_response", return_value="yo"):
                resp = client.get(f"/get_response/{sid}")
                assert resp.status_code == 200
                assert resp.get_json()["response"] == "yo"

            # Close session
            resp = client.post(f"/close/{sid}")
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "session closed"

def test_initialize_with_invalid_config(client, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    with patch("web_ai_automator.api.CONFIG_DIR", str(config_dir)):
        resp = client.post("/initialize", json={"config_file": "notfound.json"})
        assert resp.status_code == 400
        assert "error" in resp.get_json()

def test_set_parameters_invalid_sid(client):
    resp = client.post("/set_parameters/unknown", json={})
    assert resp.status_code == 404

def test_send_prompt_invalid_sid(client):
    resp = client.post("/send_prompt/unknown", json={"prompt": "hi"})
    assert resp.status_code == 404

def test_get_response_invalid_sid(client):
    resp = client.get("/get_response/unknown")
    assert resp.status_code == 404

def test_close_session_invalid_sid(client):
    resp = client.post("/close/unknown")
    assert resp.status_code == 404

def test_send_prompt_invalid_payload(client, tmp_path):
    config = {
        "url": "https://example.com/",
        "login_required": False,
        "login_method": "manual",
        "elements": {
            "input_field": {"by": "id", "value": "i"},
            "submit_button": {"by": "id", "value": "s"},
            "response_area": {"by": "id", "value": "r"}
        },
        "parameters": {}
    }
    config_path = tmp_path / "conf.json"
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    with open(config_dir / "conf.json", "w") as f:
        json.dump(config, f)
    with patch("web_ai_automator.automator.webdriver.Chrome"):
        with patch("web_ai_automator.api.CONFIG_DIR", str(config_dir)):
            resp = client.post("/initialize", json={"config_file": "conf.json"})
            sid = resp.get_json()["session_id"]
            # Send prompt with missing prompt
            resp = client.post(f"/send_prompt/{sid}", json={})
            assert resp.status_code == 400
            # Send prompt with wrong type
            resp = client.post(f"/send_prompt/{sid}", json={"prompt": 123})
            assert resp.status_code == 400

def test_cors_headers(client):
    resp = client.options("/get_response/unknown")
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"
