import shutil
import stat
from pathlib import Path
from script_manager.utils import check_name_conflicts

def move_script_to_path(script_path, destination_path, force, symlink=False):
    """Moves or symlinks a script to the designated executable path."""
    script_dest = Path(destination_path, script_path.name)

    check_name_conflicts(script_path.stem)

    if script_dest.exists() and not force:
        raise FileExistsError(f"The script '{script_dest.name}' already exists!")

    if symlink:
        print(f"Creating symlink: {script_dest} -> {script_path}")
        script_dest.symlink_to(script_path)
    else:
        print(f"Copying script to {script_dest}")
        shutil.copy(script_path, script_dest)

    script_dest.chmod(script_dest.stat().st_mode | stat.S_IEXEC)
