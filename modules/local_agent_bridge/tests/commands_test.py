from local_agent_bridge.commands import main
import local_agent_bridge.commands as commands_module
import local_agent_bridge.cli as cli_module
import pytest


def test_bare_help_and_isolated_plan_do_not_start_services(tmp_path, capsys):
    assert main([]) == 0
    assert "setup" in capsys.readouterr().out
    home = tmp_path / "empty"
    assert main(["setup", "plan", "-H", str(home), "-s", "copy", "-j"]) == 0
    assert not home.exists()
    assert "schema_version" in capsys.readouterr().out


def test_saved_plan_roundtrip_and_tampering(tmp_path, capsys):
    import json

    home = tmp_path / "home"
    saved = tmp_path / "plan.json"
    assert (
        main(
            [
                "setup",
                "plan",
                "-H",
                str(home),
                "-s",
                "copy",
                "-m",
                "generic",
                "-o",
                str(saved),
            ]
        )
        == 0
    )
    assert main(["setup", "apply", "-i", str(saved)]) == 0
    assert main(["setup", "status", "-H", str(home), "-s", "copy"]) == 0
    value = json.loads(saved.read_text())
    value["operations"][0]["path"] = str(tmp_path / "unrelated")
    saved.write_text(json.dumps(value))
    assert main(["setup", "apply", "-i", str(saved)]) == 4
    assert not (tmp_path / "unrelated").exists()
    capsys.readouterr()


def test_run_parser_keeps_management_in_model_group():
    from local_agent_bridge.cli import build_parser

    parser = build_parser(runtime_only=True)
    assert parser.parse_args(["-M", "ls"]).nickname == "ls"
    assert "--delete-model" not in parser.format_help()


def test_gpu_headroom_uses_shared_used_free_and_total_bytes(monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "resolve_executable", lambda _: "nvidia-smi")
    monkeypatch.setattr(
        cli_module,
        "nvidia_gpus",
        lambda **kwargs: [
            {
                "name": "RTX",
                "mem_used": 4 * 1024**3,
                "mem_free": 8 * 1024**3,
                "mem_total": 12 * 1024**3,
            }
        ],
    )

    cli_module.show_gpu_headroom()

    output = capsys.readouterr().out
    assert "Used: 4.00 GiB (4096 MiB)" in output
    assert "Free Headroom: 8.00 GiB (8192 MiB)" in output
    assert "Total: 12.00 GiB" in output


def test_opencode_status_reports_healthy_version_as_json(monkeypatch, capsys):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def geturl(self):
            return "http://127.0.0.1:4096/global/health"

        def read(self, size=-1):
            return b'{"healthy": true, "version": "1.19.3"}'

    seen = []
    monkeypatch.setattr(
        commands_module.urllib.request,
        "urlopen",
        lambda req, timeout: (seen.append((req.full_url, timeout)) or Response()),
    )
    monkeypatch.setattr(
        cli_module,
        "run_opencode_server_foreground",
        lambda *a, **k: pytest.fail("must not start runtime"),
    )

    assert main(["opencode", "status", "-j"]) == 0

    import json

    result = json.loads(capsys.readouterr().out)
    assert result == {
        "url": "http://127.0.0.1:4096",
        "reachable": True,
        "healthy": True,
        "version": "1.19.3",
        "error": None,
    }
    assert seen == [("http://127.0.0.1:4096/global/health", 3.0)]


def test_opencode_status_classifies_connection_refused(monkeypatch, capsys):
    from urllib.error import URLError

    monkeypatch.setattr(
        commands_module.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(URLError(ConnectionRefusedError())),
    )

    assert main(["opencode", "status"]) == 1

    output = capsys.readouterr().out
    assert "OpenCode: NOT RUNNING" in output
    assert "Connection refused" in output


def test_opencode_status_reports_local_socket_permission_as_execution_error(
    monkeypatch, capsys
):
    from urllib.error import URLError

    monkeypatch.setattr(
        commands_module.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(URLError(PermissionError(13, "blocked"))),
    )
    assert main(["opencode", "status", "-j"]) == 2
    result = __import__("json").loads(capsys.readouterr().out)
    assert result["error"]["type"] == "local_execution_error"


def test_opencode_status_classifies_timeout_and_malformed_or_unhealthy(
    monkeypatch, capsys
):
    from urllib.error import URLError

    monkeypatch.setattr(
        commands_module.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(URLError(TimeoutError())),
    )
    assert main(["opencode", "status", "-j"]) == 1
    assert '"type": "timeout"' in capsys.readouterr().out

    class Response:
        status = 200

        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def geturl(self):
            return "http://127.0.0.1:4096/global/health"

        def read(self, size=-1):
            return self.body

    monkeypatch.setattr(
        commands_module.urllib.request, "urlopen", lambda *a, **k: Response(b"not json")
    )
    assert main(["opencode", "status", "-j"]) == 1
    assert '"type": "invalid_response"' in capsys.readouterr().out

    monkeypatch.setattr(
        commands_module.urllib.request,
        "urlopen",
        lambda *a, **k: Response(b'{"healthy": false}'),
    )
    assert main(["opencode", "status"]) == 1
    assert "Health:  unhealthy" in capsys.readouterr().out


def test_opencode_status_classifies_unauthorized_without_printing_credentials(
    monkeypatch, capsys
):
    from urllib.error import HTTPError
    import io

    error = HTTPError(
        "http://127.0.0.1:4096/global/health", 401, "Unauthorized", {}, io.BytesIO()
    )
    monkeypatch.setattr(
        commands_module.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(error),
    )

    assert main(["opencode", "status", "-j"]) == 1

    output = capsys.readouterr().out
    assert '"type": "authentication_required"' in output
    assert "password" not in output.lower()


def test_opencode_status_ping_alias_and_http_error(monkeypatch, capsys):
    from urllib.error import HTTPError
    import io

    error = HTTPError(
        "http://127.0.0.1:4096/global/health", 503, "Unavailable", {}, io.BytesIO()
    )
    monkeypatch.setattr(
        commands_module.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(error),
    )
    assert main(["opencode", "ping", "-j"]) == 1
    result = __import__("json").loads(capsys.readouterr().out)
    assert result["reachable"] is True
    assert result["error"] == {
        "type": "http_error",
        "message": "HTTP 503.",
        "status_code": 503,
    }


def test_opencode_status_rejects_redirected_health_response(monkeypatch, capsys):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def geturl(self):
            return "https://other.example.test/global/health"

        def read(self, size=-1):
            return b'{"healthy": true, "version": "unexpected"}'

    monkeypatch.setattr(
        commands_module.urllib.request, "urlopen", lambda *a, **k: Response()
    )
    assert main(["opencode", "status", "-j"]) == 1
    result = __import__("json").loads(capsys.readouterr().out)
    assert result["healthy"] is False
    assert result["error"]["type"] == "unexpected_redirect"


def test_opencode_status_uses_local_auth_without_exposing_it(monkeypatch, capsys):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def geturl(self):
            return "http://127.0.0.1:4096/global/health"

        def read(self, size=-1):
            return b'{"healthy": true}'

    monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", "secret-value")
    monkeypatch.setenv("OPENCODE_SERVER_USERNAME", "local-user")
    request_headers = []
    monkeypatch.setattr(
        commands_module.urllib.request.Request,
        "get_header",
        lambda self, name: self.unredirected_hdrs.get(name.title()),
    )

    def urlopen(request, timeout):
        request_headers.append(request.get_header("Authorization"))
        return Response()

    monkeypatch.setattr(commands_module.urllib.request, "urlopen", urlopen)
    assert main(["opencode", "status"]) == 0
    assert request_headers == ["Basic bG9jYWwtdXNlcjpzZWNyZXQtdmFsdWU="]
    assert "secret-value" not in capsys.readouterr().out


def test_opencode_url_resolution_and_invalid_ambiguity(monkeypatch):
    monkeypatch.setenv("OPENCODE_BASE_URL", "http://localhost:5000")
    parser = commands_module.build_parser()
    assert (
        commands_module.resolve_opencode_url(parser.parse_args(["opencode", "status"]))
        == "http://localhost:5000"
    )
    assert (
        commands_module.resolve_opencode_url(
            parser.parse_args(["opencode", "status", "-p", "5001"])
        )
        == "http://127.0.0.1:5001"
    )
    assert (
        commands_module.resolve_opencode_url(
            parser.parse_args(["opencode", "status", "-u", "http://127.0.0.1:5002"])
        )
        == "http://127.0.0.1:5002"
    )
    with pytest.raises(ValueError, match="cannot be combined"):
        commands_module.resolve_opencode_url(
            parser.parse_args(
                ["opencode", "status", "-u", "http://localhost:5002", "-p", "5002"]
            )
        )
    with pytest.raises(ValueError, match="credentials"):
        commands_module.resolve_opencode_url(
            parser.parse_args(
                ["opencode", "status", "-u", "http://user:secret@example.test"]
            )
        )
    with pytest.raises(ValueError, match="between 1 and 65535"):
        commands_module.resolve_opencode_url(
            parser.parse_args(["opencode", "status", "-p", "65536"])
        )


def test_opencode_attach_forwards_args_inherits_terminal_and_propagates_exit(
    monkeypatch,
):
    monkeypatch.setattr(
        commands_module,
        "probe_opencode",
        lambda *a, **k: {"reachable": True, "healthy": True},
    )
    monkeypatch.setattr(
        commands_module.shutil, "which", lambda _: "C:/tools/opencode.exe"
    )
    seen = {}

    class Process:
        returncode = 7

        def __init__(self, argv, **kwargs):
            seen["argv"] = argv
            seen["kwargs"] = kwargs

        def wait(self):
            return self.returncode

    monkeypatch.setattr(commands_module.subprocess, "Popen", Process)

    assert (
        main(
            [
                "opencode",
                "attach",
                "-s",
                "ses_abc-123",
                "-d",
                "C:/Project Folder",
                "-p",
                "5000",
            ]
        )
        == 7
    )

    assert seen["argv"] == [
        "C:/tools/opencode.exe",
        "attach",
        "http://127.0.0.1:5000",
        "--session",
        "ses_abc-123",
        "--dir",
        str(commands_module.Path("C:/Project Folder")),
    ]
    assert seen["kwargs"]["shell"] is False
    assert (
        "stdin" not in seen["kwargs"]
        and "stdout" not in seen["kwargs"]
        and "stderr" not in seen["kwargs"]
    )


def test_opencode_attach_default_arguments_and_session_validation(monkeypatch):
    monkeypatch.setattr(
        commands_module,
        "probe_opencode",
        lambda *a, **k: {"reachable": True, "healthy": True},
    )
    monkeypatch.setattr(commands_module.shutil, "which", lambda _: "opencode")
    called = []

    class Process:
        returncode = 0

        def __init__(self, argv, **kwargs):
            called.append(argv)

        def wait(self):
            return 0

    monkeypatch.setattr(commands_module.subprocess, "Popen", Process)
    assert main(["opencode", "attach"]) == 0
    assert called == [["opencode", "attach", "http://127.0.0.1:4096"]]
    assert main(["opencode", "attach", "-s", "invalid session"]) == 2


def test_opencode_attach_refuses_missing_executable_or_unhealthy_server(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        commands_module,
        "probe_opencode",
        lambda *a, **k: {
            "reachable": False,
            "healthy": False,
            "error": {"message": "Connection refused"},
        },
    )
    monkeypatch.setattr(commands_module.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        commands_module.subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("must not launch"),
    )

    assert main(["opencode", "attach"]) == 1
    assert "Connection refused" in capsys.readouterr().err

    monkeypatch.setattr(
        commands_module,
        "probe_opencode",
        lambda *a, **k: {"reachable": True, "healthy": True},
    )
    assert main(["opencode", "attach"]) == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_opencode_attach_strips_local_auth_for_remote_custom_url(monkeypatch):
    monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", "secret-value")
    monkeypatch.setenv("OPENCODE_SERVER_USERNAME", "local-user")
    monkeypatch.setattr(
        commands_module,
        "probe_opencode",
        lambda *a, **k: {"reachable": True, "healthy": True},
    )
    monkeypatch.setattr(
        commands_module.shutil, "which", lambda _: "C:/tools/opencode.cmd"
    )
    captured = {}

    class Process:
        def __init__(self, argv, **kwargs):
            captured.update(kwargs)

        def wait(self):
            return 0

    monkeypatch.setattr(commands_module.subprocess, "Popen", Process)
    assert main(["opencode", "attach", "-u", "https://opencode.example.test"]) == 0
    assert captured["shell"] is False
    assert "OPENCODE_SERVER_PASSWORD" not in captured["env"]
    assert "OPENCODE_SERVER_USERNAME" not in captured["env"]
    assert captured["shell"] is False


def test_opencode_attach_ctrl_c_terminates_child(monkeypatch):
    monkeypatch.setattr(
        commands_module,
        "probe_opencode",
        lambda *a, **k: {"reachable": True, "healthy": True},
    )
    monkeypatch.setattr(commands_module.shutil, "which", lambda _: "opencode")
    events = []

    class Process:
        def __init__(self, *a, **k):
            pass

        def wait(self, timeout=None):
            if not events:
                events.append("interrupted")
                raise KeyboardInterrupt
            return 143

        def terminate(self):
            events.append("terminated")

    monkeypatch.setattr(commands_module.subprocess, "Popen", Process)
    assert main(["opencode", "attach"]) == 130
    assert events == ["interrupted", "terminated"]


def test_existing_cli_commands_keep_parsing_and_dispatch(monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit) as version:
        main(["--version"])
    assert version.value.code == 0
    assert "3.3.0" in capsys.readouterr().out

    # A temporary target keeps this regression check independent of the user's installed profiles.
    assert main(["setup", "status", "-H", str(tmp_path / "empty-home"), "-j"]) in {0, 3}
    capsys.readouterr()

    listed = []
    monkeypatch.setattr(cli_module, "handle_ls_command", lambda: listed.append(True))
    assert main(["model", "list"]) == 0
    assert listed == [True]

    with pytest.raises(SystemExit) as help_result:
        main(["run", "--help"])
    assert help_result.value.code == 0
    assert "local-agent run" in capsys.readouterr().out
