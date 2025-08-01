from flask import Flask, request, jsonify, make_response
import uuid
import os
import threading
import time
from web_ai_automator.automator import WebAIAutomator
from web_ai_automator.log_utils import setup_logger

logger = setup_logger("web_ai_automator.api")

app = Flask(__name__)
sessions = {}
session_times = {}
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs")
SESSION_TIMEOUT = 20 * 60  # 20 minutes

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response

def cleanup_sessions():
    while True:
        now = time.time()
        expired = []
        for sid, t in list(session_times.items()):
            if now - t > SESSION_TIMEOUT:
                expired.append(sid)
        for sid in expired:
            try:
                logger.info(f"Cleaning up expired session {sid}")
                sessions[sid].close_browser()
            except Exception as e:
                logger.warning(f"Exception while cleaning up session {sid}: {e}")
            sessions.pop(sid, None)
            session_times.pop(sid, None)
        time.sleep(60)

threading.Thread(target=cleanup_sessions, daemon=True).start()

def safe_config_file(config_filename):
    basename = os.path.basename(config_filename)
    path = os.path.abspath(os.path.join(CONFIG_DIR, basename))
    if not path.startswith(os.path.abspath(CONFIG_DIR)):
        raise ValueError("Invalid config file path")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config file not found: {basename}")
    return path

@app.route('/initialize', methods=['POST'])
def initialize():
    try:
        data = request.get_json(force=True)
        config_filename = data.get('config_file')
        browser = data.get('browser', 'chrome')
        headless = bool(data.get('headless', False))
        config_path = safe_config_file(config_filename)
        automator = WebAIAutomator(config_path, browser=browser, headless=headless)
        automator.start_browser()
        session_id = str(uuid.uuid4())
        sessions[session_id] = automator
        session_times[session_id] = time.time()
        logger.info(f"Session {session_id} initialized.")
        return jsonify({'session_id': session_id})
    except Exception as e:
        logger.error(f"Initialization error: {e}")
        return jsonify({'error': str(e), 'type': type(e).__name__}), 400

@app.route('/set_parameters/<session_id>', methods=['POST'])
def set_parameters(session_id):
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    try:
        params = request.get_json(force=True)
        sessions[session_id].set_parameters(params)
        session_times[session_id] = time.time()
        return jsonify({'status': 'parameters set'})
    except Exception as e:
        logger.error(f"Set parameters error: {e}")
        return jsonify({'error': str(e), 'type': type(e).__name__}), 400

@app.route('/send_prompt/<session_id>', methods=['POST'])
def send_prompt(session_id):
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    try:
        data = request.get_json(force=True)
        prompt = data.get('prompt')
        if not isinstance(prompt, str):
            return jsonify({'error': 'Invalid or missing prompt'}), 400
        sessions[session_id].enter_prompt(prompt)
        sessions[session_id].submit()
        session_times[session_id] = time.time()
        logger.info(f"Prompt sent for session {session_id}.")
        return jsonify({'status': 'prompt sent'})
    except Exception as e:
        logger.error(f"Send prompt error: {e}")
        return jsonify({'error': str(e), 'type': type(e).__name__}), 400

@app.route('/get_response/<session_id>', methods=['GET'])
def get_response(session_id):
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    try:
        response = sessions[session_id].get_response()
        session_times[session_id] = time.time()
        if response is None:
            return jsonify({'error': 'Failed to get response'}), 500
        logger.info(f"Response retrieved for session {session_id}.")
        return jsonify({'response': response})
    except Exception as e:
        logger.error(f"Get response error: {e}")
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500

@app.route('/close/<session_id>', methods=['POST'])
def close_session(session_id):
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    try:
        sessions[session_id].close_browser()
        del sessions[session_id]
        session_times.pop(session_id, None)
        logger.info(f"Session {session_id} closed.")
        return jsonify({'status': 'session closed'})
    except Exception as e:
        logger.error(f"Close session error: {e}")
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
