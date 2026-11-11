"""Comprehensive unit, integration, and security tests for independent off-host outage monitoring (Phase 04).

Covers:
- N12: Off-host outage detection independence (no local broker, SQLite, or desktop session required).
- N13: Healthchecks.io integration semantics, failure modes, redaction, and HTTPS enforcement.
- Heartbeat configuration lifecycle, permissions, and env var overrides.
- Service and Windows Scheduled Task lifecycle (dry-run, apply, structured PowerShell arguments).
- Diagnostic doctor probe.
- CLI heartbeat subcommands.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from notifications.cli import main
from notifications.exceptions import SecurityError, ValidationError
from notifications.monitoring.config import (
    HealthchecksConfig,
    default_healthchecks_config_path,
    delete_healthchecks_config,
    load_healthchecks_config,
    redact_ping_url,
    save_healthchecks_config,
)
from notifications.monitoring.heartbeat import (
    DEFAULT_TIMEOUT_SECONDS,
    USER_AGENT,
    HeartbeatResult,
    send_heartbeat,
)
from notifications.monitoring.runner import main as runner_main
from notifications.monitoring.service import (
    TASK_NAME,
    doctor,
    get_heartbeat_task_status,
    install_heartbeat_task,
    uninstall_heartbeat_task,
)

SAMPLE_UUID = "b46a1e9c-4f7d-41a2-8e10-912837465abc"
SAMPLE_PING_URL = f"https://hc-ping.com/{SAMPLE_UUID}"


# ==============================================================================
# 1. Configuration & Security Tests
# ==============================================================================


def test_config_initialization_valid():
    cfg = HealthchecksConfig(
        ping_url=SAMPLE_PING_URL,
        interval_minutes=10,
        check_name="Workstation Primary",
        created_at="2026-11-11T12:00:00Z",
    )
    assert cfg.ping_url == SAMPLE_PING_URL
    assert cfg.interval_minutes == 10
    assert cfg.check_name == "Workstation Primary"

    data = cfg.to_dict()
    assert data["ping_url"] == SAMPLE_PING_URL
    assert data["interval_minutes"] == 10
    assert data["check_name"] == "Workstation Primary"

    rehydrated = HealthchecksConfig.from_dict(data)
    assert rehydrated == cfg


def test_config_rejects_insecure_http_by_default(monkeypatch):
    monkeypatch.delenv("NOTIFICATIONS_ALLOW_INSECURE_PING", raising=False)
    with pytest.raises(ValidationError, match="HTTPS"):
        HealthchecksConfig(ping_url=f"http://hc-ping.com/{SAMPLE_UUID}")


def test_config_allows_insecure_http_when_flag_enabled(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ALLOW_INSECURE_PING", "1")
    cfg = HealthchecksConfig(ping_url=f"http://hc-ping.com/{SAMPLE_UUID}")
    assert cfg.ping_url.startswith("http://")


def test_config_rejects_missing_host():
    with pytest.raises(ValidationError, match="missing host"):
        HealthchecksConfig(ping_url="https://")


def test_config_rejects_embedded_user_credentials():
    with pytest.raises(ValidationError, match="user credentials"):
        HealthchecksConfig(ping_url=f"https://admin:pass@hc-ping.com/{SAMPLE_UUID}")


@pytest.mark.parametrize("invalid_interval", [0, -5, 61, 120])
def test_config_rejects_out_of_bound_intervals(invalid_interval):
    with pytest.raises(ValidationError, match="between 1 and 60 minutes"):
        HealthchecksConfig(ping_url=SAMPLE_PING_URL, interval_minutes=invalid_interval)


def test_config_save_load_delete(tmp_path: Path):
    secrets_file = tmp_path / "secrets" / "healthchecks.json"
    cfg = HealthchecksConfig(
        ping_url=SAMPLE_PING_URL,
        interval_minutes=15,
        check_name="Backup Node",
    )

    saved_path = save_healthchecks_config(cfg, path=secrets_file)
    assert saved_path == secrets_file
    assert secrets_file.is_file()

    loaded = load_healthchecks_config(path=secrets_file)
    assert loaded is not None
    assert loaded.ping_url == SAMPLE_PING_URL
    assert loaded.interval_minutes == 15
    assert loaded.check_name == "Backup Node"

    deleted = delete_healthchecks_config(path=secrets_file)
    assert deleted is True
    assert not secrets_file.is_file()

    # Second delete returns False
    assert delete_healthchecks_config(path=secrets_file) is False


def test_config_fail_secure_atomic_replacement(tmp_path: Path):
    secrets_file = tmp_path / "secrets" / "healthchecks.json"
    initial_cfg = HealthchecksConfig(
        ping_url=SAMPLE_PING_URL,
        interval_minutes=5,
        check_name="Initial Valid Config",
    )
    save_healthchecks_config(initial_cfg, path=secrets_file)
    original_content = secrets_file.read_text("utf-8")

    # Attempt to save a new config, but simulate an ACL failure on the temp file
    broken_cfg = HealthchecksConfig(
        ping_url=f"https://hc-ping.com/99999999-9999-9999-9999-999999999999",
        interval_minutes=10,
        check_name="Broken Update",
    )

    call_count = [0]
    real_secure = None
    import notifications.monitoring.config as cfg_module
    orig_secure = cfg_module._secure_path

    def failing_secure(p: Path):
        call_count[0] += 1
        # Fail on temp file securing (the second call to _secure_path)
        if ".tmp_healthchecks_" in str(p):
            raise SecurityError("Simulated ACL permission denial on temp file")
        return orig_secure(p)

    with patch.object(cfg_module, "_secure_path", side_effect=failing_secure):
        with pytest.raises(SecurityError, match="Simulated ACL permission denial"):
            save_healthchecks_config(broken_cfg, path=secrets_file)

    # Destination file MUST be preserved unmodified
    assert secrets_file.is_file()
    assert secrets_file.read_text("utf-8") == original_content
    # No temporary files left behind in parent directory
    temp_files = list(secrets_file.parent.glob(".tmp_healthchecks_*"))
    assert len(temp_files) == 0


def test_config_rejects_symlinks(tmp_path: Path):
    target_file = tmp_path / "real.json"
    target_file.write_text("{}", encoding="utf-8")
    symlink_file = tmp_path / "symlink.json"

    try:
        symlink_file.symlink_to(target_file)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported in current Windows environment")

    cfg = HealthchecksConfig(ping_url=SAMPLE_PING_URL)
    with pytest.raises(SecurityError, match="symbolic link"):
        save_healthchecks_config(cfg, path=symlink_file)


def test_config_env_var_precedence(tmp_path: Path, monkeypatch):
    secrets_file = tmp_path / "secrets" / "healthchecks.json"
    cfg = HealthchecksConfig(
        ping_url=SAMPLE_PING_URL,
        interval_minutes=5,
        check_name="File Config",
    )
    save_healthchecks_config(cfg, path=secrets_file)

    # Without env vars, loads file
    loaded = load_healthchecks_config(path=secrets_file)
    assert loaded.check_name == "File Config"

    # Set env vars
    env_uuid = "11111111-2222-3333-4444-555555555555"
    monkeypatch.setenv("NOTIFY_HEALTHCHECKS_PING_URL", f"https://hc-ping.com/{env_uuid}")
    monkeypatch.setenv("NOTIFY_HEALTHCHECKS_INTERVAL", "3")
    monkeypatch.setenv("NOTIFY_HEALTHCHECKS_CHECK_NAME", "Env Override")

    override = load_healthchecks_config(path=secrets_file)
    assert override is not None
    assert override.ping_url == f"https://hc-ping.com/{env_uuid}"
    assert override.interval_minutes == 3
    assert override.check_name == "Env Override"


def test_redact_ping_url():
    assert redact_ping_url("") == ""
    url = f"https://hc-ping.com/{SAMPLE_UUID}"
    redacted = redact_ping_url(url)
    assert SAMPLE_UUID not in redacted
    assert "[REDACTED_PING_UUID]" in redacted

    msg = f"Ping failed for https://hc-ping.com/slug-secret-name with code 500"
    assert "slug-secret-name" not in redact_ping_url(msg)

    raw_msg = f"Encountered {SAMPLE_UUID} in error trace"
    assert SAMPLE_UUID not in redact_ping_url(raw_msg)
    assert "[REDACTED_UUID]" in redact_ping_url(raw_msg)


# ==============================================================================
# 2. Heartbeat Client (send_heartbeat) Tests
# ==============================================================================


def test_send_heartbeat_success_200():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("User-Agent") == USER_AGENT
        assert str(request.url) == SAMPLE_PING_URL
        assert request.method == "GET"
        return httpx.Response(200, text="OK")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = send_heartbeat(SAMPLE_PING_URL, client=client)

    assert result.success is True
    assert result.status_code == 200
    assert result.error_category is None
    assert result.error_message is None
    assert result.duration_ms >= 0
    assert result.timestamp != ""


def test_send_heartbeat_modes():
    visited_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited_urls.append((request.method, str(request.url)))
        return httpx.Response(200, text="OK")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    send_heartbeat(SAMPLE_PING_URL, mode="start", client=client)
    assert visited_urls[-1] == ("GET", f"{SAMPLE_PING_URL}/start")

    send_heartbeat(SAMPLE_PING_URL, mode="fail", client=client)
    assert visited_urls[-1] == ("GET", f"{SAMPLE_PING_URL}/fail")


def test_send_heartbeat_diagnostic_body():
    captured_body = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        captured_body.append(request.content.decode("utf-8"))
        return httpx.Response(200, text="OK")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    diagnostic = "Host memory 85%, disk C: 92% full."
    result = send_heartbeat(SAMPLE_PING_URL, client=client, diagnostic_body=diagnostic)

    assert result.success is True
    assert captured_body[0] == diagnostic


def test_send_heartbeat_diagnostic_body_truncation():
    captured_len = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_len.append(len(request.content))
        return httpx.Response(200, text="OK")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    huge_diagnostic = "A" * 20000
    send_heartbeat(SAMPLE_PING_URL, client=client, diagnostic_body=huge_diagnostic)

    # Healthchecks.io max body size is 10KB (10240 bytes)
    assert captured_len[0] == 10240


def test_send_heartbeat_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text=f"Not Found for {SAMPLE_UUID}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = send_heartbeat(SAMPLE_PING_URL, client=client)

    assert result.success is False
    assert result.status_code == 404
    assert result.error_category == "http_error"
    # Redaction verification: sample UUID must be redacted from error message
    assert SAMPLE_UUID not in result.error_message
    assert "[REDACTED_UUID]" in result.error_message or "[REDACTED_PING_UUID]" in result.error_message


def test_send_heartbeat_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Read timed out")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = send_heartbeat(SAMPLE_PING_URL, client=client, timeout=2.5)

    assert result.success is False
    assert result.error_category == "timeout"
    assert "timed out after 2.5s" in result.error_message


def test_send_heartbeat_tls_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise ssl.SSLError(f"CERTIFICATE_VERIFY_FAILED for {SAMPLE_UUID}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = send_heartbeat(SAMPLE_PING_URL, client=client)

    assert result.success is False
    assert result.error_category == "tls_error"
    assert SAMPLE_UUID not in result.error_message


def test_send_heartbeat_connect_dns_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"Failed to resolve hc-ping.com ({SAMPLE_UUID})")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = send_heartbeat(SAMPLE_PING_URL, client=client)

    assert result.success is False
    assert result.error_category == "dns_connect_error"
    assert SAMPLE_UUID not in result.error_message


# ==============================================================================
# 3. Service & Scheduled Task Management Tests
# ==============================================================================


def _fake_win_exec(cmd, *args, **kwargs):
    cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
    if "whoami" in cmd_str:
        return MagicMock(returncode=0, stdout='"user","S-1-5-21-123456789-123456789-123456789-1001"')
    if "icacls" in cmd_str:
        return MagicMock(returncode=0, stdout="Successfully processed 1 files.", stderr="")
    return MagicMock(returncode=0, stdout="", stderr="")


def test_task_status_not_found(tmp_path: Path):
    def fake_not_found(cmd, *args, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        if "schtasks" in cmd_str:
            return MagicMock(returncode=1, stdout="", stderr="ERROR: The system cannot find the file specified.")
        return _fake_win_exec(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=fake_not_found):
        status = get_heartbeat_task_status(config_path=tmp_path / "nonexistent.json")

    assert status["ok"] is True
    assert status["task_name"] == TASK_NAME
    assert status["task_installed"] is False
    assert status["task_state"] == "not_found"
    assert status["configured"] is False


def test_task_status_installed(tmp_path: Path):
    cfg_file = tmp_path / "healthchecks.json"
    save_healthchecks_config(HealthchecksConfig(ping_url=SAMPLE_PING_URL, interval_minutes=5), path=cfg_file)

    csv_output = (
        '"Folder","TaskName","Next Run Time","Status","Logon Mode","Last Run Time","Last Result","Author","Task To Run","Start In","Comment"\n'
        f'"\\","{TASK_NAME}","11/11/2026 12:05:00 PM","Ready","Interactive only","11/11/2026 12:00:00 PM","0","Host","python.exe","N/A","N/A"\n'
    )

    def fake_installed(cmd, *args, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        if "schtasks" in cmd_str:
            return MagicMock(returncode=0, stdout=csv_output, stderr="")
        return _fake_win_exec(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=fake_installed):
        status = get_heartbeat_task_status(config_path=cfg_file)

    assert status["ok"] is True
    assert status["task_installed"] is True
    assert status["task_state"] == "Ready"
    assert status["last_result"] == "0"
    assert status["configured"] is True
    assert SAMPLE_UUID not in status["ping_url_redacted"]


def test_task_status_headless_vs_interactive(tmp_path: Path):
    cfg_file = tmp_path / "healthchecks.json"
    save_healthchecks_config(HealthchecksConfig(ping_url=SAMPLE_PING_URL), path=cfg_file)

    # 1. SYSTEM / Headless task
    csv_headless = (
        '"Folder","TaskName","Next Run Time","Status","Logon Mode","Last Run Time","Last Result","Author","Task To Run","Start In","Comment","Scheduled Task State","Idle Time","Power Management","Run As User"\n'
        f'"\\","{TASK_NAME}","11/11/2026 12:05:00 PM","Ready","Service account","11/11/2026 12:00:00 PM","0","SYSTEM","python.exe","N/A","N/A","Ready","Disabled","Disabled","NT AUTHORITY\\SYSTEM"\n'
    )
    def fake_headless(cmd, *args, **kwargs):
        if "schtasks" in " ".join(str(c) for c in cmd):
            return MagicMock(returncode=0, stdout=csv_headless, stderr="")
        return _fake_win_exec(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=fake_headless):
        stat_h = get_heartbeat_task_status(config_path=cfg_file)
    assert stat_h["headless"] is True
    assert stat_h["logged_off_capable"] is True
    assert "headless" in stat_h["execution_mode"]

    # 2. Interactive-only task
    csv_interactive = (
        '"Folder","TaskName","Next Run Time","Status","Logon Mode","Last Run Time","Last Result","Author","Task To Run","Start In","Comment","Scheduled Task State","Idle Time","Power Management","Run As User"\n'
        f'"\\","{TASK_NAME}","11/11/2026 12:05:00 PM","Ready","Interactive only","11/11/2026 12:00:00 PM","0","User","python.exe","N/A","N/A","Ready","Disabled","Disabled","User"\n'
    )
    def fake_interactive(cmd, *args, **kwargs):
        if "schtasks" in " ".join(str(c) for c in cmd):
            return MagicMock(returncode=0, stdout=csv_interactive, stderr="")
        return _fake_win_exec(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=fake_interactive):
        stat_i = get_heartbeat_task_status(config_path=cfg_file)
    assert stat_i["headless"] is False
    assert stat_i["logged_off_capable"] is False
    assert "interactive_only" in stat_i["execution_mode"]


def test_install_heartbeat_task_headless_admin_enforcement():
    with patch("notifications.monitoring.service.is_running_as_admin", return_value=False):
        res = install_heartbeat_task(headless=True, apply=True)
    assert res["ok"] is False
    assert "Administrator" in res["error"]


def test_install_heartbeat_task_python_path_validation(tmp_path: Path):
    invalid_py = tmp_path / "nonexistent" / "python.exe"
    res = install_heartbeat_task(python_path=str(invalid_py), apply=False)
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_install_heartbeat_task_dry_run():
    preview = install_heartbeat_task(interval_minutes=10, apply=False)
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["task_name"] == TASK_NAME
    assert preview["interval_minutes"] == 10
    assert "Dry-run: pass -a/--apply" in preview["warning"]


def test_install_heartbeat_task_apply():
    captured_stdin = []

    def fake_subprocess_run(cmd, input=None, **kwargs):
        captured_stdin.append(input)
        return _fake_win_exec(cmd)

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        result = install_heartbeat_task(interval_minutes=7, apply=True, system_account=False)

    assert result["ok"] is True
    assert result["installed"] is True
    assert len(captured_stdin) == 1

    payload = json.loads(captured_stdin[0])
    assert payload["TaskName"] == TASK_NAME
    assert payload["IntervalMinutes"] == 7
    assert payload["SystemAccount"] is False
    assert "-m notifications.monitoring.runner" in payload["Arguments"]


def test_uninstall_heartbeat_task_dry_run_and_apply():
    # 1. Dry run
    preview = uninstall_heartbeat_task(apply=False)
    assert preview["ok"] is True
    assert preview["dry_run"] is True

    # 2. Apply
    def fake_del(cmd, *args, **kwargs):
        return MagicMock(returncode=0, stdout="SUCCESS", stderr="")

    with patch("subprocess.run", side_effect=fake_del):
        res = uninstall_heartbeat_task(apply=True)

    assert res["ok"] is True
    assert res["uninstalled"] is True


def test_doctor_diagnostics(tmp_path: Path):
    cfg_file = tmp_path / "healthchecks.json"
    save_healthchecks_config(HealthchecksConfig(ping_url=SAMPLE_PING_URL), path=cfg_file)

    def mock_schtasks(cmd, *args, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        if "schtasks" in cmd_str:
            csv_out = f'"Folder","TaskName","Next Run Time","Status"\n"\\","{TASK_NAME}","N/A","Ready"\n'
            return MagicMock(returncode=0, stdout=csv_out, stderr="")
        return _fake_win_exec(cmd, *args, **kwargs)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="OK")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with patch("subprocess.run", side_effect=mock_schtasks):
        diag = doctor(config_path=cfg_file, client=client)

    assert diag["ok"] is True
    assert diag["healthy"] is True
    check_names = [c["name"] for c in diag["checks"]]
    assert "configuration" in check_names
    assert "scheduled_task" in check_names
    assert "network_connectivity" in check_names


# ==============================================================================
# 4. Headless Runner Tests
# ==============================================================================


def test_runner_success(tmp_path: Path, monkeypatch):
    cfg_file = tmp_path / "healthchecks.json"
    save_healthchecks_config(HealthchecksConfig(ping_url=SAMPLE_PING_URL), path=cfg_file)

    with patch("notifications.monitoring.runner.send_heartbeat") as mock_send:
        mock_send.return_value = HeartbeatResult(success=True, status_code=200, duration_ms=45)
        monkeypatch.setattr(sys, "argv", ["runner", "-c", str(cfg_file)])
        code = runner_main()

    assert code == 0
    mock_send.assert_called_once()


def test_runner_missing_config(tmp_path: Path, monkeypatch):
    missing_file = tmp_path / "none.json"
    monkeypatch.setattr(sys, "argv", ["runner", "-c", str(missing_file)])
    code = runner_main()
    assert code == 1


def test_runner_heartbeat_failed(tmp_path: Path, monkeypatch):
    cfg_file = tmp_path / "healthchecks.json"
    save_healthchecks_config(HealthchecksConfig(ping_url=SAMPLE_PING_URL), path=cfg_file)

    with patch("notifications.monitoring.runner.send_heartbeat") as mock_send:
        mock_send.return_value = HeartbeatResult(
            success=False,
            status_code=500,
            duration_ms=80,
            error_category="http_error",
            error_message="Server error",
        )
        monkeypatch.setattr(sys, "argv", ["runner", "-c", str(cfg_file)])
        code = runner_main()

    assert code == 1


def test_runner_independence_n12_n13(tmp_path: Path):
    """Verify N12/N13: Heartbeat runner has zero dependencies on broker, storage, SQLite, or coordinator."""
    cfg_file = tmp_path / "healthchecks.json"
    save_healthchecks_config(HealthchecksConfig(ping_url=SAMPLE_PING_URL), path=cfg_file)

    # 1. Verify module import isolation in a fresh Python process
    cmd_imports = [
        sys.executable,
        "-c",
        (
            "import sys; "
            "import notifications.monitoring.runner; "
            "forbidden = ['notifications.broker', 'notifications.storage', 'notifications.lifecycle', 'sqlite3', 'resource_coordinator']; "
            "found = [m for m in forbidden if m in sys.modules]; "
            "sys.stderr.write(f'Forbidden modules imported: {found}\\n') if found else None; "
            "sys.exit(1 if found else 0)"
        ),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    proc_imp = subprocess.run(cmd_imports, capture_output=True, text=True, env=env)
    assert proc_imp.returncode == 0, f"Import isolation violated: {proc_imp.stderr}"

    # 2. Verify standalone execution in isolated environment without DB or broker
    isolated_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
        "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
        "NOTIFICATIONS_ALLOW_INSECURE_PING": "1",
    }
    # Mock server ping url using a dummy localhost or mock endpoint if needed,
    # or verify that runner fails with connection error (exit code 1) instead of crash/import error.
    dummy_cfg = tmp_path / "dummy_hc.json"
    dummy_cfg.write_text(json.dumps({"ping_url": "http://127.0.0.1:9/ping"}), encoding="utf-8")

    cmd_run = [
        sys.executable,
        "-m",
        "notifications.monitoring.runner",
        "-c",
        str(dummy_cfg),
        "-t",
        "1.0",
    ]
    proc_run = subprocess.run(cmd_run, capture_output=True, text=True, env=isolated_env)
    # Exits with 1 due to connection refused to dummy port 9, but runs cleanly without crashing on missing broker/db
    assert proc_run.returncode == 1
    assert "Heartbeat failed" in proc_run.stderr or "Connection" in proc_run.stderr


# ==============================================================================
# 5. CLI Integration Tests
# ==============================================================================


def test_cli_heartbeat_configure_dry_run(capsys):
    ret = main(["heartbeat", "configure", "-u", SAMPLE_PING_URL, "-i", "10", "-j"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["dry_run"] is True
    assert SAMPLE_UUID not in data["ping_url_redacted"]


def test_cli_heartbeat_configure_apply(tmp_path: Path, monkeypatch, capsys):
    secrets_file = tmp_path / "secrets" / "healthchecks.json"
    monkeypatch.setenv("NOTIFY_HEALTHCHECKS_SECRETS_FILE", str(secrets_file))

    ret = main(["heartbeat", "configure", "-u", SAMPLE_PING_URL, "-i", "5", "-a", "-j"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["status"] == "configured"
    assert secrets_file.is_file()


def test_cli_heartbeat_status(tmp_path: Path, monkeypatch, capsys):
    secrets_file = tmp_path / "secrets" / "healthchecks.json"
    monkeypatch.setenv("NOTIFY_HEALTHCHECKS_SECRETS_FILE", str(secrets_file))
    save_healthchecks_config(HealthchecksConfig(ping_url=SAMPLE_PING_URL), path=secrets_file)

    def fake_stat(cmd, *args, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        if "schtasks" in cmd_str:
            return MagicMock(returncode=1, stdout="", stderr="Not found")
        return _fake_win_exec(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=fake_stat):
        ret = main(["heartbeat", "status", "-j"])

    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["configured"] is True
    assert data["task_installed"] is False


def test_cli_heartbeat_test_dry_run(tmp_path: Path, monkeypatch, capsys):
    secrets_file = tmp_path / "secrets" / "healthchecks.json"
    monkeypatch.setenv("NOTIFY_HEALTHCHECKS_SECRETS_FILE", str(secrets_file))
    save_healthchecks_config(HealthchecksConfig(ping_url=SAMPLE_PING_URL), path=secrets_file)

    ret = main(["heartbeat", "test", "-j"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["dry_run"] is True
    assert "Dry-run: pass -a/--apply" in data["warning"]


def test_cli_heartbeat_test_apply(tmp_path: Path, monkeypatch, capsys):
    secrets_file = tmp_path / "secrets" / "healthchecks.json"
    monkeypatch.setenv("NOTIFY_HEALTHCHECKS_SECRETS_FILE", str(secrets_file))
    save_healthchecks_config(HealthchecksConfig(ping_url=SAMPLE_PING_URL), path=secrets_file)

    with patch("notifications.monitoring.heartbeat.send_heartbeat") as mock_send:
        mock_send.return_value = HeartbeatResult(success=True, status_code=200, duration_ms=50)
        ret = main(["heartbeat", "test", "-a", "-j"])

    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["status"] == "ping_accepted"


def test_cli_heartbeat_ping_headless(tmp_path: Path, monkeypatch, capsys):
    secrets_file = tmp_path / "secrets" / "healthchecks.json"
    monkeypatch.setenv("NOTIFY_HEALTHCHECKS_SECRETS_FILE", str(secrets_file))
    save_healthchecks_config(HealthchecksConfig(ping_url=SAMPLE_PING_URL), path=secrets_file)

    with patch("notifications.monitoring.heartbeat.send_heartbeat") as mock_send:
        mock_send.return_value = HeartbeatResult(success=True, status_code=200, duration_ms=30)
        ret = main(["heartbeat", "ping", "-v"])

    assert ret == 0
    captured = capsys.readouterr()
    assert "Heartbeat confirmed" in captured.out


def test_cli_heartbeat_install_dry_run_and_apply(capsys):
    # Dry run
    ret = main(["heartbeat", "install", "-i", "10", "-j"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["dry_run"] is True

    # Apply
    with patch("subprocess.run", side_effect=_fake_win_exec):
        ret = main(["heartbeat", "install", "-i", "10", "-a", "-j"])

    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["installed"] is True


def test_cli_heartbeat_doctor(tmp_path: Path, monkeypatch, capsys):
    secrets_file = tmp_path / "secrets" / "healthchecks.json"
    monkeypatch.setenv("NOTIFY_HEALTHCHECKS_SECRETS_FILE", str(secrets_file))
    save_healthchecks_config(HealthchecksConfig(ping_url=SAMPLE_PING_URL), path=secrets_file)

    with patch("notifications.monitoring.service.get_heartbeat_task_status") as mock_status, \
         patch("httpx.Client.get") as mock_get:
        mock_status.return_value = {"task_installed": True, "task_state": "Ready", "last_result": "0"}
        mock_get.return_value = MagicMock(status_code=200)

        ret = main(["heartbeat", "doctor", "-j"])

    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["healthy"] is True
