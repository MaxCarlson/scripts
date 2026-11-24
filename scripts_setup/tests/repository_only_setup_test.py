"""Regression coverage for repository-only setup and managed launchers."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

try:
    import tomllib
except ImportError:  # Python 3.10 and earlier
    import tomli as tomllib

from scripts_setup import launcher_generator, setup_utils
from scripts_setup import setup_skills
from scripts_setup import shared_packages


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_root_setup():
    previous = os.environ.get("SKIP_VENV_BOOTSTRAP")
    os.environ["SKIP_VENV_BOOTSTRAP"] = "1"
    try:
        spec = importlib.util.spec_from_file_location("root_setup_repository_only_test", REPO_ROOT / "setup.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            os.environ.pop("SKIP_VENV_BOOTSTRAP", None)
        else:
            os.environ["SKIP_VENV_BOOTSTRAP"] = previous
    return module


def _load_modules_setup():
    spec = importlib.util.spec_from_file_location(
        "modules_setup_repository_only_test", REPO_ROOT / "modules" / "setup.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("argv", [["-r"], ["--repository-only"]])
def test_root_setup_accepts_repository_only_short_and_long_flags(argv):
    setup = _load_root_setup()

    args = setup.parse_args(argv)

    assert args.repository_only is True


@pytest.mark.parametrize("argv", [["--repository-on"], ["-rv"]])
def test_repository_only_detection_accepts_argparse_abbreviations_and_combined_flags(argv):
    setup = _load_root_setup()

    assert setup._repository_only_requested(argv)
    assert setup.parse_args(argv).repository_only


def test_root_setup_accepts_repeated_skill_destinations():
    setup = _load_root_setup()
    first = Path("C:/temporary/skills-one")
    second = Path("C:/temporary/skills-two")

    args = setup.parse_args(["-K", str(first), "--skills-dir", str(second)])

    assert args.skills_dir == [first, second]


def test_scripts_setup_distribution_packages_its_runtime_imports():
    pyproject_path = REPO_ROOT / "scripts_setup" / "pyproject.toml"
    config = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    setuptools_config = config["tool"]["setuptools"]

    assert setuptools_config["packages"] == ["scripts_setup"]
    assert setuptools_config["package-dir"]["scripts_setup"] == "."
    assert (REPO_ROOT / "scripts_setup" / "__init__.py").is_file()

    setup = _load_root_setup()
    assert setup._expected_import_modules(REPO_ROOT / "scripts_setup", "scripts_setup_utils") == ["scripts_setup"]


def test_repository_only_subsets_keep_installers_and_skip_user_integration_wrappers(tmp_path):
    setup = _load_root_setup()

    sub_setups = setup._build_sub_setups(tmp_path, repository_only=True)

    assert [path.relative_to(tmp_path).as_posix() for path, _ in sub_setups] == [
        "modules/setup.py",
        "pscripts/modules/setup.py",
    ]


def test_normal_subsets_keep_existing_setup_wrappers(tmp_path):
    setup = _load_root_setup()

    sub_setups = setup._build_sub_setups(tmp_path, repository_only=False)

    assert [path.relative_to(tmp_path).as_posix() for path, _ in sub_setups] == [
        "pyscripts/setup.py",
        "shell-scripts/setup.py",
        "modules/setup.py",
        "pscripts/setup.py",
    ]


def test_repository_only_integration_helper_skips_profile_path_skills_activation_and_wsl(tmp_path, monkeypatch):
    setup = _load_root_setup()
    run_setup = Mock(side_effect=AssertionError("integration subprocess invoked"))
    monkeypatch.setattr(setup, "run_setup", run_setup)

    setup._run_environment_integrations(
        repository_only=True,
        scripts_dir=tmp_path,
        dotfiles_dir=tmp_path / "dotfiles",
        bin_dir=tmp_path / "bin",
        skills_dirs=None,
        verbose=False,
    )

    run_setup.assert_not_called()


def test_normal_integration_helper_preserves_existing_hooks_and_forwards_skill_destinations(tmp_path, monkeypatch):
    setup = _load_root_setup()
    calls = []
    monkeypatch.setattr(setup, "run_setup", lambda script, *args: calls.append((Path(script).name, args)))
    monkeypatch.setattr(setup, "_run_auto_activation", lambda dotfiles_dir, verbose: calls.append(("activation", ())))

    setup._run_environment_integrations(
        repository_only=False,
        scripts_dir=tmp_path,
        dotfiles_dir=tmp_path / "dotfiles",
        bin_dir=tmp_path / "bin",
        skills_dirs=[tmp_path / "agent-skills", tmp_path / "other-skills"],
        verbose=False,
    )

    assert [name for name, _ in calls] == ["setup_path.py", "setup_pwsh_profile.py", "setup_skills.py", "activation"]
    skill_args = calls[2][1]
    assert skill_args.count("--skills-dir") == 2
    assert str(tmp_path / "agent-skills") in skill_args
    assert str(tmp_path / "other-skills") in skill_args


def test_repository_only_wsl_hook_is_skipped(tmp_path, monkeypatch):
    setup = _load_root_setup()
    run_setup = Mock(side_effect=AssertionError("system setup subprocess invoked"))
    monkeypatch.setattr(setup, "run_setup", run_setup)
    monkeypatch.setattr(setup.platform, "uname", lambda: SimpleNamespace(release="microsoft-standard-WSL2"))

    setup._run_wsl2_integration(repository_only=True, verbose=False)

    run_setup.assert_not_called()


def test_run_setup_passes_repository_only_environment_to_child(tmp_path, monkeypatch):
    setup = _load_root_setup()
    child = tmp_path / "child.py"
    child.write_text("pass\n", encoding="utf-8")
    seen = {}

    def fake_stream(cmd, *, env, tag):
        seen.update(env)
        return 0, "", ""

    monkeypatch.setenv("SCRIPTS_REPOSITORY_ONLY", "1")
    monkeypatch.setattr(setup, "_popen_stream_and_log", fake_stream)

    setup.run_setup(child)

    assert seen["SCRIPTS_REPOSITORY_ONLY"] == "1"


def test_repository_only_environment_marker_is_set_and_cleared(monkeypatch, tmp_path):
    setup = _load_root_setup()
    inherited_pythonpath = tmp_path / "external-python-path"
    environment_overrides = {
        "PYTHONHOME": "C:/external/python-home",
        "PYTHONPATH": str(inherited_pythonpath),
        "PYTHONUSERBASE": "C:/external/python-user-base",
        "PIP_TARGET": "C:/external/pip-target",
        "PIP_PREFIX": "C:/external/pip-prefix",
        "PIP_USER": "1",
        "PIP_ROOT": "C:/external/pip-root",
    }
    for name, value in environment_overrides.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(setup.sys, "path", [*setup.sys.path, str(inherited_pythonpath)])

    setup._configure_repository_only(True)
    assert os.environ[setup.REPOSITORY_ONLY_ENV] == "1"
    assert os.environ["PYTHONNOUSERSITE"] == "1"
    assert all(name not in os.environ for name in environment_overrides)
    assert str(inherited_pythonpath) not in setup.sys.path
    setup._configure_repository_only(False)
    assert setup.REPOSITORY_ONLY_ENV not in os.environ


def test_repository_only_bootstrap_clears_destination_overrides_before_venv_setup(tmp_path, monkeypatch):
    setup = _load_root_setup()
    repository = tmp_path / "repo"
    repository.mkdir()
    repository_venv = repository / ".venv"
    venv_python = repository_venv / "bin" / "python"
    inherited_pythonpath = tmp_path / "inherited-pythonpath"
    monkeypatch.setenv("PYTHONPATH", str(inherited_pythonpath))
    monkeypatch.setenv("PIP_TARGET", str(tmp_path / "external-pip-target"))
    monkeypatch.setattr(setup, "SCRIPTS_DIR", repository)
    monkeypatch.setattr(setup, "VENV_DIR", repository_venv)
    monkeypatch.setattr(setup, "_venv_python", lambda: venv_python)
    monkeypatch.setattr(setup, "_create_venv", lambda: None)
    monkeypatch.setattr(setup, "_ensure_pip_in_venv", lambda _path: None)
    monkeypatch.setattr(setup.os, "execv", Mock())
    monkeypatch.setattr(setup.sys, "executable", str(tmp_path / "system-python"))
    monkeypatch.setattr(setup.sys, "prefix", str(tmp_path / "system"))
    monkeypatch.setattr(setup.sys, "argv", ["setup.py", "--repository-only"])
    monkeypatch.setattr(setup.sys, "path", [*setup.sys.path, str(inherited_pythonpath)])

    setup._bootstrap_venv_if_needed()

    assert "PYTHONPATH" not in os.environ
    assert "PIP_TARGET" not in os.environ
    assert str(inherited_pythonpath) not in setup.sys.path


def test_repository_only_flag_is_preserved_by_venv_reexecution(tmp_path, monkeypatch):
    setup = _load_root_setup()
    venv_python = tmp_path / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    exec_calls = []
    monkeypatch.delenv("SKIP_VENV_BOOTSTRAP", raising=False)
    monkeypatch.delenv("SCRIPTS_REPOSITORY_ONLY", raising=False)
    monkeypatch.setattr(setup, "_venv_python", lambda: venv_python)
    monkeypatch.setattr(setup, "_ensure_pip_in_venv", lambda _path: None)
    monkeypatch.setattr(setup.os, "execv", lambda executable, argv: exec_calls.append((executable, argv)))
    monkeypatch.setattr(setup.sys, "executable", str(tmp_path / "system-python.exe"))
    monkeypatch.setattr(setup.sys, "argv", ["setup.py", "--repository-only"])

    setup._bootstrap_venv_if_needed()

    assert exec_calls[0][1][-1] == "--repository-only"


def test_repository_only_ignores_inherited_skip_venv_and_reexecutes_repository_venv(tmp_path, monkeypatch):
    setup = _load_root_setup()
    venv_python = tmp_path / "Scripts" / "python.exe"
    create_venv = Mock()
    exec_calls = []
    monkeypatch.setenv("SKIP_VENV_BOOTSTRAP", "1")
    monkeypatch.setattr(setup, "_venv_python", lambda: venv_python)
    monkeypatch.setattr(setup, "_create_venv", create_venv)
    monkeypatch.setattr(setup.os, "execv", lambda executable, argv: exec_calls.append((executable, argv)))
    monkeypatch.setattr(setup.sys, "executable", str(tmp_path / "system-python.exe"))
    monkeypatch.setattr(setup.sys, "argv", ["setup.py", "--repository-only"])

    setup._bootstrap_venv_if_needed()

    create_venv.assert_called_once_with()
    assert exec_calls and exec_calls[0][0] == str(venv_python)


def test_repository_only_bootstrap_uses_prefix_when_venv_python_is_a_symlink(tmp_path, monkeypatch):
    setup = _load_root_setup()
    repository = tmp_path / "repo"
    repository_venv = repository / ".venv"
    venv_python = repository_venv / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    system_python = tmp_path / "system" / "bin" / "python3"
    shared_python_target = tmp_path / "usr" / "bin" / "python3"
    exec_calls = []
    ensure_pip = Mock()
    original_resolve = Path.resolve

    def resolve_symlinked_python(path, *args, **kwargs):
        if path in {venv_python, system_python}:
            return shared_python_target
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(setup, "SCRIPTS_DIR", repository)
    monkeypatch.setattr(setup, "VENV_DIR", repository_venv)
    monkeypatch.setattr(setup, "_venv_python", lambda: venv_python)
    monkeypatch.setattr(setup, "_venv_site_packages_pyver", lambda: None)
    monkeypatch.setattr(setup, "_ensure_pip_in_venv", ensure_pip)
    monkeypatch.setattr(setup, "_create_venv", Mock())
    monkeypatch.setattr(setup.os, "execv", lambda executable, argv: exec_calls.append((executable, argv)))
    monkeypatch.setattr(setup.sys, "executable", str(system_python))
    monkeypatch.setattr(setup.sys, "prefix", str(tmp_path / "system"))
    monkeypatch.setattr(setup.sys, "argv", ["setup.py", "--repository-only"])
    monkeypatch.setattr(Path, "resolve", resolve_symlinked_python)

    setup._bootstrap_venv_if_needed()

    ensure_pip.assert_called_once_with(venv_python)
    assert exec_calls and exec_calls[0][0] == str(venv_python)
    monkeypatch.setattr(setup.sys, "prefix", str(repository_venv))
    setup._validate_repository_only_interpreter()


@pytest.mark.skipif(os.name == "nt", reason="Requires POSIX venv interpreter symlinks")
def test_repository_only_bootstrap_reexecs_from_system_python_with_real_symlink_venv(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    setup_copy = repository / "setup.py"
    setup_copy.write_bytes((REPO_ROOT / "setup.py").read_bytes())
    venv_dir = repository / ".venv"
    subprocess.run([sys.executable, "-m", "venv", "--symlinks", str(venv_dir)], check=True)
    venv_python = venv_dir / "bin" / "python"
    assert venv_python.is_symlink()
    assert venv_python.resolve() == Path(sys.executable).resolve()
    venv_probe = subprocess.run(
        [str(venv_python), "-c", "import sys; print(sys.prefix)"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert Path(venv_probe.stdout.strip()).resolve() == venv_dir.resolve()

    probe = tmp_path / "bootstrap_probe.py"
    probe.write_text(
        "import os, subprocess, sys\n"
        "from types import SimpleNamespace\n"
        "from pathlib import Path\n"
        "calls = []\n"
        "subprocess.run = lambda *args, **kwargs: SimpleNamespace(returncode=0)\n"
        "os.execv = lambda path, argv: calls.append((path, argv))\n"
        "setup_path = sys.argv[1]\n"
        "sys.argv = [setup_path, '--repository-only']\n"
        "namespace = {'__name__': 'bootstrap_probe', '__file__': setup_path}\n"
        "exec(compile(Path(setup_path).read_text(encoding='utf-8'), setup_path, 'exec'), namespace)\n"
        "print('EXEC_TARGET=' + calls[0][0] if calls else 'EXEC_TARGET=none')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "SKIP_VENV_BOOTSTRAP"):
        env.pop(name, None)
    result = subprocess.run(
        [sys.executable, str(probe), str(setup_copy)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert f"EXEC_TARGET={venv_python}" in result.stdout


def test_repository_only_rejects_explicit_no_venv_even_with_inherited_skip(tmp_path, monkeypatch):
    setup = _load_root_setup()
    monkeypatch.setenv("SKIP_VENV_BOOTSTRAP", "1")
    monkeypatch.setattr(setup.sys, "argv", ["setup.py", "--repository-only", "--no-venv"])

    with pytest.raises(SystemExit) as error:
        setup._bootstrap_venv_if_needed()

    assert error.value.code == 2


@pytest.mark.parametrize(
    ("repository_flag", "bin_flag", "redirected"),
    [
        ("--repository-only", "--bin-dir", False),
        ("--repository-on", "--bin-d", False),
        ("-rB", "", False),
        ("-r", "--bin-dir", True),
    ],
)
def test_repository_only_rejects_external_bin_before_creating_venv(
    tmp_path, monkeypatch, repository_flag, bin_flag, redirected
):
    setup = _load_root_setup()
    create_venv = Mock()
    monkeypatch.delenv("SKIP_VENV_BOOTSTRAP", raising=False)
    monkeypatch.setattr(setup, "_venv_python", lambda: tmp_path / "missing-venv" / "python.exe")
    monkeypatch.setattr(setup, "_create_venv", create_venv)
    monkeypatch.setattr(setup.os, "execv", Mock())
    bin_override = setup.SCRIPTS_DIR / "redirected-bin" if redirected else tmp_path / "external-bin"
    if redirected:
        original_resolve = Path.resolve

        def resolve_with_redirect(path, *args, **kwargs):
            if path == bin_override:
                return tmp_path / "external-bin"
            return original_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve_with_redirect)
    argv = ["setup.py", repository_flag]
    if bin_flag:
        argv.append(bin_flag)
    argv.append(str(bin_override))
    monkeypatch.setattr(setup.sys, "argv", argv)

    with pytest.raises(SystemExit) as error:
        setup._bootstrap_venv_if_needed()

    assert error.value.code == 2
    create_venv.assert_not_called()


def test_repository_only_rejects_incompatible_active_interpreter(tmp_path, monkeypatch):
    setup = _load_root_setup()
    repository_venv = setup.SCRIPTS_DIR / ".venv"
    monkeypatch.setattr(setup, "VENV_DIR", repository_venv)
    monkeypatch.setattr(setup, "_venv_python", lambda: repository_venv / "Scripts" / "python.exe")
    monkeypatch.setattr(setup.sys, "executable", str(tmp_path / "other-venv" / "Scripts" / "python.exe"))
    monkeypatch.setattr(setup.sys, "prefix", str(tmp_path / "other-venv"))

    with pytest.raises(RuntimeError, match="active interpreter"):
        setup._validate_repository_only_interpreter()


def test_repository_only_rejects_venv_redirected_outside_invoked_repository(tmp_path, monkeypatch):
    setup = _load_root_setup()
    monkeypatch.setattr(setup, "VENV_DIR", tmp_path / "external-venv")

    with pytest.raises(RuntimeError, match=".venv inside the invoked repository"):
        setup._validate_repository_only_interpreter()


def test_repository_only_rejects_redirected_scripts_root_before_creating_venv(tmp_path, monkeypatch):
    setup = _load_root_setup()
    create_venv = Mock()
    monkeypatch.delenv("SKIP_VENV_BOOTSTRAP", raising=False)
    monkeypatch.setattr(setup, "_venv_python", lambda: tmp_path / "missing-venv" / "python.exe")
    monkeypatch.setattr(setup, "_create_venv", create_venv)
    monkeypatch.setattr(setup.os, "execv", Mock())
    redirect = setup.SCRIPTS_DIR / "redirected-source"
    original_resolve = Path.resolve

    def resolve_with_redirect(path, *args, **kwargs):
        if path == redirect:
            return tmp_path / "external-source"
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_with_redirect)
    monkeypatch.setattr(setup.sys, "argv", ["setup.py", "--repository-only", "--scripts-dir", str(redirect)])

    with pytest.raises(SystemExit) as error:
        setup._bootstrap_venv_if_needed()

    assert error.value.code == 2
    create_venv.assert_not_called()


def test_repository_only_rejects_external_venv_before_creating_or_updating_it(tmp_path, monkeypatch):
    setup = _load_root_setup()
    external_venv = tmp_path / "external-venv"
    create_venv = Mock()
    monkeypatch.delenv("SKIP_VENV_BOOTSTRAP", raising=False)
    monkeypatch.setattr(setup, "VENV_DIR", external_venv)
    monkeypatch.setattr(setup, "_venv_python", lambda: external_venv / "Scripts" / "python.exe")
    monkeypatch.setattr(setup, "_create_venv", create_venv)
    monkeypatch.setattr(setup.os, "execv", Mock())
    monkeypatch.setattr(setup.sys, "argv", ["setup.py", "--repository-only"])

    with pytest.raises(SystemExit) as error:
        setup._bootstrap_venv_if_needed()

    assert error.value.code == 2
    create_venv.assert_not_called()


def _prepare_repository_only_main(setup, monkeypatch, run_setup_calls):
    monkeypatch.setattr(setup, "_log_init", lambda: None)
    monkeypatch.setattr(setup, "_validate_repository_only_interpreter", lambda: None, raising=False)
    monkeypatch.setattr(setup, "report_or_repair_invalid_aebndl_dists", lambda repair=False: 0)
    monkeypatch.setattr(setup, "init_timer", lambda: None)
    monkeypatch.setattr(setup, "ensure_module_installed", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "run_setup", lambda path, *args, **kwargs: run_setup_calls.append((Path(path), args)))
    monkeypatch.setattr(shared_packages, "ensure_shared_distributions", lambda **kwargs: True)
    monkeypatch.setattr(setup, "_run_wsl2_integration", lambda *args, **kwargs: None)
    setup.errors.clear()
    setup.warnings.clear()


def test_repository_only_orchestration_ignores_conflicting_environment_and_uses_invoked_root(monkeypatch, tmp_path):
    setup = _load_root_setup()
    external_scripts = tmp_path / "primary-scripts"
    external_dotfiles = tmp_path / "primary-dotfiles"
    run_setup_calls = []
    _prepare_repository_only_main(setup, monkeypatch, run_setup_calls)
    monkeypatch.setenv("SCRIPTS", str(external_scripts))
    monkeypatch.setenv("DOTFILES", str(external_dotfiles))
    monkeypatch.setattr(setup.sys, "argv", ["setup.py", "--repository-only"])

    with pytest.raises(SystemExit) as result:
        setup.main()
    assert result.value.code == 0

    installer_args = [args for path, args in run_setup_calls if path.name == "setup.py"]
    assert installer_args
    for args in installer_args:
        assert "--scripts-dir" in args
        assert args[args.index("--scripts-dir") + 1] == str(setup.SCRIPTS_DIR)
        assert args[args.index("--bin-dir") + 1] == str(setup.SCRIPTS_DIR / "bin")
    launcher_args = next(args for path, args in run_setup_calls if path.name == "launcher_generator.py")
    assert launcher_args[launcher_args.index("--repo-root") + 1] == str(setup.SCRIPTS_DIR)
    assert launcher_args[launcher_args.index("--bin-dir") + 1] == str(setup.SCRIPTS_DIR / "bin")
    assert "--cleanup" in launcher_args
    assert all("setup_path.py" not in str(path) and "setup_pwsh_profile.py" not in str(path) for path, _ in run_setup_calls)
    assert not external_scripts.exists()
    assert not external_dotfiles.exists()


@pytest.mark.parametrize("override", ["--scripts-dir", "--bin-dir"])
def test_repository_only_orchestration_rejects_external_targets_before_install(override, monkeypatch, tmp_path):
    setup = _load_root_setup()
    run_setup_calls = []
    _prepare_repository_only_main(setup, monkeypatch, run_setup_calls)
    log_init = Mock()
    monkeypatch.setattr(setup, "_log_init", log_init)
    external_target = tmp_path / "outside-repository"
    monkeypatch.setattr(setup.sys, "argv", ["setup.py", "--repository-only", override, str(external_target)])
    shared_check = Mock(return_value=True)
    monkeypatch.setattr(shared_packages, "ensure_shared_distributions", shared_check)

    with pytest.raises(SystemExit) as error:
        setup.main()

    assert error.value.code == 2
    log_init.assert_not_called()
    shared_check.assert_not_called()
    assert run_setup_calls == []
    assert not external_target.exists()


def test_repository_only_orchestration_rejects_bin_path_redirected_outside_repository(monkeypatch, tmp_path):
    setup = _load_root_setup()
    run_setup_calls = []
    _prepare_repository_only_main(setup, monkeypatch, run_setup_calls)
    redirect = setup.SCRIPTS_DIR / "redirected-bin"
    external_target = tmp_path / "external-bin"
    original_resolve = Path.resolve

    def resolve_with_redirect(path, *args, **kwargs):
        if path == redirect:
            return external_target
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_with_redirect)
    monkeypatch.setattr(setup.sys, "argv", ["setup.py", "--repository-only", "--bin-dir", str(redirect)])
    shared_check = Mock(return_value=True)
    monkeypatch.setattr(shared_packages, "ensure_shared_distributions", shared_check)

    with pytest.raises(SystemExit) as error:
        setup.main()

    assert error.value.code == 2
    shared_check.assert_not_called()
    assert run_setup_calls == []


def test_modules_setup_skips_user_pythonpath_registration_in_repository_only_mode(tmp_path, monkeypatch):
    modules_setup = _load_modules_setup()
    subprocess_run = Mock(side_effect=AssertionError("registry or shell subprocess invoked"))
    monkeypatch.setattr(modules_setup.subprocess, "run", subprocess_run)
    monkeypatch.setenv("SCRIPTS_REPOSITORY_ONLY", "1")

    modules_setup.ensure_pythonpath(tmp_path / "modules", tmp_path / "dotfiles")

    subprocess_run.assert_not_called()
    assert not (tmp_path / "dotfiles").exists()


def test_launcher_discovery_includes_private_standalone_python_scripts(tmp_path):
    private_scripts = tmp_path / "pscripts" / "pyscripts"
    private_scripts.mkdir(parents=True)
    (private_scripts / "private_tool.py").write_text('__version__ = "2.3.4"\n', encoding="utf-8")
    (private_scripts / "setup.py").write_text("pass\n", encoding="utf-8")

    commands = launcher_generator.scan_repository_programs(tmp_path)

    assert commands["private_tool"].kind == "python_file"
    assert commands["private_tool"].source_path == "pscripts/pyscripts/private_tool.py"
    assert "setup" not in commands


def test_launcher_generation_writes_private_script_wrapper_and_manifest(tmp_path):
    private_scripts = tmp_path / "pscripts" / "pyscripts"
    private_scripts.mkdir(parents=True)
    (private_scripts / "private_tool.py").write_text("print('ready')\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"

    report = launcher_generator.migrate_wrappers(
        tmp_path,
        bin_dir,
        dry_run=False,
        backup_dir=tmp_path / "backup",
    )
    manifest = (tmp_path / "scripts_manifest.json").read_text(encoding="utf-8")
    second = launcher_generator.migrate_wrappers(
        tmp_path,
        bin_dir,
        dry_run=False,
        backup_dir=tmp_path / "backup",
    )

    assert (bin_dir / ("private_tool.cmd" if os.name == "nt" else "private_tool")).is_file()
    assert '"private_tool"' in manifest
    assert report.created_count >= 1
    assert second.created_count == 0


def test_repository_only_launcher_cleanup_removes_only_obsolete_managed_wrappers(tmp_path):
    (tmp_path / "pyscripts").mkdir()
    (tmp_path / "pyscripts" / "active_tool.py").write_text("print('ready')\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    obsolete = bin_dir / ("obsolete_tool.cmd" if os.name == "nt" else "obsolete_tool")
    unmanaged = bin_dir / ("custom_tool.cmd" if os.name == "nt" else "custom_tool")
    obsolete.write_text(launcher_generator.generate_windows_wrapper("obsolete_tool"), encoding="utf-8")
    unmanaged.write_text("custom user launcher\n", encoding="utf-8")
    backup_dir = tmp_path / "backup"

    report = launcher_generator.migrate_wrappers(
        tmp_path,
        bin_dir,
        dry_run=False,
        backup_dir=backup_dir,
        cleanup=True,
    )

    active = bin_dir / ("active_tool.cmd" if os.name == "nt" else "active_tool")
    assert not obsolete.exists()
    assert active.is_file()
    assert unmanaged.read_text(encoding="utf-8") == "custom user launcher\n"
    assert (backup_dir / obsolete.name).is_file()
    assert report.removed_obsolete_count == 1


def test_skill_symlinks_use_only_explicit_destinations(tmp_path, monkeypatch):
    skill = tmp_path / "skill" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    destination = tmp_path / "custom-skills"
    calls = []

    def fake_symlink(src, dest, verbose=True):
        calls.append((src, dest))
        return True

    monkeypatch.setattr(setup_skills, "create_symlink", fake_symlink)

    created, skipped = setup_skills.symlink_skills([skill], cli_skill_dirs=[destination])

    assert (created, skipped) == (1, 0)
    assert calls == [(skill, destination / "demo")]


def test_windows_symlink_privilege_failure_is_reported_without_suppression(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"
    failure = OSError("A required privilege is not held by the client")
    failure.winerror = 1314
    monkeypatch.setattr(setup_utils.os, "name", "nt")
    monkeypatch.setattr(Path, "symlink_to", Mock(side_effect=failure))

    with pytest.raises(SystemExit):
        setup_utils.create_symlink(source, destination, verbose=True)

    output = capsys.readouterr().out
    assert "1314" in output or "privilege" in output.lower()
    assert "Developer Mode or admin privileges" in output
    assert not destination.exists()
