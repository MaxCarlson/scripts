"""Diagnostic argv-echo and cross-platform argument fidelity test suite."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

TEST_ARGV_CASES = [
    ["hello", "world"],
    ["with spaces", "second arg", "multiple   spaces   inside"],
    ["", "empty_first"],
    ["empty_middle", "", "tail"],
    ["empty_last", ""],
    ["", "", ""],
    ['quotes "inside" arg', "single 'inside' arg"],
    ['"double quotes around"'],
    ["metachars: & | < > ^ % ! ( )"],
    ["&", "|", "<", ">", "^", "%", "!", "(", ")"],
    ["unicode: 日本語 🚀 ñ ü"],
    ["C:\\Program Files\\Toolkit\\", "\\\\server\\share\\path\\to\\dir"],
    ["--flag=value", "--other", "val"],
    ["--", "positional_after_dash_dash"],
    ["-v", "-f", "--flag-with-value=123", "--", "--another-flag"],
]


@pytest.fixture
def echo_manifest(tmp_path):
    target_py = Path(__file__).parent / "argv_echo_target.py"
    manifest_file = tmp_path / "manifest.json"
    manifest_data = {
        "schema_version": 1,
        "commands": {
            "echo": {
                "program_id": "pyscript:argv_echo_target.py",
                "kind": "python_file",
                "target": str(target_py),
            }
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")
    return manifest_file


@pytest.mark.parametrize("args", TEST_ARGV_CASES)
def test_direct_launcher_argv_fidelity(tmp_path, monkeypatch, echo_manifest, args):
    db_path = tmp_path / "invocations.sqlite3"
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(db_path))

    cmd = [
        sys.executable,
        "-m",
        "script_logging.launcher",
        "--manifest",
        str(echo_manifest),
        "--command",
        "echo",
        "--",
        *args,
    ]
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    received = json.loads(res.stdout)
    assert received == args


@pytest.mark.parametrize("exit_val", [0, 1, 42, 127])
def test_launcher_child_exit_code_propagation(tmp_path, exit_val):
    exit_target = tmp_path / "exit_target.py"
    exit_target.write_text(f"import sys\nsys.exit({exit_val})\n", encoding="utf-8")

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "commands": {
                    "exiter": {
                        "program_id": "pyscript:exit_target.py",
                        "kind": "python_file",
                        "target": str(exit_target),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        "-m",
        "script_logging.launcher",
        "--manifest",
        str(manifest_file),
        "--command",
        "exiter",
    ]
    res = subprocess.run(cmd)
    assert res.returncode == exit_val


def test_launcher_stdio_piping_and_streaming(tmp_path):
    stdio_target = tmp_path / "stdio_target.py"
    stdio_target.write_text(
        """import sys
stdin_content = sys.stdin.read()
sys.stdout.write(f"STDOUT_ECHO:{stdin_content}")
sys.stderr.write(f"STDERR_ECHO:{stdin_content}")
sys.exit(0)
""",
        encoding="utf-8",
    )

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "commands": {
                    "stdio": {
                        "program_id": "pyscript:stdio_target.py",
                        "kind": "python_file",
                        "target": str(stdio_target),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        "-m",
        "script_logging.launcher",
        "--manifest",
        str(manifest_file),
        "--command",
        "stdio",
    ]
    test_input = "Sample Stdin Payload with Unicode 🚀 and\nnewlines\n"
    res = subprocess.run(
        cmd,
        input=test_input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert res.stdout == f"STDOUT_ECHO:{test_input}"
    assert res.stderr == f"STDERR_ECHO:{test_input}"


@pytest.mark.skipif(os.name != "nt", reason="Windows batch wrapper tests require Windows")
class TestWindowsWrapperFidelity:
    @pytest.fixture
    def cmd_wrapper(self, tmp_path, echo_manifest):
        wrapper_path = tmp_path / "echo_cmd.cmd"
        # Standard .cmd wrapper matching Stage 4 template pattern
        wrapper_content = (
            "@echo off\n"
            f'"{sys.executable}" -m script_logging.launcher --manifest "{echo_manifest}" --command echo --wrapper "%~f0" -- %*\n'
            "exit /b %ERRORLEVEL%\n"
        )
        wrapper_path.write_text(wrapper_content, encoding="utf-8")
        return wrapper_path

    def test_cmd_exe_standard_arguments(self, cmd_wrapper):
        cmd = [
            "cmd.exe",
            "/c",
            "call",
            str(cmd_wrapper),
            "hello world",
            "second_arg",
            "third with spaces",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        received = json.loads(res.stdout)
        assert received == ["hello world", "second_arg", "third with spaces"]

    def test_cmd_exe_empty_and_quoted_arguments(self, cmd_wrapper):
        # Empty string arguments in CMD
        cmd = [
            "cmd.exe",
            "/c",
            "call",
            str(cmd_wrapper),
            "",
            "middle",
            "",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        received = json.loads(res.stdout)
        assert received == ["", "middle", ""]

    def test_cmd_exe_unicode_and_paths(self, cmd_wrapper):
        cmd = [
            "cmd.exe",
            "/c",
            "call",
            str(cmd_wrapper),
            "unicode: 日本語 🚀",
            "C:\\Program Files\\Toolkit\\",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        received = json.loads(res.stdout)
        assert received == ["unicode: 日本語 🚀", "C:\\Program Files\\Toolkit\\"]

    def test_cmd_exe_flags_and_dashes(self, cmd_wrapper):
        cmd = [
            "cmd.exe",
            "/c",
            "call",
            str(cmd_wrapper),
            "--flag=val",
            "-v",
            "--",
            "positional_after",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        received = json.loads(res.stdout)
        assert received == ["--flag=val", "-v", "--", "positional_after"]

    def test_pwsh_standard_arguments(self, cmd_wrapper):
        # Test invocation from PowerShell 7 / pwsh
        ps_cmd = f'& "{cmd_wrapper}" "hello world" "arg2" "with spaces"'
        cmd = ["pwsh", "-NoProfile", "-Command", ps_cmd]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        received = json.loads(res.stdout)
        assert received == ["hello world", "arg2", "with spaces"]

    def test_pwsh_unicode_and_flags(self, cmd_wrapper):
        ps_cmd = f'& "{cmd_wrapper}" --flag="val" "unicode 日本語 🚀"'
        cmd = ["pwsh", "-NoProfile", "-Command", ps_cmd]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        received = json.loads(res.stdout)
        assert received == ["--flag=val", "unicode 日本語 🚀"]

    def test_pwsh_empty_arguments_with_standard_or_escaped_quotes(self, cmd_wrapper):
        # In PowerShell, empty arguments passed to batch files require standard native arg passing
        # or explicit escaped double quotes '""'.
        ps_cmd = f'$PSNativeCommandArgumentPassing = "Standard"; & "{cmd_wrapper}" "" "middle" ""'
        cmd = ["pwsh", "-NoProfile", "-Command", ps_cmd]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        received = json.loads(res.stdout)
        assert received == ["", "middle", ""]

        # Escaped quotes pattern
        ps_cmd_escaped = f'& "{cmd_wrapper}" \'""\' "middle" \'""\''
        cmd_escaped = ["pwsh", "-NoProfile", "-Command", ps_cmd_escaped]
        res_escaped = subprocess.run(
            cmd_escaped, capture_output=True, text=True, encoding="utf-8", check=True
        )
        received_escaped = json.loads(res_escaped.stdout)
        assert received_escaped == ["", "middle", ""]

    def test_pwsh_quotes_inside_arguments(self, cmd_wrapper):
        # In PowerShell invoking .cmd batch files, embedded double quotes must be escaped with \"
        # so the batch parser does not strip them during %* expansion.
        ps_cmd = f'& "{cmd_wrapper}" \'quotes \\"inside\\" arg\' "plain"'
        cmd = ["pwsh", "-NoProfile", "-Command", ps_cmd]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        received = json.loads(res.stdout)
        assert received == ['quotes "inside" arg', "plain"]

    def test_cmd_wrapper_exit_code_propagation(self, tmp_path, echo_manifest):
        exit_target = tmp_path / "exit42.py"
        exit_target.write_text("import sys\nsys.exit(42)\n", encoding="utf-8")

        manifest_file = tmp_path / "manifest_exit.json"
        manifest_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "commands": {
                        "exit42": {
                            "program_id": "pyscript:exit42.py",
                            "kind": "python_file",
                            "target": str(exit_target),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        wrapper_path = tmp_path / "exit42.cmd"
        wrapper_content = (
            "@echo off\n"
            f'"{sys.executable}" -m script_logging.launcher --manifest "{manifest_file}" --command exit42 --wrapper "%~f0" -- %*\n'
            "exit /b %ERRORLEVEL%\n"
        )
        wrapper_path.write_text(wrapper_content, encoding="utf-8")

        res = subprocess.run(["cmd.exe", "/c", "call", str(wrapper_path)])
        assert res.returncode == 42

    def test_direct_cmd_file_invocation(self, cmd_wrapper):
        res = subprocess.run(
            [str(cmd_wrapper), "direct1", "direct with space", ""],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        received = json.loads(res.stdout)
        assert received == ["direct1", "direct with space", ""]
