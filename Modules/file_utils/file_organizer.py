import os
import time


def organize_files(directory, mode):
    """Organize files in the directory based on the mode."""
    if mode == "type":
        for root, _, files in os.walk(directory):
            for file in files:
                ext = os.path.splitext(file)[1][1:].lower() or "no_extension"
                target_dir = os.path.join(directory, ext)
                os.makedirs(target_dir, exist_ok=True)
                os.rename(os.path.join(root, file), os.path.join(target_dir, file))
                print(f"Moved: {file} -> {target_dir}")
    elif mode == "date":
        for root, _, files in os.walk(directory):
            for file in files:
                full_path = os.path.join(root, file)
                ctime = os.path.getctime(full_path)
                date = time.strftime("%Y-%m-%d", time.localtime(ctime))
                target_dir = os.path.join(directory, date)
                os.makedirs(target_dir, exist_ok=True)
                os.rename(full_path, os.path.join(target_dir, file))
                print(f"Moved: {file} -> {target_dir}")
