# Web AI Automator

This module automates interactions with web-based AI platforms using Selenium and provides a Flask API for control.

## Installation

1. Install dependencies: `pip install selenium flask`
2. Ensure ChromeDriver or GeckoDriver is installed and in your PATH.

## Usage

1. Run the API server: `python api.py`
2. Use the API endpoints to initialize sessions, set parameters, send prompts, get responses, and close sessions.

## Configuration

Configuration files for different websites are in the `configs` directory. Add new JSON files to support additional sites.

## API Endpoints

- `/initialize`: POST with `config_file` (and optionally `browser`, `headless`) to start a new session.
- `/set_parameters/<session_id>`: POST with parameters to set.
- `/send_prompt/<session_id>`: POST with `prompt` to send.
- `/get_response/<session_id>`: GET to retrieve the response.
- `/close/<session_id>`: POST to close the session.

See the code and configuration files for more details.

## Security and Robustness

- Only config files in the `configs` directory can be loaded.
- Each session is auto-closed after 20 minutes of inactivity.
- CORS headers are enabled by default.
- Browser can be launched headless with `{"headless": true}` in `/initialize`.

## Compatibility

- Supports both Chrome and Firefox browsers. Use the `browser` parameter in `/initialize`.
