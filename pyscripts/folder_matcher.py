#!/usr/bin/env python3
import os
import shutil
import argparse
import sys

def get_folder_files(folder, ext):
    """
    Return a dict mapping file name to file size for all files
    immediately inside folder whose name ends with the given extension.
    Comparison is done case‐insensitively.
    """
    files = {}
    try:
        for entry in os.listdir(folder):
            full_path = os.path.join(folder, entry)
            if os.path.isfile(full_path) and entry.lower().endswith(ext.lower()):
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    size = None
                files[entry] = size
    except Exception as e:
        print(f"Error reading folder {folder}: {e}")
    return files

def folders_match(source_folder, target_folder, ext):
    """
    Compare the matching files (those ending with ext) in the two folders.
    Return True if the set of file names are equal and for each file the sizes are equal.
    """
    src_files = get_folder_files(source_folder, ext)
    tgt_files = get_folder_files(target_folder, ext)
    if set(src_files.keys()) != set(tgt_files.keys()):
        return False
    for name in src_files:
        if src_files[name] != tgt_files.get(name):
            return False
    return True

def find_matching_folders(source, ext, min_count):
    """
    Walk the source directory recursively.
    For each folder (the immediate directory, not counting its subfolders),
    count the number of files whose names end with ext.
    If that count is at least min_count, record the folder’s path.
    Returns a list of folder paths.
    """
    matching = []
    for dirpath, _dirnames, filenames in os.walk(source):
        count = sum(1 for f in filenames if f.lower().endswith(ext.lower()))
        if count >= min_count:
            matching.append(dirpath)
    return matching

def process_folder(folder, target, ext, delete_flag):
    """
    Given a folder from the source:
      - If a folder with the same basename does not exist in target, move folder.
      - If a folder with that name exists in target:
          - Compare the two folders (only considering files with extension ext).
          - If they match:
              - If delete_flag is set, delete the source folder.
              - Otherwise, print a message.
          - If they do not match, print a warning.
    """
    folder_name = os.path.basename(os.path.normpath(folder))
    target_folder = os.path.join(target, folder_name)
    
    if not os.path.exists(target_folder):
        print(f"Moving folder:\n  Source: {folder}\n  Target: {target_folder}")
        try:
            shutil.move(folder, target_folder)
        except Exception as e:
            print(f"Error moving folder {folder}: {e}")
    else:
        # Folder exists at target: compare matching files.
        if folders_match(folder, target_folder, ext):
            if delete_flag:
                print(f"Deleting source folder (duplicate exists in target): {folder}")
                try:
                    shutil.rmtree(folder)
                except Exception as e:
                    print(f"Error deleting folder {folder}: {e}")
            else:
                print(f"Folder exists and matches target: {folder}")
        else:
            print(f"Folder {folder} exists in target but does not match contents; skipping.")

def main():
    parser = argparse.ArgumentParser(
        description="Find folders with at least n files of a given extension in a source directory. "
                    "Folders that do not exist in the target are moved there; if a folder with the same name exists, "
                    "its contents are compared and (if --delete is passed) the source folder is deleted if identical."
    )
    parser.add_argument("source", help="Source directory to search for folders")
    parser.add_argument("target", help="Target directory to move folders to")
    parser.add_argument("--ext", "-e", required=True, help="File extension to count (e.g. .jpg)")
    parser.add_argument("--num", "-n", type=int, required=True,
                        help="Minimum number of files (with the given extension) required for a folder to qualify")
    parser.add_argument("--delete", "-d", action="store_true",
                        help="If passed, delete the source folder when a matching folder already exists in target")
    args = parser.parse_args()

    source = os.path.abspath(args.source)
    target = os.path.abspath(args.target)

    # Check that source and target exist and are directories.
    if not os.path.isdir(source):
        print(f"Error: Source directory '{source}' does not exist or is not a directory.")
        sys.exit(1)
    if not os.path.isdir(target):
        print(f"Error: Target directory '{target}' does not exist or is not a directory.")
        sys.exit(1)

    # Find folders in source that have at least args.num files ending with args.ext.
    print(f"Scanning '{source}' for folders with at least {args.num} '{args.ext}' files...")
    matching_folders = find_matching_folders(source, args.ext, args.num)
    if not matching_folders:
        print("No folders matching the criteria were found.")
        sys.exit(0)

    print(f"Found {len(matching_folders)} folders matching the criteria.\n")

    # Process each matching folder.
    for folder in matching_folders:
        process_folder(folder, target, args.ext, args.delete)

if __name__ == "__main__":
    main()
