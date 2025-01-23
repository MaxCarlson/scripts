import argparse
import subprocess
from pathlib import Path
from script_manager.scripts import move_script_to_path
from script_manager.requirements import extract_imports

def install_requirements(requirements_file):
    """Install requirements using Conda if active, otherwise use pip."""
    if not requirements_file.exists():
        print(f"No requirements file found: {requirements_file}")
        return

    print(f"Installing dependencies from {requirements_file}...")
    
    if is_conda_active():
        print("Conda environment detected. Using conda to install dependencies.")
        try:
            subprocess.run(["conda", "install", "-y", "--file", str(requirements_file)], check=True)
        except subprocess.CalledProcessError:
            print("Some dependencies could not be resolved with Conda. Falling back to pip.")
            subprocess.run(["pip", "install", "-r", str(requirements_file)], check=True)
    else:
        print("No Conda environment detected. Using pip to install dependencies.")
        subprocess.run(["pip", "install", "-r", str(requirements_file)], check=True)

def main():
    parser = argparse.ArgumentParser(description="Manage executable scripts")
    parser.add_argument("-s", "--sources", type=str, required=True)
    parser.add_argument("-p", "--exe_path", type=str, default="~/scripts/bin/")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--symlink", action="store_true")

    args = parser.parse_args()

    script_path = Path(args.sources).expanduser()
    exe_path = Path(args.exe_path).expanduser()

    # Move or symlink script
    move_script_to_path(script_path, exe_path, args.force, args.symlink)

    # Generate and install requirements for standalone scripts
    req_dir = Path("~/scripts/requirements/").expanduser()
    req_dir.mkdir(exist_ok=True)
    
    req_file = req_dir / f"{script_path.stem}.txt"
    dependencies = extract_imports([script_path])
    req_file.write_text("\n".join(dependencies))

    install_requirements(req_file)

if __name__ == "__main__":
    main()
