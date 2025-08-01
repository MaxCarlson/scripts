import pytest
import json
import os
from unittest.mock import patch, MagicMock
from web_ai_automator.automator import WebAIAutomator, BY_MAP

CONFIG_SAMPLE = {
    "url": "https://example.com/",
    "login_required": False,
    "login_method": "manual",
    "elements": {
        "input_field": {"by": "id", "value": "prompt-in"},
        "submit_button": {"by": "id", "value": "send"},
        "response_area": {"by": "id", "value": "reply"}
    },
    "parameters": {
        "temperature": {"by": "id", "value": "temp", "type": "slider"},
        "length": {"by": "id", "value": "len", "type": "input"},
        "grounded": {"by": "id", "value": "g", "type": "checkbox"}
    }
}

@pytest.fixture
def tmp_config(tmp_path):
    config_file = tmp_path / "test.json"
    with open(config_file, "w") as f:
        json.dump(CONFIG_SAMPLE, f)
    return str(config_file)

def make_mock_driver():
    driver = MagicMock()
    driver.find_element.return_value = MagicMock()
    return driver

@patch("web_ai_automator.automator.webdriver.Chrome")
def test_browser_init_and_close(mock_chrome, tmp_config):
    automator = WebAIAutomator(tmp_config, browser="chrome")
    mock_driver = make_mock_driver()
    mock_chrome.return_value = mock_driver
    automator.start_browser()
    assert automator.driver is mock_driver
    automator.close_browser()
    mock_driver.quit.assert_called_once()

@patch("web_ai_automator.automator.webdriver.Chrome")
def test_login_manual_waits_for_element(mock_chrome, tmp_config):
    conf = CONFIG_SAMPLE.copy()
    conf["login_required"] = True
    config_file = tmp_config
    with open(config_file, "w") as f:
        json.dump(conf, f)
    automator = WebAIAutomator(config_file)
    driver = make_mock_driver()
    mock_chrome.return_value = driver
    # Simulate element showing up immediately
    with patch("web_ai_automator.automator.WebDriverWait") as MockWait:
        MockWait.return_value.until.return_value = True
        automator.start_browser()
        MockWait.return_value.until.assert_called()

def test_by_map_valid_and_invalid(tmp_config):
    automator = WebAIAutomator(tmp_config)
    # Valid mapping
    assert automator._by("id") == BY_MAP["id"]
    # Invalid mapping
    with pytest.raises(ValueError):
        automator._by("notarealby")

def test_set_parameters_success(tmp_config):
    automator = WebAIAutomator(tmp_config)
    driver = make_mock_driver()
    automator.driver = driver
    # All types
    driver.find_element.return_value = elem = MagicMock()
    elem.is_selected.return_value = False
    automator.set_parameters({"temperature": 0.7, "length": 200, "grounded": True})
    assert driver.find_element.call_count == 3

def test_set_parameters_unknown_param(tmp_config):
    automator = WebAIAutomator(tmp_config)
    driver = make_mock_driver()
    automator.driver = driver
    # Should ignore unknown param without error
    automator.set_parameters({"unknown": 1})

def test_enter_prompt_and_submit(tmp_config):
    automator = WebAIAutomator(tmp_config)
    driver = make_mock_driver()
    automator.driver = driver
    # Enter prompt
    automator.enter_prompt("hello world")
    driver.find_element.return_value.clear.assert_called_once()
    driver.find_element.return_value.send_keys.assert_called_with("hello world")
    # Submit
    automator.submit()
    driver.find_element.return_value.click.assert_called_once()

def test_get_response_success(tmp_config):
    automator = WebAIAutomator(tmp_config)
    driver = make_mock_driver()
    automator.driver = driver
    driver.find_element.return_value.text = "AI reply"
    with patch("web_ai_automator.automator.WebDriverWait") as MockWait:
        MockWait.return_value.until.return_value = True
        assert automator.get_response(timeout=1) == "AI reply"

def test_get_response_failure(tmp_config):
    automator = WebAIAutomator(tmp_config)
    driver = make_mock_driver()
    automator.driver = driver
    with patch("web_ai_automator.automator.WebDriverWait") as MockWait:
        MockWait.side_effect = Exception("timeout")
        assert automator.get_response(timeout=1) is None

def test_close_browser_handles_exceptions(tmp_config):
    automator = WebAIAutomator(tmp_config)
    class Driver:
        def quit(self): raise RuntimeError("fail")
    automator.driver = Driver()
    # Should not raise
    automator.close_browser()
