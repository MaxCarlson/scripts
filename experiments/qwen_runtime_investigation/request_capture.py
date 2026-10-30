#!/usr/bin/env python3
"""Capture safe OpenCode request parameters at a disposable mock provider."""

__version__ = "0.2.0"

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from typing import Any
from urllib.parse import urlsplit


SAFE_PARAMETERS = {
    "reasoning_effort",
    "reasoning",
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
    "temperature",
    "top_p",
    "top_k",
    "stream",
}


def safe_request_summary(path: str, request: dict[str, Any]) -> dict[str, Any]:
    """Return only an allowlisted scalar summary; never retain request content."""
    parameters = {
        key: value
        for key, value in request.items()
        if key in SAFE_PARAMETERS and (value is None or isinstance(value, (str, int, float, bool)))
    }
    tools = request.get("tools")
    return {
        "method": "POST",
        "path": urlsplit(path).path,
        "model": request.get("model") if isinstance(request.get("model"), str) else None,
        "request_fields": sorted(request.keys()),
        "tool_count": len(tools) if isinstance(tools, list) else 0,
        "parameters": parameters,
    }


def make_handler(captures: list[dict[str, Any]]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802
            size = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(size))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_error(400)
                return
            if not isinstance(payload, dict):
                self.send_error(400)
                return

            captures.append(safe_request_summary(self.path, payload))
            body = (
                'data: {"id":"mock","object":"chat.completion.chunk","created":1,'
                '"model":"mock","choices":[{"index":0,"delta":{"content":"READY"},'
                '"finish_reason":null}]}\n\n'
                'data: {"id":"mock","object":"chat.completion.chunk","created":1,'
                '"model":"mock","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}'
                '\n\ndata: [DONE]\n\n'
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return Handler


def isolated_environment(root: Path, config_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name, child in (
        ("APPDATA", "appdata"),
        ("LOCALAPPDATA", "localappdata"),
        ("USERPROFILE", "userprofile"),
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "xdg-config"),
        ("XDG_DATA_HOME", "xdg-data"),
        ("XDG_STATE_HOME", "xdg-state"),
        ("XDG_CACHE_HOME", "xdg-cache"),
    ):
        path = root / child
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    env["OPENCODE_CONFIG"] = str(config_path)
    env["OPENCODE_CONFIG_DIR"] = str(root / "opencode-config-dir")
    Path(env["OPENCODE_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
    return env


def write_config(path: Path, base_url: str, output_limit: int, explicit_variants: bool,
                 include_none: bool = False, agent_variant: str | None = None,
                 model_reasoning_option: str | None = None) -> None:
    model: dict[str, Any] = {
        "name": "Local worker: qwen38-27b-q4km",
        "limit": {"context": 98304, "output": output_limit},
    }
    if explicit_variants:
        model["reasoning"] = True
        model["variants"] = {
            effort: {"reasoningEffort": effort}
            for effort in (("none", "low", "medium", "xhigh") if include_none else ("low", "medium", "xhigh"))
        }
    if model_reasoning_option is not None:
        model["reasoning"] = True
        model["options"] = {"reasoningEffort": model_reasoning_option}
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": "lmstudio/qwen38_23GB",
        "provider": {
            "lmstudio": {
                "name": "LM Studio mock capture",
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": base_url, "apiKey": "mock-only"},
                "models": {"qwen38_23GB": model},
            }
        },
    }
    if agent_variant is not None:
        config["agent"] = {"benchmark-files": {"mode": "primary", "variant": agent_variant}}
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def run_attempt(
    executable: Path,
    project: Path,
    env: dict[str, str],
    variant: str | None,
    agent_variant: str | None = None,
) -> dict[str, Any]:
    prompt = "Reply with the single word READY. Do not call tools."
    command = [
        str(executable),
        "run",
        "--pure",
        "--format",
        "json",
        "--model",
        "lmstudio/qwen38_23GB",
        "--dir",
        str(project),
    ]
    if variant:
        command.extend(("--variant", variant))
    if agent_variant:
        command.extend(("--agent", "benchmark-files"))
    command.append(prompt)
    result = subprocess.run(
        command,
        cwd=project,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=90,
        check=False,
    )
    return {"requested_variant": variant, "exit_code": result.returncode}


def locate_opencode(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe",
        Path("C:/Program Files/LM Studio/resources/app/bin/opencode.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("OpenCode executable not found; supply --opencode-exe")


def run_scenario(
    executable: Path,
    *,
    output_limit: int,
    explicit_variants: bool,
    variants: tuple[str | None, ...],
    include_none: bool = False,
    agent_variant: str | None = None,
    model_reasoning_option: str | None = None,
) -> dict[str, Any]:
    captures: list[dict[str, Any]] = []
    class QuietThreadingHTTPServer(ThreadingHTTPServer):
        def handle_error(self, _request: Any, _client_address: Any) -> None:
            # OpenCode closes short-lived readiness connections during shutdown.
            return

    server = QuietThreadingHTTPServer(("127.0.0.1", 0), make_handler(captures))
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix="qwen-opencode-capture-") as scratch:
            root = Path(scratch)
            project = root / "synthetic-project"
            project.mkdir()
            config_path = root / "opencode.json"
            base_url = f"http://127.0.0.1:{server.server_port}/v1"
            write_config(config_path, base_url, output_limit, explicit_variants, include_none,
                         agent_variant, model_reasoning_option)
            env = isolated_environment(root, config_path)
            attempts = [run_attempt(executable, project, env, variant, agent_variant) for variant in variants]
        return {
            "output_limit": output_limit,
            "reasoning_capability_configured": explicit_variants,
            "agent_variant_configured": agent_variant,
            "model_reasoning_option": model_reasoning_option,
            "attempts": attempts,
            "captures": captures,
        }
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def validate_scenarios(scenarios: list[dict[str, Any]]) -> None:
    if len(scenarios) != 6:
        raise RuntimeError("expected six controlled scenarios")
    for scenario in scenarios:
        if not scenario["attempts"] or any(item["exit_code"] != 0 for item in scenario["attempts"]):
            raise RuntimeError("one or more mock-provider OpenCode attempts failed")
        if not scenario["captures"]:
            raise RuntimeError("mock provider captured no inference requests")
        if any(capture["path"] != "/v1/chat/completions" for capture in scenario["captures"]):
            raise RuntimeError("OpenCode used an unexpected provider endpoint")
        for capture in scenario["captures"]:
            if capture["parameters"].get("max_tokens") != scenario["output_limit"]:
                raise RuntimeError("OpenCode did not forward the configured output limit as max_tokens")
    baseline, output_comparison, explicit, no_reasoning, agent_variant, model_option = scenarios
    if any("reasoning_effort" in item["parameters"] for item in baseline["captures"]):
        raise RuntimeError("an unconfigured Qwen variant unexpectedly emitted reasoning_effort")
    if any("reasoning_effort" in item["parameters"] for item in output_comparison["captures"]):
        raise RuntimeError("an unconfigured Qwen variant unexpectedly emitted reasoning_effort")
    for effort in ("low", "medium", "xhigh"):
        captures = [
            item for item in explicit["captures"]
            if item["tool_count"] > 0 and item["parameters"].get("reasoning_effort") == effort
        ]
        if not captures:
            raise RuntimeError(f"explicit {effort} variant was not forwarded in a tool-bearing request")
    if not any(item["tool_count"] > 0 and item["parameters"].get("reasoning_effort") == "none"
               for item in no_reasoning["captures"]):
        raise RuntimeError("explicit none reasoning variant was not forwarded in a tool-bearing request")
    if not any(item["tool_count"] == 0 and item["parameters"].get("reasoning_effort") == "low"
               for item in agent_variant["captures"]):
        raise RuntimeError("agent-level low variant was not visible on its no-tool request")
    if not any(item["tool_count"] > 0 and "reasoning_effort" not in item["parameters"]
               for item in agent_variant["captures"]):
        raise RuntimeError("agent-level variant control changed: expected missing effort on tool-bearing request")
    if not any(item["tool_count"] > 0 and item["parameters"].get("reasoning_effort") == "low"
               for item in model_option["captures"]):
        raise RuntimeError("model-level reasoningEffort option was not forwarded in a tool-bearing request")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output-file", type=Path, required=True)
    parser.add_argument("-x", "--opencode-exe", help="Optional absolute OpenCode executable path")
    args = parser.parse_args()
    executable = locate_opencode(args.opencode_exe)
    scenarios = [
        run_scenario(executable, output_limit=8192, explicit_variants=False,
                     variants=(None, "low", "medium", "xhigh")),
        run_scenario(executable, output_limit=16384, explicit_variants=False,
                     variants=(None,)),
        run_scenario(executable, output_limit=8192, explicit_variants=True,
                     variants=("low", "medium", "xhigh")),
        run_scenario(executable, output_limit=16384, explicit_variants=True,
                     variants=("none",), include_none=True),
        run_scenario(executable, output_limit=8192, explicit_variants=True,
                     variants=(None,), agent_variant="low"),
        run_scenario(executable, output_limit=8192, explicit_variants=False,
                     variants=(None,), model_reasoning_option="low"),
    ]
    validation_error = None
    try:
        validate_scenarios(scenarios)
    except RuntimeError as error:
        validation_error = str(error)
    result = {
        "schema_version": 2,
        "capture_tool_version": __version__,
        "provider": "local OpenAI-compatible mock",
        "open_code_version": "1.19.3",
        "prompt_or_body_recorded": False,
        "credentials_recorded": False,
        "validation": "passed" if validation_error is None else "failed",
        "validation_error": validation_error,
        "scenarios": scenarios,
    }
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output_file": str(args.output_file.resolve()),
        "scenario_count": len(scenarios),
        "capture_count": sum(len(item["captures"]) for item in scenarios),
        "attempt_exit_codes": [attempt["exit_code"] for item in scenarios for attempt in item["attempts"]],
        "validation": result["validation"],
        "validation_error": validation_error,
    }, indent=2))
    return 0 if validation_error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
