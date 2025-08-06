import pytest
from unittest.mock import patch, MagicMock

from web_ai_automator.cli import main

@patch('web_ai_automator.cli.argparse.ArgumentParser')
@patch('web_ai_automator.cli.WebAIAutomator')
def test_cli_with_prompt(mock_automator_class, mock_argparse, mock_config_file):
    """Test CLI execution with a prompt."""
    # Setup mock arguments
    mock_args = MagicMock()
    mock_args.config = mock_config_file
    mock_args.prompt = "Test prompt"
    mock_args.browser = "chrome"
    mock_args.headless = True
    mock_argparse.return_value.parse_args.return_value = mock_args

    # Setup mock automator instance
    mock_automator_instance = MagicMock()
    mock_automator_instance.get_response.return_value = "AI response"
    mock_automator_class.return_value = mock_automator_instance

    # Run the main CLI function
    main()

    # Assertions
    mock_automator_class.assert_called_once_with(mock_config_file, browser="chrome", headless=True)
    mock_automator_instance.start_browser.assert_called_once()
    mock_automator_instance.enter_prompt.assert_called_once_with("Test prompt")
    mock_automator_instance.submit.assert_called_once()
    mock_automator_instance.get_response.assert_called_once()
    mock_automator_instance.close_browser.assert_called_once()

@patch('builtins.input', return_value='')
@patch('web_ai_automator.cli.argparse.ArgumentParser')
@patch('web_ai_automator.cli.WebAIAutomator')
def test_cli_without_prompt(mock_automator_class, mock_argparse, mock_input, mock_config_file):
    """Test CLI execution in interactive mode (no prompt)."""
    # Setup mock arguments
    mock_args = MagicMock()
    mock_args.config = mock_config_file
    mock_args.prompt = None # No prompt provided
    mock_args.browser = "firefox"
    mock_args.headless = False
    mock_argparse.return_value.parse_args.return_value = mock_args

    # Setup mock automator instance
    mock_automator_instance = MagicMock()
    mock_automator_class.return_value = mock_automator_instance

    # Run the main CLI function
    main()

    # Assertions
    mock_automator_class.assert_called_once_with(mock_config_file, browser="firefox", headless=False)
    mock_automator_instance.start_browser.assert_called_once()
    mock_automator_instance.enter_prompt.assert_not_called()
    mock_automator_instance.submit.assert_not_called()
    mock_automator_instance.get_response.assert_not_called()
    mock_input.assert_called_once_with("Press Enter to close the browser...")
    mock_automator_instance.close_browser.assert_called_once()

@patch('builtins.print')
@patch('web_ai_automator.cli.argparse.ArgumentParser')
@patch('web_ai_automator.cli.WebAIAutomator')
def test_cli_exception_handling(mock_automator_class, mock_argparse, mock_print, mock_config_file):
    """Test that exceptions are caught and handled gracefully."""
    # Setup mock arguments
    mock_args = MagicMock()
    mock_args.config = mock_config_file
    mock_args.prompt = "prompt"
    mock_args.browser = "chrome"
    mock_args.headless = False
    mock_argparse.return_value.parse_args.return_value = mock_args

    # Setup mock automator to raise an error
    mock_automator_instance = MagicMock()
    mock_automator_instance.start_browser.side_effect = ValueError("Browser failed to start")
    mock_automator_class.return_value = mock_automator_instance

    main()

    mock_automator_instance.start_browser.assert_called_once()
    # Check that the error message was printed
    mock_print.assert_any_call("\nAn error occurred: Browser failed to start")
    # Check that close_browser is still called in the finally block
    mock_automator_instance.close_browser.assert_called_once()
