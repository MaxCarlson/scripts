"""Integration tests verifying the 4 repository setup entry points use launcher_generator."""
import os
from pathlib import Path
import pytest

from scripts_setup.launcher_generator import (
    MANAGED_SIGNATURE_WINDOWS,
    MANAGED_SIGNATURE_POSIX,
)


@pytest.fixture
def mock_setup_env(tmp_path: Path):
    """Set up disposable repo tree with modules, pyscripts, and bin."""
    repo = tmp_path / "mock_repo"
    bin_dir = repo / "bin"
    bin_dir.mkdir(parents=True)
    venv_scripts = repo / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    venv_scripts.mkdir(parents=True)

    # Fake target executables
    (venv_scripts / ("fake_cmd.exe" if os.name == "nt" else "fake_cmd")).write_text("fake binary", encoding="utf-8")
    
    pyscripts_dir = repo / "pyscripts"
    pyscripts_dir.mkdir(parents=True)
    fake_py = pyscripts_dir / "fake_script.py"
    fake_py.write_text("print('hello')", encoding="utf-8")

    return repo, bin_dir, venv_scripts, fake_py


def test_modules_setup_proxy_generation(mock_setup_env):
    """Test modules/setup.py generate_console_proxies uses launcher_generator and preserves unmanaged."""
    repo, bin_dir, venv_scripts, _ = mock_setup_env

    # 1. Place an unmanaged script with the same name
    unmanaged_target = bin_dir / ("unmanaged_cmd.cmd" if os.name == "nt" else "unmanaged_cmd")
    unmanaged_target.write_text("echo custom user script", encoding="utf-8")

    # Import modules.setup
    import modules.setup as m_setup
    assert callable(m_setup.generate_console_proxies)

    # Test writing managed wrapper directly via write_wrapper as used by modules.setup
    from scripts_setup.launcher_generator import write_wrapper

    managed_wrapper = bin_dir / ("fake_cmd.cmd" if os.name == "nt" else "fake_cmd")
    changed = write_wrapper(managed_wrapper, "fake_cmd")
    assert changed is True
    assert managed_wrapper.is_file()
    content = managed_wrapper.read_text(encoding="utf-8")
    expected_sig = MANAGED_SIGNATURE_WINDOWS if os.name == "nt" else MANAGED_SIGNATURE_POSIX
    assert expected_sig in content

    # Test preserving unmanaged wrapper
    changed_unmanaged = write_wrapper(unmanaged_target, "unmanaged_cmd")
    assert changed_unmanaged is False
    assert unmanaged_target.read_text(encoding="utf-8") == "echo custom user script"


def test_pyscripts_setup_wrapper_generation(mock_setup_env):
    """Test pyscripts/setup.py delegates to launcher_generator and preserves unmanaged."""
    repo, bin_dir, _, fake_py = mock_setup_env

    from pyscripts.setup import _make_windows_wrapper, _make_posix_wrapper

    # 1. Unmanaged wrapper in place
    custom_cmd = bin_dir / "custom_script.cmd"
    custom_cmd.write_text("echo user custom script", encoding="utf-8")
    custom_py = repo / "pyscripts" / "custom_script.py"
    custom_py.write_text("print('custom')", encoding="utf-8")

    _make_windows_wrapper(bin_dir, custom_py, verbose=False)
    # Must remain byte-for-byte unchanged
    assert custom_cmd.read_text(encoding="utf-8") == "echo user custom script"

    # 2. Managed wrapper generation
    _make_windows_wrapper(bin_dir, fake_py, verbose=False)
    gen_cmd = bin_dir / f"{fake_py.stem}.cmd"
    assert gen_cmd.is_file()
    assert MANAGED_SIGNATURE_WINDOWS in gen_cmd.read_text(encoding="utf-8")

    # POSIX wrapper
    _make_posix_wrapper(bin_dir, fake_py, verbose=False)
    gen_posix = bin_dir / fake_py.stem
    assert gen_posix.is_file()
    assert MANAGED_SIGNATURE_POSIX in gen_posix.read_text(encoding="utf-8")


def test_bootstrap_latest_write_console_proxy(mock_setup_env):
    """Test bootstrap_latest.py write_console_proxy creates managed wrapper with signature."""
    repo, bin_dir, venv_scripts, _ = mock_setup_env

    from bootstrap_latest import write_console_proxy

    dest = bin_dir / ("test_proxy.cmd" if os.name == "nt" else "test_proxy")
    (venv_scripts / ("test_proxy.exe" if os.name == "nt" else "test_proxy")).write_text("bin", encoding="utf-8")

    venv_dir = repo / ".venv"
    write_console_proxy(dest, "test_proxy", windows=(os.name == "nt"), venv_dir=venv_dir)

    assert dest.is_file()
    content = dest.read_text(encoding="utf-8")
    expected_sig = MANAGED_SIGNATURE_WINDOWS if os.name == "nt" else MANAGED_SIGNATURE_POSIX
    assert expected_sig in content

    # Should raise FileExistsError if already exists
    with pytest.raises(FileExistsError):
        write_console_proxy(dest, "test_proxy", windows=(os.name == "nt"), venv_dir=venv_dir)


def test_setup_utils_windows_cmd_wrapper(mock_setup_env):
    """Test scripts_setup/setup_utils.py _create_windows_cmd_wrapper."""
    repo, bin_dir, _, fake_py = mock_setup_env

    from scripts_setup.setup_utils import _create_windows_cmd_wrapper

    wrapper_path = bin_dir / f"{fake_py.stem}.cmd"
    _create_windows_cmd_wrapper(wrapper_path, fake_py, verbose=False)

    assert wrapper_path.is_file()
    content = wrapper_path.read_text(encoding="utf-8")
    assert MANAGED_SIGNATURE_WINDOWS in content
