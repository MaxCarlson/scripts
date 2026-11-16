"""H4.9 Python 3.12+ compatibility and trusted-bootstrap regression tests."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from tools.h4_qualification import bundle_builder, python_compat, source_integrity, windows_acceptance

MODULE_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = MODULE_ROOT / "tools" / "h4_qualification"
BOOTSTRAP_PS1 = TOOLS_DIR / "Bootstrap-H4GuestBundle.ps1"
PWSH = shutil.which("pwsh")


def _build_bundle(tmp_path: Path, name: str = "bundle_out") -> tuple[Path, Path, str]:
    out = tmp_path / name
    res = bundle_builder.build_bundle(
        repo_root=MODULE_ROOT.parents[1],
        output_dir=out,
        new_ref="HEAD",
        apply=True,
    )
    return out, Path(res["archive_path"]), res["archive_sha256"]


def test_rc_package_keeps_python_310_contract_while_h4_tools_require_312():
    pyproject = tomllib.loads((MODULE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["requires-python"] == ">=3.10"
    assert python_compat.RC_PACKAGE_PYTHON_REQUIRES == ">=3.10"
    assert python_compat.H4_TOOLING_PYTHON_REQUIRES == ">=3.12"
    assert python_compat.require_supported_python("bundle_builder", version_info=(3, 12, 10)) == "3.12.10"
    assert python_compat.require_supported_python("windows_acceptance", version_info=(3, 13, 0)) == "3.13.0"


@pytest.mark.parametrize("bad_version", [(3, 9, 18), (3, 10, 11), (3, 11, 9)])
def test_unsupported_python_versions_rejected_with_actionable_error(bad_version):
    with pytest.raises(python_compat.PythonCompatibilityError) as exc:
        python_compat.require_supported_python("windows_acceptance", version_info=bad_version)
    msg = str(exc.value)
    assert exc.value.code == "unsupported_python_version"
    assert "3.12+" in msg
    assert ">=3.10" in msg


def test_entrypoints_reject_unsupported_python_before_side_effects(tmp_path, capsys):
    out_dir = tmp_path / "never_created_bundle"
    assert bundle_builder.main(["-o", str(out_dir), "-a", "-j"], python_version_info=(3, 10, 11)) == 2
    err = capsys.readouterr().err
    payload = json.loads(err)
    assert payload["reason_code"] == "unsupported_python_version"
    assert "3.12+" in payload["error"]
    assert not out_dir.exists()

    run_root = tmp_path / "h4-rc-untouched"
    run_root.mkdir()
    assert windows_acceptance.main(
        ["-r", str(run_root), "-p", "offline", "-a", "-j"],
        is_windows=True,
        python_version_info=(3, 11, 8),
    ) == 2
    err2 = capsys.readouterr().err
    payload2 = json.loads(err2)
    assert payload2["reason_code"] == "unsupported_python_version"
    assert not list(run_root.iterdir())


@pytest.mark.parametrize("script_name", [
    "source_integrity.py",
    "bundle_builder.py",
    "windows_acceptance.py",
])
def test_subprocess_cli_fails_before_tomllib_import_under_simulated_py310(tmp_path, script_name):
    script_path = TOOLS_DIR / script_name
    probe = (
        "import sys, runpy; "
        "target = sys.argv[1]; "
        "sys.modules['tomllib'] = None; "
        "sys.version_info = (3, 10, 11, 'final', 0); "
        "sys.argv = [target, '-j']; "
        "runpy.run_path(target, run_name='__main__')"
    )
    proc = subprocess.run(
        [sys.executable, "-B", "-c", probe, str(script_path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 2
    assert "ModuleNotFoundError" not in proc.stderr
    payload = json.loads(proc.stderr.strip())
    assert payload["reason_code"] == "unsupported_python_version"
    assert "3.12+" in payload["error"]


def test_bundle_metadata_distinguishes_rc_and_h4_python_contracts_and_dependencies(tmp_path):
    out_dir, _, expected_sha = _build_bundle(tmp_path)
    bundle_root = out_dir / "h4-windows-acceptance"
    manifest = json.loads((bundle_root / "manifest.json").read_text(encoding="utf-8"))
    lock = json.loads((bundle_root / "dependencies" / "dependency-lock.json").read_text(encoding="utf-8"))
    readme = (bundle_root / "README.md").read_text(encoding="utf-8")

    assert manifest["rc_package_python_requires"] == ">=3.10"
    assert manifest["tool_python_requires"] == ">=3.12"
    assert lock["python_requires"] == ">=3.10"
    assert lock["rc_package_python_requires"] == ">=3.10"
    assert lock["h4_tooling_python_requires"] == ">=3.12"
    assert lock["dependency_status"] == "resolved_not_hashed"
    assert lock["wheelhouse_status"] == "unavailable"
    assert (bundle_root / "harness" / "python_compat.py").is_file()
    assert "unauthenticated `.sha256`" in readme

    verified = source_integrity.verify_extracted_bundle(bundle_root)
    assert verified["verified"] is True
    assert expected_sha == (out_dir / f"{bundle_builder.ARCHIVE_FILENAME}.sha256").read_text(encoding="utf-8").split()[0]


@pytest.mark.skipif(not PWSH, reason="pwsh required for PowerShell bootstrap tests")
def test_trusted_bootstrap_rejects_bad_digest_bad_python_and_cleans_partial_extract(tmp_path):
    _, zip_path, expected_sha = _build_bundle(tmp_path, "src_bundle")

    # 1. Mismatched digest aborts BEFORE creating DestinationRoot
    bad_dest = tmp_path / "dest_bad_digest"
    proc_bad = subprocess.run(
        [
            PWSH, "-NoProfile", "-NonInteractive", "-File", str(BOOTSTRAP_PS1),
            "-ArchivePath", str(zip_path),
            "-ExpectedSha256", "0" * 64,
            "-DestinationRoot", str(bad_dest),
            "-Python", sys.executable,
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc_bad.returncode != 0
    assert not bad_dest.exists()

    # 2. Unsupported Python shim fails BEFORE extraction
    fake_py = tmp_path / "python310.cmd"
    fake_py.write_text("@echo 3.10.11\r\n@exit /b 2\r\n", encoding="utf-8")
    py_dest = tmp_path / "dest_bad_py"
    proc_py = subprocess.run(
        [
            PWSH, "-NoProfile", "-NonInteractive", "-File", str(BOOTSTRAP_PS1),
            "-ArchivePath", str(zip_path),
            "-ExpectedSha256", expected_sha,
            "-DestinationRoot", str(py_dest),
            "-Python", str(fake_py),
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc_py.returncode == 2
    assert "3.12+" in (proc_py.stdout + proc_py.stderr)
    assert not py_dest.exists()

    # 3. Valid extraction succeeds andVerify-H4GuestBundle catches tampered extracted component
    ok_dest = tmp_path / "dest_ok"
    proc_ok = subprocess.run(
        [
            PWSH, "-NoProfile", "-NonInteractive", "-File", str(BOOTSTRAP_PS1),
            "-ArchivePath", str(zip_path),
            "-ExpectedSha256", expected_sha,
            "-DestinationRoot", str(ok_dest),
            "-Python", sys.executable,
        ],
        capture_output=True, text=True, timeout=45, check=False,
    )
    # Exits 0 on clean virtual guest or 3 on non-guest primary host (never unexpected crash).
    assert proc_ok.returncode in {0, 3}
    preflight = json.loads(proc_ok.stdout.strip().splitlines()[-1])
    assert preflight["source_integrity"]["verified"] is True

    # Verify-H4GuestBundle directly rejects unsupported Python shim with exit 2
    verify_ps1 = ok_dest / "scripts" / "Verify-H4GuestBundle.ps1"
    proc_verify_py = subprocess.run(
        [
            PWSH, "-NoProfile", "-NonInteractive", "-File", str(verify_ps1),
            "-BundleRoot", str(ok_dest),
            "-Python", str(fake_py),
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc_verify_py.returncode == 2
    assert "3.12+" in (proc_verify_py.stdout + proc_verify_py.stderr)

    # Tamper extracted component -> Verify-H4GuestBundle must fail BEFORE preflight
    (ok_dest / "harness" / "windows_acceptance.py").write_text("# tampered\n", encoding="utf-8")
    proc_tamper = subprocess.run(
        [
            PWSH, "-NoProfile", "-NonInteractive", "-File", str(verify_ps1),
            "-BundleRoot", str(ok_dest),
            "-Python", sys.executable,
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc_tamper.returncode == 2
    assert "bundle_component_mismatch" in proc_tamper.stderr

    # 4. Missing Verify-H4GuestBundle.ps1 inside custom zip triggers cleanup of newly created dest
    incomplete_zip = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(incomplete_zip, "w") as zf:
        zf.writestr("README.md", b"no verify script")
    import hashlib
    inc_sha = hashlib.sha256(incomplete_zip.read_bytes()).hexdigest()
    inc_dest = tmp_path / "dest_incomplete"
    proc_inc = subprocess.run(
        [
            PWSH, "-NoProfile", "-NonInteractive", "-File", str(BOOTSTRAP_PS1),
            "-ArchivePath", str(incomplete_zip),
            "-ExpectedSha256", inc_sha,
            "-DestinationRoot", str(inc_dest),
            "-Python", sys.executable,
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc_inc.returncode != 0
    assert not inc_dest.exists()


def test_build_bundle_allows_cross_drive_output_and_rejects_live_package_containment():
    import os

    repo_root = MODULE_ROOT.parents[1]
    if os.name == "nt":
        other_drive = "Z:" if repo_root.drive.upper() != "Z:" else "Y:"
        cross_drive_out = Path(f"{other_drive}\\h4_cross_drive_plan_only")
        plan = bundle_builder.build_bundle(
            repo_root=repo_root,
            output_dir=cross_drive_out,
            new_ref="HEAD",
            apply=False,
        )
        assert plan["status"] == "planned"
        assert plan["output_dir"] == str(cross_drive_out)

    with pytest.raises(bundle_builder.SourceIntegrityError) as exc_info:
        bundle_builder.build_bundle(
            repo_root=repo_root,
            output_dir=MODULE_ROOT / "resource_coordinator" / "sub_out",
            new_ref="HEAD",
            apply=False,
        )
    assert exc_info.value.code == "bundle_output_unsafe"


def test_cleanup_allowlist_accepts_lifecycle_runs_and_junit_xml(tmp_path):
    run_root = tmp_path / "h4-rc-cleanup-allowlist"
    run_root.mkdir()
    (run_root / ".h4-test-root.json").write_text("{}", encoding="utf-8")
    (run_root / "runs").mkdir()
    (run_root / "junit.xml").write_text("<testsuite/>", encoding="utf-8")

    reasons = windows_acceptance.task_path_reasons(run_root)
    assert not any("unrecognized" in r or "not_empty" in r for r in reasons), reasons
    rc = windows_acceptance.main(["--test-root", str(run_root), "--profile", "cleanup", "--json"])
    assert rc == 3


def test_task_profile_uses_verified_source_root_from_extracted_bundle_layout(tmp_path, monkeypatch):
    bundle_root = tmp_path / "extracted_bundle"
    harness_dir = bundle_root / "harness"
    harness_dir.mkdir(parents=True)
    bundle_runner = harness_dir / "windows_acceptance.py"
    bundle_runner.write_text("# extracted runner copy\n", encoding="utf-8")

    src_root = bundle_root / "sources" / "rc-1.0.0"
    mod_root = src_root / "modules" / "resource_coordinator"
    tests_dir = mod_root / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_windows_task_transport_integration.py").write_text(
        "def test_windows_disposable_task_registration_snapshot_restore_and_verification():\n    pass\n",
        encoding="utf-8",
    )
    manifest = bundle_root / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    run_root = tmp_path / "h4-rc-task-bundle-layout"
    run_root.mkdir()

    monkeypatch.setenv("RC_H4_DISPOSABLE_GUEST_AUTHORIZED", windows_acceptance.AUTHORIZATION_PHRASE)
    monkeypatch.setattr(windows_acceptance, "__file__", str(bundle_runner))
    monkeypatch.setattr(windows_acceptance.sys, "platform", "win32")
    monkeypatch.setattr(windows_acceptance, "_run_powershell", lambda **kw: {"queries": {"system": "ok"}})
    monkeypatch.setattr(windows_acceptance, "guard_reasons", lambda *a, **kw: ())
    monkeypatch.setattr(windows_acceptance, "task_path_reasons", lambda *a, **kw: ())
    monkeypatch.setattr(
        windows_acceptance,
        "_repository_roots",
        lambda *a, **kw: (src_root, None, "deadbeef" * 8, None),
    )

    captured = {}

    class _FakeCompleted:
        returncode = 0
        stdout = "1 passed"
        stderr = ""

    def _fake_run(command, cwd=None, env=None, **kwargs):
        captured["command"] = list(command)
        captured["cwd"] = Path(cwd)
        captured["pythonpath"] = env.get("PYTHONPATH", "")
        captured["flag"] = env.get("RC_WINDOWS_TASK_INTEGRATION")
        junit_idx = command.index("--junitxml") + 1
        Path(command[junit_idx]).write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0"></testsuite>',
            encoding="utf-8",
        )
        return _FakeCompleted()

    monkeypatch.setattr(windows_acceptance.subprocess, "run", _fake_run)

    rc = windows_acceptance.main(
        [
            "--test-root",
            str(run_root),
            "--apply",
            "--profile",
            "task",
            "--authorization",
            windows_acceptance.AUTHORIZATION_PHRASE,
            "--authorize-guest-mutation",
            "--source-root",
            str(src_root),
            "--source-manifest",
            str(manifest),
            "--json",
        ]
    )
    assert rc == 0
    assert captured["cwd"] == mod_root.resolve()
    assert str(mod_root.resolve()) in captured["pythonpath"]
    assert captured["flag"] == "1"
    assert (
        "tests/test_windows_task_transport_integration.py::test_windows_disposable_task_registration_snapshot_restore_and_verification"
        in captured["command"]
    )


def test_task_profile_target_collects_from_module_root():
    import subprocess
    import sys

    target = "tests/test_windows_task_transport_integration.py::test_windows_disposable_task_registration_snapshot_restore_and_verification"
    res = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "--collect-only", target],
        cwd=MODULE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "test_windows_disposable_task_registration_snapshot_restore_and_verification" in res.stdout


def test_build_bundle_supports_explicit_tooling_ref_preserving_release_sources(tmp_path):
    import json

    repo_root = MODULE_ROOT.parents[1]
    out_dir = tmp_path / "bundle_tooling_ref"
    pinned_new = "0a93d5251142b5526329521252cb9a360ad94460"
    pinned_old = "873a49382a5e03da47f793608d3519f7e69da646"
    tooling_ref = "70de4853664f44ec3feb652a9aa8bac8135739af"

    receipt = bundle_builder.build_bundle(
        repo_root=repo_root,
        output_dir=out_dir,
        new_ref=pinned_new,
        old_ref=pinned_old,
        tooling_ref=tooling_ref,
        apply=True,
    )
    assert receipt["archive_verified"] is True
    assert receipt["new_commit"] == pinned_new
    assert receipt["old_commit"] == pinned_old
    assert receipt["tooling_commit"] == tooling_ref
    assert receipt["tooling_ref_explicit"] is True
    assert receipt["new_source_tree_sha256"] == "27764f44b7311072b62b0dbf8d8faa96260f3deb8a0f09bf0bef969368599989"
    assert receipt["old_source_tree_sha256"] == "4fa9978efc5c0045594a6fa115e803de7da837ccb80863e51324b69c85718dc0"

    manifest = json.loads(Path(receipt["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["tooling_source"]["commit_sha"] == tooling_ref
    assert manifest["tooling_source"]["explicit_tooling_ref"] is True

    harness_runner = (out_dir / "h4-windows-acceptance" / "harness" / "windows_acceptance.py").read_text(encoding="utf-8")
    assert "if args.source_root is not None" in harness_runner


def test_listener_inventory_distinguishes_empty_occupied_and_unavailable(tmp_path, monkeypatch):
    import inspect

    ps_src = inspect.getsource(windows_acceptance._run_powershell)
    assert "MSFT_NetTCPConnection" in ps_src
    assert "Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection" in ps_src
    assert "Get-NetTCPConnection -State Listen -LocalPort" not in ps_src

    monkeypatch.setattr(windows_acceptance, "guest_identity", lambda ev: True)
    h4_root = tmp_path / "h4-rc-listener-test"
    h4_root.mkdir()
    base_ev = {
        "queries": {"system": "available", "tasks": "available", "services": "available", "processes": "available", "listener": "available"},
        "rc_tasks": [],
        "rc_services": [],
        "rc_processes": [],
        "listener_port": 49676,
        "listener_rows": [],
    }
    assert windows_acceptance.guard_reasons(base_ev, h4_root, is_windows=True) == []

    occupied_ev = {
        **base_ev,
        "listener_rows": [{"port": 49676, "pid": 9999, "creation_time": 1.0, "executable_path": "c:\\other.exe"}],
    }
    assert "listener_port_owner_unverified" in windows_acceptance.guard_reasons(occupied_ev, h4_root, is_windows=True)

    unavailable_ev = {
        **base_ev,
        "queries": {**base_ev["queries"], "listener": "error"},
    }
    assert "listener_inventory_unavailable" in windows_acceptance.guard_reasons(unavailable_ev, h4_root, is_windows=True)


def test_lifecycle_guard_failure_emits_structured_sanitized_diagnostics(tmp_path, monkeypatch):
    import json

    src_root = tmp_path / "sources" / "rc-1.0.0"
    old_root = tmp_path / "sources" / "rc-0.14.0"
    src_root.mkdir(parents=True)
    old_root.mkdir(parents=True)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    run_root = tmp_path / "h4-rc-full-diag"
    run_root.mkdir()

    monkeypatch.setenv("RC_H4_DISPOSABLE_GUEST_AUTHORIZED", windows_acceptance.AUTHORIZATION_PHRASE)
    monkeypatch.setattr(windows_acceptance.sys, "platform", "win32")
    monkeypatch.setattr(windows_acceptance.os, "name", "nt")
    monkeypatch.setattr(windows_acceptance, "_run_powershell", lambda **kw: {
        "queries": {"system": "available", "tasks": "available", "services": "available", "processes": "available", "listener": "error"},
        "computer": {"manufacturer": "Microsoft Corporation", "model": "Virtual Machine", "hypervisor_present": True},
    })
    monkeypatch.setattr(windows_acceptance, "guest_identity", lambda ev: True)
    monkeypatch.setattr(windows_acceptance, "task_path_reasons", lambda *a, **kw: [])
    monkeypatch.setattr(
        windows_acceptance,
        "_repository_roots",
        lambda *a, **kw: (src_root, old_root, "a" * 64, "b" * 64),
    )

    def _lifecycle_with_port_gate(profile, root, s_root, o_root, timeout, fault):
        gate = windows_acceptance.GuestMutationGate(
            root,
            ("ResourceCoordinator-H4-1234567890-install-boot",),
            listener_port=49676,
        )
        gate()
        return {}

    rc = windows_acceptance.main(
        [
            "--test-root", str(run_root),
            "--apply", "--profile", "full",
            "--authorization", windows_acceptance.AUTHORIZATION_PHRASE,
            "--authorize-guest-mutation",
            "--source-root", str(src_root),
            "--old-source-root", str(old_root),
            "--source-manifest", str(manifest),
            "--json",
        ],
        lifecycle_runner_override=_lifecycle_with_port_gate,
    )
    assert rc == 4
    results = json.loads((run_root / "test-results.json").read_text(encoding="utf-8"))
    assert results["stage"] == "guard"
    assert results["reason_code"] == "guest_mutation_guard_refused"
    assert results["guard_reasons"] == ["listener_inventory_unavailable"]
    cleanup = json.loads((run_root / "cleanup-result.json").read_text(encoding="utf-8"))
    assert cleanup["stage"] == "guard"
    assert cleanup["reason_code"] == "guest_mutation_guard_refused"
    assert cleanup["guard_reasons"] == ["listener_inventory_unavailable"]
