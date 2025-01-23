import shutil
import subprocess
from pathlib import Path

def create_virtual_environment(module_path, module_name, use_conda, force):
    """Creates a virtual or Conda environment for the module."""
    venv_path = module_path / "venv"
    conda_env_name = module_name

    if use_conda:
        if shutil.which("conda") is None:
            raise RuntimeError("Conda is not installed or not in PATH!")

    if venv_path.exists():
        if use_conda:
            if not force:
                confirm = input("A venv exists. Replace with a Conda environment? (y/n): ").strip().lower()
                if confirm != "y":
                    return
            shutil.rmtree(venv_path)

    if use_conda:
        subprocess.run(["conda", "create", "-y", "-n", conda_env_name, "python"], check=True)
    else:
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
