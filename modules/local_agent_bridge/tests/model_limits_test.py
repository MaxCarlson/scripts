"""Model metadata verification and preservation tests; no live services."""

import json

import pytest

from local_agent_bridge import cli
from local_agent_bridge.commands import main


@pytest.fixture
def opencode_config(tmp_path, monkeypatch):
    path = tmp_path / ".config/opencode/opencode.json"
    monkeypatch.setattr(cli, "OPENCODE_CONFIG_PATH", path)
    monkeypatch.setattr(cli, "HOME_DIR", tmp_path)
    return path


@pytest.mark.parametrize(
    ("context", "output"),
    [(32768, 8192), (65536, 8192), (4096, 1024)],
)
def test_model_limits_accept_positive_integer_pairs(context, output):
    assert cli.validate_model_limits(context, output) == (context, output)


@pytest.mark.parametrize(
    ("context", "output"),
    [(0, 1), (-1, 1), (32768, 0), (32768, -1), (32768, 32768), (True, 1), (32768, 1.5)],
)
def test_model_limits_reject_invalid_pairs(context, output):
    with pytest.raises(ValueError):
        cli.validate_model_limits(context, output)


def test_opencode_model_limits_are_written_without_losing_user_fields(opencode_config):
    opencode_config.parent.mkdir(parents=True)
    opencode_config.write_text(
        json.dumps(
            {
                "model": "cloud/keep",
                "provider": {
                    "other": {"models": {"keep": {"name": "untouched"}}},
                    "lmstudio": {
                        "options": {"headers": {"X-User": "keep"}},
                        "models": {
                            "qwen38_23GB": {
                                "name": "User label",
                                "options": {"temperature": 0.2},
                                "limit": {"context": 65536, "output": 8192, "input": 60000},
                            }
                        },
                    },
                },
                "permission": {"bash": "ask"},
            }
        ),
        encoding="utf-8",
    )

    assert cli.update_opencode_for_model(
        "qwen38_23GB", "qwen/qwen3.8-27b@q4_k_m", 1234, 65536, 8192
    )

    saved = json.loads(opencode_config.read_text(encoding="utf-8"))
    model = saved["provider"]["lmstudio"]["models"]["qwen38_23GB"]
    assert model["limit"] == {"context": 65536, "output": 8192, "input": 60000}
    assert model["name"] == "User label"
    assert model["options"] == {"temperature": 0.2}
    assert saved["provider"]["lmstudio"]["options"] == {
        "headers": {"X-User": "keep"},
        "baseURL": "http://127.0.0.1:1234/v1",
    }
    assert saved["provider"]["other"] == {"models": {"keep": {"name": "untouched"}}}
    assert saved["permission"] == {"bash": "ask"}
    assert saved["model"] == "lmstudio/qwen38_23GB"


def test_opencode_limit_conflict_requires_explicit_correction(opencode_config):
    opencode_config.parent.mkdir(parents=True)
    opencode_config.write_text(
        json.dumps(
            {
                "provider": {
                    "lmstudio": {
                        "models": {"qwen": {"limit": {"context": 32768, "output": 8192}}}
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="conflict"):
        cli.update_opencode_for_model("qwen", "qwen/Qwen3", 1234, 65536, 8192)

    assert cli.update_opencode_for_model(
        "qwen", "qwen/Qwen3", 1234, 65536, 8192, overwrite_limits=True
    )
    saved = json.loads(opencode_config.read_text(encoding="utf-8"))
    assert saved["provider"]["lmstudio"]["models"]["qwen"]["limit"] == {
        "context": 65536,
        "output": 8192,
    }


def test_opencode_jsonc_comments_and_structure_survive_limit_updates(opencode_config):
    opencode_config.parent.mkdir(parents=True)
    original = """{
  // keep this user comment
  "provider": {
    "lmstudio": {
      "options": {"headers": {"X-User": "keep"}},
      "models": {
        "qwen38_23GB": {
          // alias note stays in place
          "name": "Qwen user label",
          "limit": {"context": 65536, /* output note stays */ "output": 8192}
        }
      }
    },
    "other": {"models": {"keep": {"name": "untouched"}}}
  },
  "permission": {"bash": "ask"}
}
"""
    opencode_config.write_text(original, encoding="utf-8")

    assert cli.update_opencode_for_model(
        "qwen38_23GB", "qwen/Qwen3", 1234, 65536, 8192
    )

    saved_text = opencode_config.read_text(encoding="utf-8")
    saved = cli.load_opencode_config()
    assert "// keep this user comment" in saved_text
    assert "// alias note stays in place" in saved_text
    assert "/* output note stays */" in saved_text
    assert saved["provider"]["lmstudio"]["models"]["qwen38_23GB"]["limit"] == {
        "context": 65536,
        "output": 8192,
    }
    assert saved["provider"]["lmstudio"]["options"] == {
        "headers": {"X-User": "keep"},
        "baseURL": "http://127.0.0.1:1234/v1",
    }
    assert saved["permission"]["bash"] == "ask"


def test_opencode_provider_conflict_requires_explicit_correction(opencode_config):
    opencode_config.parent.mkdir(parents=True)
    opencode_config.write_text(
        json.dumps(
            {
                "provider": {
                    "lmstudio": {
                        "npm": "custom-provider",
                        "options": {"baseURL": "http://127.0.0.1:9999/v1", "headers": {"X-User": "keep"}},
                        "models": {"qwen": {"limit": {"context": 32768, "output": 8192}}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    before = opencode_config.read_bytes()
    with pytest.raises(RuntimeError, match="--update-opencode-provider"):
        cli.update_opencode_for_model("qwen", "qwen/Qwen3", 1234, 32768, 8192)
    assert opencode_config.read_bytes() == before

    cli.update_opencode_for_model(
        "qwen", "qwen/Qwen3", 1234, 32768, 8192, overwrite_provider=True
    )
    saved = json.loads(opencode_config.read_text(encoding="utf-8"))
    provider = saved["provider"]["lmstudio"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"]["baseURL"] == "http://127.0.0.1:1234/v1"
    assert provider["options"]["headers"] == {"X-User": "keep"}


def test_run_limits_keep_32k_default_and_use_named_profile_output(opencode_config):
    assert cli.resolve_run_limits({}, "other-model", None, None) == (32768, None)
    assert cli.resolve_run_limits({}, "qwen38_23GB", 65536, None) == (65536, 8192)
    with pytest.raises(RuntimeError, match="also requires --output-tokens"):
        cli.resolve_run_limits({}, "other-model", 65536, None)
    existing = {
        "provider": {
            "lmstudio": {
                "models": {"qwen38_23GB": {"limit": {"context": 65536, "output": 8192}}}
            }
        }
    }
    assert cli.resolve_run_limits(existing, "qwen38_23GB", None, None) == (65536, 8192)


def test_null_limit_metadata_is_a_conflict_until_explicit_correction():
    cfg = {
        "provider": {
            "lmstudio": {
                "models": {"qwen": {"limit": {"context": 32768, "output": None}}}
            }
        }
    }
    with pytest.raises(RuntimeError, match="invalid output limit"):
        cli.resolve_run_limits(cfg, "qwen", None, None)
    assert cli.resolve_run_limits(cfg, "qwen", None, 8192, overwrite=True) == (32768, 8192)


def test_model_rename_preserves_loaded_64k_context_and_alias_limits(opencode_config, monkeypatch):
    opencode_config.parent.mkdir(parents=True)
    opencode_config.write_text(
        json.dumps(
            {
                "model": "lmstudio/qwen38_23GB",
                "provider": {
                    "lmstudio": {
                        "models": {
                            "qwen38_23GB": {
                                "name": "Qwen",
                                "limit": {"context": 65536, "output": 8192},
                                "lms_model": "qwen/qwen3.8-27b@q4_k_m",
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = cli.LoadedInstance("qwen38_23GB", "/models/qwen-q4.gguf", "20 GiB", "", 65536, "LOADED")
    monkeypatch.setattr(cli, "get_loaded_instance", lambda _: (loaded, ""))
    monkeypatch.setattr(cli, "resolve_model_selection", lambda spec: cli.ModelSelection("qwen3.8-27b", "qwen-q4", "q4", spec, ""))
    load_calls = []
    monkeypatch.setattr(cli, "run_cmd", lambda command, **kwargs: load_calls.append(command) or cli.CmdResult(0, "", ""))
    monkeypatch.setattr(cli, "update_codex_mcp_toml", lambda *args: True)
    monkeypatch.setattr(cli, "update_agy_mcp_configs", lambda *args: (True, ("global", "cli")))

    cli.handle_rename_model("qwen38_23GB", "qwen-renamed", 1234, 4096)

    load_call = next(command for command in load_calls if command[1] == "load")
    assert load_call[load_call.index("--context-length") + 1] == "65536"
    saved = json.loads(opencode_config.read_text(encoding="utf-8"))
    assert saved["provider"]["lmstudio"]["models"]["qwen-renamed"]["limit"] == {
        "context": 65536,
        "output": 8192,
    }


def test_model_rename_refuses_unknown_loaded_context_before_mutation(opencode_config, monkeypatch):
    opencode_config.parent.mkdir(parents=True)
    opencode_config.write_text(
        json.dumps({"provider": {"lmstudio": {"models": {"qwen": {"limit": {"context": 65536, "output": 8192}}}}}}),
        encoding="utf-8",
    )
    before = opencode_config.read_bytes()
    monkeypatch.setattr(
        cli,
        "get_loaded_instance",
        lambda _: (cli.LoadedInstance("qwen", "/models/qwen.gguf", "", "", None, "LOADED"), ""),
    )
    with pytest.raises(RuntimeError, match="did not report the loaded context"):
        cli.handle_rename_model("qwen", "qwen-renamed", 1234, 4096)
    assert opencode_config.read_bytes() == before


def test_model_verify_reports_static_effective_and_loaded_values(opencode_config, monkeypatch, capsys):
    opencode_config.parent.mkdir(parents=True)
    opencode_config.write_text(
        json.dumps(
            {
                "model": "lmstudio/qwen",
                "provider": {
                    "lmstudio": {
                        "npm": "@ai-sdk/openai-compatible",
                        "options": {"baseURL": "http://127.0.0.1:1234/v1"},
                        "models": {"qwen": {"limit": {"context": 65536, "output": 8192}}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    requests = []

    def response(url, timeout=3.0):
        requests.append(url)
        if "/config/providers" in url:
            return {
                "providers": [
                    {"id": "lmstudio", "models": {"qwen": {"limit": {"context": 65536, "output": 8192}}}}
                ],
                "default": {"lmstudio": "qwen"},
            }
        return {"model": "lmstudio/qwen"}

    monkeypatch.setattr(cli, "http_get_json", response)
    monkeypatch.setattr(
        cli,
        "get_loaded_instance",
        lambda nickname: (
            cli.LoadedInstance(nickname, "/models/qwen-q4.gguf", "20 GiB", "", 65536, "LOADED"),
            "",
        ),
    )

    assert main(
        ["model", "verify", "qwen", "-j", "-c", "65536", "-o", "8192", "-d", "C:/project space"]
    ) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok"
    assert result["requested"] == {"context": 65536, "output": 8192}
    assert result["configured"]["context"] == 65536
    assert result["configured"]["output"] == 8192
    assert result["configured"]["provider"] == "lmstudio"
    assert result["configured"]["alias"] == "qwen"
    assert result["effective_opencode"] == {
        "reachable": True,
        "model": "lmstudio/qwen",
        "provider": "lmstudio",
        "alias": "qwen",
        "context": 65536,
        "output": 8192,
        "base_url": None,
    }
    assert result["loaded_lm_studio"]["context"] == 65536
    assert any("directory=" in url and "project+space" in url for url in requests)


def test_model_verify_static_fallback_is_explicitly_lower_confidence(opencode_config, monkeypatch, capsys):
    opencode_config.parent.mkdir(parents=True)
    opencode_config.write_text(
        json.dumps(
            {
                "model": "lmstudio/qwen",
                "provider": {
                    "lmstudio": {
                        "npm": "@ai-sdk/openai-compatible",
                        "options": {"baseURL": "http://127.0.0.1:1234/v1"},
                        "models": {"qwen": {"limit": {"context": 32768, "output": 4096}}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "http_get_json", lambda *a, **k: None)
    monkeypatch.setattr(cli, "get_loaded_instance", lambda _: (None, ""))

    assert main(["model", "verify", "qwen", "-j"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["effective_opencode"]["reachable"] is False
    assert result["loaded_lm_studio"]["context"] is None
    assert result["requested"] == {"context": None, "output": None}
    assert any("offline" in warning.lower() for warning in result["warnings"])


def test_model_verify_detects_configured_and_effective_mismatches(opencode_config, monkeypatch, capsys):
    opencode_config.parent.mkdir(parents=True)
    opencode_config.write_text(
        json.dumps(
            {
                "model": "lmstudio/qwen",
                "provider": {"lmstudio": {"models": {"qwen": {"limit": {"context": 32768, "output": 4096}}}}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "http_get_json",
        lambda url, **_: (
            {"providers": [{"id": "lmstudio", "models": {"qwen": {"limit": {"context": 65536, "output": 8192}}}}]}
            if "/config/providers" in url
            else {"model": "lmstudio/qwen"}
        ),
    )
    monkeypatch.setattr(cli, "get_loaded_instance", lambda _: (None, ""))

    assert main(["model", "verify", "qwen", "-j", "-c", "65536", "-o", "8192"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "mismatch"
    assert result["configured"]["context"] == 32768
    assert result["effective_opencode"]["context"] == 65536
    assert result["diagnostics"]


def test_model_verify_reports_known_loaded_context_mismatch(opencode_config, monkeypatch, capsys):
    opencode_config.parent.mkdir(parents=True)
    opencode_config.write_text(
        json.dumps(
            {
                "model": "lmstudio/qwen",
                "provider": {"lmstudio": {"models": {"qwen": {"limit": {"context": 65536, "output": 8192}}}}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "http_get_json", lambda url, **_: ({"providers": [{"id": "lmstudio", "models": {"qwen": {"limit": {"context": 65536, "output": 8192}}}}]} if "/config/providers" in url else {"model": "lmstudio/qwen"}))
    monkeypatch.setattr(
        cli,
        "get_loaded_instance",
        lambda _: (cli.LoadedInstance("qwen", "/models/qwen.gguf", "", "", 32768, "LOADED"), ""),
    )

    assert main(["model", "verify", "qwen", "-j"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["loaded_lm_studio"]["context"] == 32768
    assert any("loaded context 32768" in issue for issue in result["diagnostics"])


def test_model_verify_detects_missing_provider_endpoint_configuration(opencode_config, monkeypatch, capsys):
    opencode_config.parent.mkdir(parents=True)
    opencode_config.write_text(
        json.dumps(
            {
                "model": "lmstudio/qwen",
                "provider": {"lmstudio": {"models": {"qwen": {"limit": {"context": 32768, "output": 4096}}}}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "http_get_json",
        lambda url, **_: (
            {"providers": [{"id": "lmstudio", "models": {"qwen": {"limit": {"context": 32768, "output": 4096}}}}]}
            if "/config/providers" in url
            else {"model": "lmstudio/qwen"}
        ),
    )
    monkeypatch.setattr(cli, "get_loaded_instance", lambda _: (None, ""))

    assert main(["model", "verify", "qwen", "-j"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert any("baseURL" in issue for issue in result["diagnostics"])
    assert any("provider package" in issue for issue in result["diagnostics"])


def test_run_configures_64k_qwen_profile_without_live_processes(opencode_config, monkeypatch, capsys):
    selection = cli.ModelSelection("qwen3.8-27b", "qwen-q4", "q4_k_m", "qwen/qwen3.8-27b@q4_k_m", "20 GiB")
    loaded = cli.LoadedInstance("qwen38_23GB", "/models/qwen3.8-27b-Q4_K_M.gguf", "20 GiB", "", 65536, "LOADED")
    get_loaded_calls = iter([(None, ""), (loaded, "")])
    load_commands = []
    monkeypatch.setattr(cli, "check_prerequisites", lambda *a, **k: None)
    monkeypatch.setattr(cli, "resolve_model_selection", lambda *a, **k: selection)
    monkeypatch.setattr(cli, "unload_other_loaded_llms", lambda _: None)
    monkeypatch.setattr(cli, "get_loaded_instance", lambda _: next(get_loaded_calls))
    monkeypatch.setattr(cli, "run_cmd", lambda command, **kwargs: load_commands.append(command) or cli.CmdResult(0, "", ""))
    monkeypatch.setattr(cli, "show_gpu_headroom", lambda: None)
    monkeypatch.setattr(cli, "show_recommended_settings", lambda _: None)

    assert cli.main(
        ["-M", "qwen38_23GB", "-m", "qwen/qwen3.8-27b@q4_k_m", "-c", "65536", "-N", "--no-codex", "--no-agy"],
        runtime_only=True,
    ) == 0

    load = next(command for command in load_commands if len(command) > 1 and command[1] == "load")
    assert load[load.index("--context-length") + 1] == "65536"
    configured = json.loads(opencode_config.read_text(encoding="utf-8"))
    assert configured["provider"]["lmstudio"]["models"]["qwen38_23GB"]["limit"] == {
        "context": 65536,
        "output": 8192,
    }
    capsys.readouterr()


def test_verify_cli_is_read_only_and_run_keeps_existing_flags():
    from local_agent_bridge.commands import build_parser

    parser = build_parser()
    args = parser.parse_args(["model", "verify", "qwen", "-j"])
    assert (args.group, args.action, args.nickname, args.json) == ("model", "verify", "qwen", True)
    run = cli.build_parser(runtime_only=True).parse_args(["-M", "qwen", "-c", "65536"])
    assert run.nickname == "qwen"
    assert run.context_length == 65536


def test_model_verify_invalid_limits_return_usage_exit_code(opencode_config, capsys):
    assert main(["model", "verify", "qwen", "-j", "-c", "32768"]) == 2
    error = json.loads(capsys.readouterr().out)
    assert error["status"] == "error"
    assert "must be supplied together" in error["diagnostics"][0]

    assert main(["model", "verify", "qwen", "-j", "-c", "32768", "-o", "32768"]) == 2
    error = json.loads(capsys.readouterr().out)
    assert "less than" in error["diagnostics"][0]
