import pytest

from system_manager.cli import main


def _invoke(capsys, argv):
    try:
        result = main(argv)
    except SystemExit as exc:
        result = exc.code
    captured = capsys.readouterr()
    return result, captured.out, captured.err


def test_no_args_prints_top_level_help(capsys):
    result, stdout, stderr = _invoke(capsys, [])

    assert result == 0
    assert stderr == ""
    assert "usage: sm" in stdout
    assert "Cross-platform System Manager CLI" in stdout


@pytest.mark.parametrize(
    "category",
    [
        "id",
        "net",
        "proc",
        "sys",
        "env",
        "pkg",
        "disk",
        "service",
        "docker",
        "git",
        "text",
        "crypto",
        "file",
        "perm",
    ],
)
def test_category_without_subcommand_prints_category_help(capsys, category):
    result, stdout, stderr = _invoke(capsys, [category])

    assert result == 0
    assert stderr == ""
    assert f"usage: sm {category}" in stdout
    assert "-h, --help" in stdout


def test_category_help_matches_explicit_help(capsys):
    result, stdout, stderr = _invoke(capsys, ["id"])
    explicit_result, explicit_stdout, explicit_stderr = _invoke(capsys, ["id", "--help"])

    assert result == explicit_result == 0
    assert stderr == explicit_stderr == ""
    assert stdout == explicit_stdout


def test_unique_nested_command_without_args_prints_command_help(capsys):
    result, stdout, stderr = _invoke(capsys, ["sid"])

    assert result == 0
    assert stderr == ""
    assert "usage: sm id sid" in stdout
    assert "-h, --help" in stdout


def test_cli_help_and_ui_fallback_without_termdash(monkeypatch, capsys):
    import subprocess
    import sys

    code = (
        "import sys; "
        "sys.modules['termdash'] = None; "
        "sys.modules['termdash.interactive_list'] = None; "
        "from system_manager.cli import main; "
        "main(['--help'])"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "System Manager CLI" in proc.stdout

    from system_manager import ui

    monkeypatch.setattr(ui, "InteractiveList", None)
    ui.show_list([{"pid": 123, "name": "demo"}], title="Demo")
    table_out = capsys.readouterr().out
    assert "Demo" in table_out
    assert "123" in table_out
    assert "demo" in table_out
