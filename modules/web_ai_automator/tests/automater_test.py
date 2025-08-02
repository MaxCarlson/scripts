import pytest
from unittest.mock import patch, MagicMock, call
from selenium.common.exceptions import TimeoutException
from web_ai_automator.automator import WebAIAutomator

# Note: The original file was named automater_test.py, it has been renamed to automator_test.py

@patch('web_ai_automator.automator.webdriver')
def test_start_browser_chrome(mock_webdriver, mock_config_file):
    """Test starting the Chrome browser."""
    automator = WebAIAutomator(mock_config_file, browser="chrome", headless=True)
    automator.start_browser()
    
    mock_webdriver.ChromeOptions.assert_called_once()
    options_instance = mock_webdriver.ChromeOptions.return_value
    assert options_instance.add_argument.call_count == 3
    options_instance.add_argument.assert_has_calls([
        call('--headless'),
        call('--disable-gpu'),
        call('--window-size=1920,1080')
    ], any_order=True)
    
    mock_webdriver.Chrome.assert_called_once_with(options=options_instance)
    automator.driver.get.assert_called_once_with("http://fake-ai-platform.com")
    assert automator.wait is not None

@patch('web_ai_automator.automator.webdriver')
def test_start_browser_firefox(mock_webdriver, mock_config_file):
    """Test starting the Firefox browser."""
    automator = WebAIAutomator(mock_config_file, browser="firefox", headless=False)
    automator.start_browser()
    
    mock_webdriver.FirefoxOptions.assert_called_once()
    options_instance = mock_webdriver.FirefoxOptions.return_value
    options_instance.add_argument.assert_not_called() # headless=False
    
    mock_webdriver.Firefox.assert_called_once_with(options=options_instance)
    automator.driver.get.assert_called_once_with("http://fake-ai-platform.com")

def test_start_browser_unsupported(mock_config_file):
    """Test that an unsupported browser raises a ValueError."""
    automator = WebAIAutomator(mock_config_file, browser="safari")
    with pytest.raises(ValueError, match="Unsupported browser: safari"):
        automator.start_browser()

@patch('web_ai_automator.automator.webdriver')
def test_close_browser(mock_webdriver, mock_config_file):
    """Test that the browser's quit method is called."""
    automator = WebAIAutomator(mock_config_file)
    automator.driver = mock_webdriver.Chrome.return_value
    automator.close_browser()
    automator.driver.quit.assert_called_once()

@patch('web_ai_automator.automator.webdriver')
def test_enter_prompt(mock_webdriver, mock_config_file):
    """Test entering a prompt."""
    automator = WebAIAutomator(mock_config_file)
    automator.driver = MagicMock()
    automator.wait = MagicMock()
    
    mock_prompt_element = MagicMock()
    automator.wait.until.return_value = mock_prompt_element
    
    automator.enter_prompt("Hello AI")
    
    mock_prompt_element.click.assert_called_once()
    mock_prompt_element.send_keys.assert_called_once_with("Hello AI")

@patch('web_ai_automator.automator.webdriver')
def test_submit(mock_webdriver, mock_config_file):
    """Test submitting the prompt."""
    automator = WebAIAutomator(mock_config_file)
    automator.driver = MagicMock()
    automator.wait = MagicMock()
    
    mock_submit_button = MagicMock()
    automator.wait.until.return_value = mock_submit_button
    
    automator.submit()
    
    automator.driver.execute_script.assert_called_once_with("arguments[0].click();", mock_submit_button)

@patch('web_ai_automator.automator.webdriver')
@patch('web_ai_automator.automator.time')
def test_get_response_success(mock_time, mock_webdriver, mock_config_file):
    """Test successfully getting a response."""
    automator = WebAIAutomator(mock_config_file)
    automator.driver = MagicMock()
    automator.wait = MagicMock()
    
    # Simulate finding one response element before submit, and two after
    automator.pre_submit_response_count = 1
    
    # Mock the final response element
    mock_response_element = MagicMock()
    mock_response_element.text = "This is the AI response."
    
    # The final `find_element` call should return our mock element
    automator.driver.find_element.return_value = mock_response_element
    
    # The wait should succeed
    automator.wait.until.side_effect = [
        True, # First wait for new container succeeds
        True, # Second wait for element presence succeeds
        True  # Third wait for text to populate succeeds
    ]

    response = automator.get_response()
    
    assert response == "This is the AI response."
    mock_time.sleep.assert_called_once_with(1)

@patch('web_ai_automator.automator.webdriver')
def test_get_response_timeout(mock_webdriver, mock_config_file):
    """Test a timeout when getting a response."""
    automator = WebAIAutomator(mock_config_file)
    automator.driver = MagicMock()
    automator.wait = MagicMock()
    
    # Make the wait call raise a TimeoutException
    automator.wait.until.side_effect = TimeoutException("Test Timeout")
    
    response = automator.get_response()
    
    assert response is None
