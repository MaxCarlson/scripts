import pytest
import json
import tempfile
import os

@pytest.fixture(scope="function")
def mock_config_file():
    """Creates a temporary JSON config file for testing."""
    config_data = {
        "url": "http://fake-ai-platform.com",
        "selectors": {
            "prompt_input": {"by": "CSS_SELECTOR", "value": "#prompt-textarea"},
            "submit_button": {"by": "CSS_SELECTOR", "value": "button[data-testid='send-button']"},
            "response_area": {"by": "CSS_SELECTOR", "value": ".markdown.prose"},
            "last_response": {"by": "CSS_SELECTOR", "value": ".markdown.prose:last-of-type"},
            "parameters": {
                "temperature": {"by": "ID", "value": "temp-slider"}
            }
        }
    }
    
    # Use a temporary file that is automatically cleaned up
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json") as tmp:
        json.dump(config_data, tmp)
        config_path = tmp.name
    
    yield config_path
    
    # Cleanup the file after the test
    os.unlink(config_path)
