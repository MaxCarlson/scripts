"""Regression tests for CLI/backend JSON error contracts and full registration audit."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from vm_lab import cli
from vm_lab.backend import BackendAdapter
from vm_lab.exceptions import EXIT_ERROR, EXIT_SUCCESS, BackendExecutionError

VM_LAB_ROOT = Path(__file__).resolve().parent.parent


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["pwsh"], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# Section 4: JSON error-handling & normalization contract (10 scenarios)
# ---------------------------------------------------------------------------


def test_stderr_structured_json_error_emits_single_json_on_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """1. Structured error JSON on stderr only: single JSON on stdout, no duplicate on stderr, nonzero exit."""
    err_json = '{"status":"error","operation":"list","error":"You do not have the required permission."}\n'
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=_completed(stdout="", stderr=err_json, returncode=1)):
        rc = cli.main(["list", "-j"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == EXIT_ERROR
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["status"] == "error"
    assert payload["operation"] == "list"
    assert "permission" in payload["error"]


def test_stdout_structured_success_json(capsys: pytest.CaptureFixture[str]) -> None:
    """2. Structured success JSON on stdout."""
    ok_json = '{"status":"OK","operation":"host-resources","logical_cpu_count":8}\n'
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=_completed(stdout=ok_json, stderr="", returncode=0)):
        rc = cli.main(["host", "resources", "-j"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["status"] == "OK"
    assert payload["logical_cpu_count"] == 8


def test_stdout_structured_failure_json(capsys: pytest.CaptureFixture[str]) -> None:
    """3. Structured failure JSON on stdout."""
    fail_json = '{"status":"FAILED","reason_code":"guest_command_nonzero_exit","error":"exit 2"}\n'
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=_completed(stdout=fail_json, stderr="", returncode=0)):
        rc = cli.main(["list", "-j"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == EXIT_ERROR
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["status"] == "FAILED"


def test_malformed_json_on_stderr_emits_structured_error(capsys: pytest.CaptureFixture[str]) -> None:
    """4. Malformed JSON on stderr."""
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=_completed(stdout="", stderr='{"status": "error"', returncode=1)):
        rc = cli.main(["list", "-j"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == EXIT_ERROR
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["status"] == "ERROR"
    assert payload["reason_code"] == "malformed_backend_json"
    assert '{"status": "error"' in payload["error"]


def test_non_json_powershell_error_emits_structured_error(capsys: pytest.CaptureFixture[str]) -> None:
    """5. Non-JSON PowerShell errors (including missing function & permission denial)."""
    ps_err = "Get-VmLabHostResources: The term 'Get-VmLabHostResources' is not recognized as a name of a cmdlet."
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=_completed(stdout="", stderr=ps_err, returncode=1)):
        rc = cli.main(["host", "resources", "-j"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == EXIT_ERROR
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["status"] == "ERROR"
    assert payload["reason_code"] == "missing_backend_function"
    assert "Get-VmLabHostResources" in payload["error"]


def test_empty_backend_output_with_nonzero_exit(capsys: pytest.CaptureFixture[str]) -> None:
    """6. Empty backend output with nonzero exit."""
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=_completed(stdout="", stderr="", returncode=2)):
        rc = cli.main(["list", "-j"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == EXIT_ERROR
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["status"] == "ERROR"
    assert payload["reason_code"] == "empty_backend_output"


def test_interactive_credential_operation_with_structured_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """7. Interactive credential operation with structured failure."""
    fail_json = '{"status":"AWAITING_INTERACTION","reason_code":"guest_credentials_required","vm_name":"Lab-01"}\n'
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=_completed(stdout=fail_json, stderr="", returncode=0)):
        rc = cli.main(["guest", "status", "Lab-01", "--prompt-credential", "-j"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc != 0
    payload = json.loads(captured.out)
    assert payload["status"] == "AWAITING_INTERACTION"


def test_human_readable_mode_no_duplicate_error(capsys: pytest.CaptureFixture[str]) -> None:
    """8. Human-readable mode renders one clear error message with nonzero exit and no duplicate."""
    err_json = '{"status":"error","operation":"list","error":"Permission denied."}\n'
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=_completed(stdout="", stderr=err_json, returncode=1)):
        rc = cli.main(["list"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == EXIT_ERROR
    assert captured.err == ""
    assert captured.out.count("Permission denied.") == 1
    assert "status: error" in captured.out


def test_json_mode_stdout_malformed_json_raises_and_emits_single_json(capsys: pytest.CaptureFixture[str]) -> None:
    """9. JSON mode handles malformed stdout JSON with a single valid JSON error document."""
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=_completed(stdout="{not-json", stderr="", returncode=1)):
        rc = cli.main(["list", "-j"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == EXIT_ERROR
    payload = json.loads(captured.out)
    assert payload["status"] == "ERROR"
    assert payload["reason_code"] == "backend_execution_error"


def test_secret_redaction_in_stderr_and_payload(capsys: pytest.CaptureFixture[str]) -> None:
    """10. Secret redaction across stderr, structured JSON error, and exceptions."""
    err_json = '{"status":"error","error":"auth failed with password=SuperSecret123 token=Tok999"}\n'
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=_completed(stdout="", stderr=err_json, returncode=1)):
        rc = cli.main(["list", "-j"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == EXIT_ERROR
    assert "SuperSecret123" not in captured.out
    assert "Tok999" not in captured.out
    payload = json.loads(captured.out)
    assert "password=[REDACTED]" in payload["error"]
    assert "token=[REDACTED]" in payload["error"]

    with patch(
        "vm_lab.backend.subprocess.run",
        return_value=_completed(stdout="{bad", stderr="secret=TopSecret456", returncode=1),
    ):
        with pytest.raises(BackendExecutionError) as exc_info:
            adapter.invoke(["-o", "list", "-Json"], json_mode=True)
    assert "TopSecret456" not in str(exc_info.value)
    assert "secret=[REDACTED]" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Section 5: Deterministic CLI/backend registration audit (AST + real import)
# ---------------------------------------------------------------------------


def _collect_leaf_builders(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], argparse.ArgumentParser]]:
    leaves: list[tuple[tuple[str, ...], argparse.ArgumentParser]] = []
    sub_actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not sub_actions:
        return [(prefix, parser)]
    for sub in sub_actions:
        for name, subparser in sub.choices.items():
            # Skip aliases pointing to the same parser object if already visited by canonical name
            leaves.extend(_collect_leaf_builders(subparser, (*prefix, name)))
    return leaves


def _synthetic_namespace(parser: argparse.ArgumentParser, path: tuple[str, ...]) -> argparse.Namespace:
    ns = argparse.Namespace()
    for action in parser._actions:
        if action.dest in {"help", "command"} or action.dest.endswith("_cmd"):
            continue
        if isinstance(action, argparse._StoreTrueAction):
            setattr(ns, action.dest, False)
        elif action.default is not argparse.SUPPRESS and action.default is not None:
            setattr(ns, action.dest, action.default)
        elif action.choices:
            setattr(ns, action.dest, list(action.choices)[0])
        elif action.type is int:
            setattr(ns, action.dest, 1024)
        elif action.nargs in {"+", "*"} or isinstance(action, argparse._AppendAction):
            setattr(ns, action.dest, ["dummy"])
        else:
            setattr(ns, action.dest, "dummy")
    # Satisfy conditional required combinations in commands.py
    if path == ("artifact", "plan") or path == ("artifact", "deploy"):
        ns.manifest = "manifest.json"
        ns.destination = "C:\\Temp"
    if path == ("guest", "run"):
        ns.script = "script.ps1"
        ns.executable = None
    if path == ("guest", "exec"):
        ns.executable = "C:\\Windows\\System32\\whoami.exe"
        ns.script = None
    if path == ("checkpoint", "inspect"):
        ns.checkpoint = "cp-1"
    if path == ("setup", "guide"):
        ns.action = "guide"
    return ns


def test_cli_backend_registration_audit_via_powershell_ast_and_module_import() -> None:
    """Audit all Python CLI builders against PowerShell AST, ValidateSet, switch branches, and real Import-Module."""
    audit_ps = f"""
$ErrorActionPreference = 'Stop'
$root = '{VM_LAB_ROOT}'
$tokens = $null; $errs = $null

$invAst = [System.Management.Automation.Language.Parser]::ParseFile("$root\\Invoke-VmLab.ps1", [ref]$tokens, [ref]$errs)
$appAst = [System.Management.Automation.Language.Parser]::ParseFile("$root\\Invoke-VmLabApprovedPlan.ps1", [ref]$tokens, [ref]$errs)
$outAst = [System.Management.Automation.Language.Parser]::ParseFile("$root\\src\\Output.ps1", [ref]$tokens, [ref]$errs)

$invParams = @($invAst.ParamBlock.Parameters | ForEach-Object {{ $_.Name.VariablePath.UserPath }})
$appParams = @($appAst.ParamBlock.Parameters | ForEach-Object {{ $_.Name.VariablePath.UserPath }})

$opParam = $invAst.ParamBlock.Parameters | Where-Object {{ $_.Name.VariablePath.UserPath -eq 'Operation' }}
$valSetAttr = $opParam.Attributes | Where-Object {{ $_.TypeName.Name -eq 'ValidateSet' }}
$invOps = @($valSetAttr.PositionalArguments | ForEach-Object {{ $_.Value }})

$outSwitch = $outAst.Find({{ param($n) $n -is [System.Management.Automation.Language.SwitchStatementAst] }}, $true)
$switchOps = @()
foreach ($cl in $outSwitch.Clauses) {{
    $vals = $cl.Item1.FindAll({{ param($n) $n -is [System.Management.Automation.Language.StringConstantExpressionAst] }}, $true)
    foreach ($v in $vals) {{ $switchOps += $v.Value }}
}}

$calledFuncs = @($outAst.FindAll({{ param($n) $n -is [System.Management.Automation.Language.CommandAst] }}, $true) |
    ForEach-Object {{ $_.GetCommandName() }} |
    Where-Object {{ $_ -and $_ -like '*-VmLab*' }} |
    Sort-Object -Unique)

$definedFuncs = @()
foreach ($f in Get-ChildItem "$root\\src\\*.ps1") {{
    $fAst = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errs)
    $definedFuncs += @($fAst.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }}, $true) |
        ForEach-Object {{ $_.Name }})
}}

Import-Module "$root\\vm_lab.psd1" -Force
$mod = Get-Module vm_lab
$exported = @($mod.ExportedFunctions.Keys | Sort-Object -Unique)
$missingInModuleScope = @()
foreach ($fn in $calledFuncs) {{
    $exists = & $mod {{ param($name) $null -ne (Get-Command -Name $name -ErrorAction SilentlyContinue) }} $fn
    if (-not $exists) {{ $missingInModuleScope += $fn }}
}}

[pscustomobject]@{{
    invoke_ops = $invOps
    output_switch_ops = $switchOps | Sort-Object -Unique
    invoke_params = $invParams
    approved_params = $appParams
    called_funcs = $calledFuncs
    defined_funcs = $definedFuncs | Sort-Object -Unique
    exported_funcs = $exported
    missing_in_module_scope = $missingInModuleScope
}} | ConvertTo-Json -Depth 5
"""
    proc = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", audit_ps],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, f"PowerShell AST audit failed: {proc.stderr}"
    meta = json.loads(proc.stdout)

    # 1. Every function called in Output.ps1 must exist in src/*.ps1 and be callable in vm_lab module scope
    missing_src = sorted(set(meta["called_funcs"]) - set(meta["defined_funcs"]))
    assert not missing_src, f"Functions called in Output.ps1 but missing in src/*.ps1: {missing_src}"
    assert not meta["missing_in_module_scope"], (
        f"Functions called in Output.ps1 not loaded after Import-Module: {meta['missing_in_module_scope']}"
    )
    assert "Get-VmLabHostResources" in meta["exported_funcs"]

    # 2. Every leaf Python CLI command must map to a valid PowerShell operation and valid parameters
    parser = cli.build_parser()
    leaves = _collect_leaf_builders(parser)
    assert len(leaves) >= 30

    inv_ops = set(meta["invoke_ops"])
    switch_ops = set(meta["output_switch_ops"])
    inv_params = {p.lower() for p in meta["invoke_params"]}
    app_params = {p.lower() for p in meta["approved_params"]}

    for path, leaf_parser in leaves:
        if path == ("version",):
            continue
        builder = leaf_parser.get_default("_builder")
        assert builder is not None, f"Leaf command {path} has no _builder"
        script_name = leaf_parser.get_default("_script_name") or "Invoke-VmLab.ps1"
        ns = _synthetic_namespace(leaf_parser, path)
        ps_args, _ = builder(ns)

        if script_name == "Invoke-VmLabApprovedPlan.ps1":
            valid_params = app_params
        else:
            assert ps_args[0] == "-o", f"Command {path} did not start with -o: {ps_args}"
            op = ps_args[1]
            assert op in inv_ops, f"Command {path} operation '{op}' not in Invoke-VmLab.ps1 ValidateSet"
            assert op in switch_ops, f"Command {path} operation '{op}' not in Output.ps1 switch"
            valid_params = inv_params

        for token in ps_args:
            if token.startswith("-") and token not in {"-o", "-j"}:
                param_name = token[1:].split(":")[0].lower()
                assert param_name in valid_params, (
                    f"Command {path} emitted unknown PowerShell parameter '{token}' for {script_name}"
                )


# ---------------------------------------------------------------------------
# Wizard interactive completion contract
# ---------------------------------------------------------------------------


def test_wizard_interactive_success_empty_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """1. Successful interactive wizard with empty captured stdout exits 0 without UnboundLocalError."""
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=subprocess.CompletedProcess(args=["pwsh"], returncode=0)):
        rc = cli.main(["wizard"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS
    assert captured.out == ""
    assert captured.err == ""


def test_wizard_interactive_failure_empty_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """2. Failed interactive wizard with empty captured stdout returns nonzero exit."""
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=subprocess.CompletedProcess(args=["pwsh"], returncode=1)):
        rc = cli.main(["wizard"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert captured.err == ""


def test_wizard_interactive_cancelled_nonzero_exit(capsys: pytest.CaptureFixture[str]) -> None:
    """3. Cancelled interactive wizard (e.g., Ctrl+C / exit 130) preserves nonzero exit code."""
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch("vm_lab.backend.subprocess.run", return_value=subprocess.CompletedProcess(args=["pwsh"], returncode=130)):
        rc = cli.main(["wizard"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == 130
    assert captured.out == ""


def test_wizard_interactive_stdout_no_json_fallback(capsys: pytest.CaptureFixture[str]) -> None:
    """4. Interactive wizard writes non-empty stdout once and never emits JSON fallback."""
    mock_be = SimpleNamespace(
        invoke=lambda *a, **kw: SimpleNamespace(
            stdout="Wizard completed.",
            stderr="",
            data={"unexpected": True},
            exit_code=0,
        )
    )
    rc = cli.main(["wizard"], adapter=mock_be)  # type: ignore[arg-type]

    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS
    assert captured.out == "Wizard completed.\n"
    assert "unexpected" not in captured.out
    assert captured.err == ""


def test_noninteractive_json_operation_still_works_alongside_wizard_fix(capsys: pytest.CaptureFixture[str]) -> None:
    """5. Existing noninteractive CLI operations and JSON output remain intact."""
    adapter = BackendAdapter(backend_root=VM_LAB_ROOT, pwsh_exe="pwsh")
    with patch(
        "vm_lab.backend.subprocess.run",
        return_value=_completed(stdout='{"status":"PLANNED","operation":"plan"}\n', stderr="", returncode=0),
    ):
        rc = cli.main(["plan", "Test-VM", "-t", "windows11-dev", "-r", "C:\\VMs\\Test-VM", "-j"], adapter=adapter)

    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS
    payload = json.loads(captured.out)
    assert payload["status"] == "PLANNED"
