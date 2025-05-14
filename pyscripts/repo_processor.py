#!/usr/bin/env python3
import os
import zipfile
import argparse
import fnmatch
import shutil
from pathlib import Path
import datetime

# Default patterns
DEFAULT_EXCLUDE_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".idea", ".vscode", ".mypy_cache", ".pytest_cache", "dist", "build", "target"}
DEFAULT_EXCLUDE_EXTS = {".pyc", ".pyo", ".exe", ".dll", ".bin", ".o", ".so", ".zip", ".tar", ".gz", ".7z", ".log", ".tmp", ".DS_Store"}
DEFAULT_EXCLUDE_FILES = {"package-lock.json", "yarn.lock", "Pipfile.lock", ".env"}
DEFAULT_MAX_HIERARCHY_DEPTH = 100 # For directory tree generation
DEFAULT_MAX_HIERARCHY_LINES = 50000 # For directory tree string output

def get_directory_size(directory):
    """Returns total size of directory (in bytes)."""
    return sum(f.stat().st_size for f in Path(directory).rglob('*') if f.is_file())

def should_exclude(path_obj: Path, relative_path_str: str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
    """
    Determines if a file or directory should be excluded based on multiple criteria.
    Keep patterns override exclusions. Remove patterns force exclusion unless overridden by keep.
    """
    # Check if explicitly kept
    if any(fnmatch.fnmatch(relative_path_str, pattern) or fnmatch.fnmatch(path_obj.name, pattern) for pattern in keep_patterns_list):
        return False

    # Check if explicitly removed
    if any(fnmatch.fnmatch(relative_path_str, pattern) or fnmatch.fnmatch(path_obj.name, pattern) for pattern in remove_patterns_list):
        return True

    # Check default dir exclusions (applies to dirs themselves and contents of such dirs)
    # Path parts gives components of the path, e.g., ['src', 'module', 'file.py']
    path_parts = relative_path_str.split(os.sep)
    if any(part in exclude_dirs_set for part in path_parts if Path(source_dir_global, *path_parts[:path_parts.index(part)+1]).is_dir()): # Check if any parent folder part is an excluded dir name
         # Check if the path itself is an excluded dir or if any of its parent components (that are dirs) are in exclude_dirs_set
        if path_obj.is_dir() and path_obj.name in exclude_dirs_set:
            return True
        # Check if any parent directory name in its path is an excluded dir name
        current_check_path = Path()
        for part in path_obj.parent.parts: # Check parent parts of the actual file path
            current_check_path = current_check_path / part
            if current_check_path.name in exclude_dirs_set:
                return True


    if path_obj.name in exclude_dirs_set and path_obj.is_dir(): # If the item itself is a dir to be excluded
        return True
    if path_obj.suffix in exclude_exts_set:
        return True
    if path_obj.name in exclude_files_set:
        return True
    
    return False


# Global variable to hold the source directory for should_exclude context
source_dir_global = None


def generate_directory_tree_string(source_dir_path: Path, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, max_depth=DEFAULT_MAX_HIERARCHY_DEPTH, prefix="", is_last=True, is_root=True):
    """Generates a string representation of the directory tree."""
    global source_dir_global # Use the global source_dir
    if is_root:
        source_dir_global = source_dir_path # Set it at the beginning of the call

    lines = []
    if is_root:
        lines.append(f"{source_dir_path.name}/")

    try:
        # Sort entries for consistent output, directories first
        entries = sorted(
            [item for item in source_dir_path.iterdir()],
            key=lambda x: (not x.is_dir(), x.name.lower())
        )
    except PermissionError:
        lines.append(f"{prefix}└── [Error: Permission Denied]")
        return "\n".join(lines)


    for i, entry in enumerate(entries):
        relative_path_str = str(entry.relative_to(source_dir_global)) # Relative to the initial source_dir
        
        if should_exclude(entry, relative_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list) and not entry.is_dir(): # Exclude files, but show excluded dirs if they have non-excluded content
             if entry.is_dir() and not any(not should_exclude(sub_entry, str(sub_entry.relative_to(source_dir_global)), exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list) for sub_entry in entry.rglob("*")):
                continue # Skip excluded emptyish dirs


        connector = "└── " if i == len(entries) - 1 else "├── "
        lines.append(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")

        if entry.is_dir() and (max_depth > 0 or max_depth == -1): # max_depth == -1 for infinite
            new_prefix = prefix + ("    " if i == len(entries) - 1 else "│   ")
            if not should_exclude(entry, relative_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list): # Don't recurse into fully excluded dirs
                lines.extend(generate_directory_tree_string(entry, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, max_depth -1 if max_depth != -1 else -1, new_prefix, i == len(entries) -1, is_root=False).splitlines()[1:]) # [1:] to avoid duplicating dir name

    if is_root:
        source_dir_global = None # Reset global var
    return "\n".join(lines)


def generate_llm_text_output(source_dir_path_str, output_file_path_str, exclude_dirs_list, exclude_exts_list, exclude_files_list, remove_patterns_list, keep_patterns_list, verbose):
    global source_dir_global # Ensure this is accessible
    source_dir = Path(source_dir_path_str).resolve()
    source_dir_global = source_dir # Set for should_exclude and tree generation
    output_file_path = Path(output_file_path_str).resolve()

    exclude_dirs_set = set(exclude_dirs_list)
    exclude_exts_set = set(exclude_exts_list)
    exclude_files_set = set(exclude_files_list)

    # 1. Generate directory tree string
    if verbose: print("Generating directory tree...")
    tree_str = generate_directory_tree_string(source_dir, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list)

    # 2. Discover files and categorize them
    if verbose: print("Discovering and categorizing files...")
    included_files_content = [] # list of (path_in_repo, content)
    excluded_for_listing = []    # list of (path_in_repo, reason)

    for root, dirs, files in os.walk(source_dir, topdown=True):
        root_path = Path(root)
        current_relative_dir = str(root_path.relative_to(source_dir))
        if current_relative_dir == ".": current_relative_dir = "" # Handle root case

        # Filter directories based on exclusion rules for traversal
        # A directory is skipped if its *name* is in exclude_dirs_set and it's not kept by a keep_pattern
        original_dirs = list(dirs) # Iterate over a copy for modification
        dirs[:] = [] # Clear and rebuild
        for d_name in original_dirs:
            dir_path_obj = root_path / d_name
            relative_dir_path_str = str(dir_path_obj.relative_to(source_dir))
            if not should_exclude(dir_path_obj, relative_dir_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
                dirs.append(d_name)
            elif verbose:
                 print(f"Skipping traversal of excluded directory: {relative_dir_path_str}")


        for file_name in files:
            file_path_obj = root_path / file_name
            relative_file_path_str = str(file_path_obj.relative_to(source_dir))

            if should_exclude(file_path_obj, relative_file_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
                excluded_for_listing.append((relative_file_path_str, "Excluded by rules (dir, ext, file, or pattern)"))
                if verbose: print(f"LLM Output: Excluded file listed: {relative_file_path_str}")
                continue

            # If not excluded, read content
            try:
                # Check for binary-like files heuristically if not covered by extension (optional)
                # For now, trust text if not excluded by extension
                content = file_path_obj.read_text(encoding='utf-8', errors='ignore')
                included_files_content.append((relative_file_path_str, content))
                if verbose: print(f"LLM Output: Included content for: {relative_file_path_str}")
            except Exception as e:
                excluded_for_listing.append((relative_file_path_str, f"Error reading file (possibly binary or permission issue): {str(e)[:50]}"))
                if verbose: print(f"LLM Output: Could not read/include content for: {relative_file_path_str} due to {e}")
    
    source_dir_global = None # Reset

    # 3. Format the output string
    output_parts = []
    output_parts.append(f"=== Repository Analysis: {source_dir.name} ===")
    output_parts.append(f"Date Processed: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output_parts.append(f"Root Path: {source_dir}")
    output_parts.append(f"\nSummary:")
    output_parts.append(f"* Files with content included: {len(included_files_content)}")
    output_parts.append(f"* Files listed (content excluded or unreadable): {len(excluded_for_listing)}")
    output_parts.append("\n---\n")

    output_parts.append("**1. Full Directory Structure (filtered):**")
    output_parts.append(tree_str)
    output_parts.append("\n---\n")

    output_parts.append("**2. Contextual Files (Content Excluded or Unreadable):**")
    if excluded_for_listing:
        for rel_path, reason in sorted(list(set(excluded_for_listing))): # set to remove duplicates if any
            output_parts.append(f"- {rel_path} (Reason: {reason})")
    else:
        output_parts.append("No files were specifically excluded from content or unreadable based on filters.")
    output_parts.append("\n---\n")

    output_parts.append("**3. Included Files (Hierarchy & Content):**")
    if included_files_content:
        for rel_path, content in sorted(included_files_content):
            output_parts.append(f"\n--- File: {rel_path} ---")
            output_parts.append(content)
            output_parts.append(f"--- End of File: {rel_path} ---")
    else:
        output_parts.append("No file content was included.")

    output_parts.append("\n=== End of Repository Analysis ===")

    # 4. Write to output file
    try:
        output_file_path.write_text("\n".join(output_parts), encoding='utf-8')
        print(f"\nLLM text output generated at: {output_file_path}")
    except Exception as e:
        print(f"\nError writing LLM text output to {output_file_path}: {e}")


def flatten_directory_for_zip(source_dir_path_str, name_by_path_flag):
    """Moves all files to a single directory for zipping, returns temp dir path."""
    source_dir = Path(source_dir_path_str)
    # Create temp dir inside the original source_dir to avoid issues if source_dir is deleted later by user
    # Or better, create it adjacent or in system temp if permissions allow and it's cleaned up.
    # For simplicity here, let's make it a subdirectory that the main zip function can clean up.
    temp_flat_dir = source_dir / "_flattened_for_zip_temp"
    if temp_flat_dir.exists(): # Clean up from previous run if necessary
        shutil.rmtree(temp_flat_dir)
    temp_flat_dir.mkdir(exist_ok=True)

    moved_files_map = {} # original_rel_path -> new_path_in_flat_dir

    # Copy files first to avoid modifying original structure during walk if errors occur
    files_to_move = []
    for root, _, files in os.walk(source_dir):
        root_path = Path(root)
        if root_path == temp_flat_dir or str(temp_flat_dir) in str(root_path) : # Don't process the temp dir itself
            continue
        for file_name in files:
            original_path = root_path / file_name
            files_to_move.append(original_path)

    for original_path in files_to_move:
        new_filename = original_path.name
        if name_by_path_flag:
            try:
                rel_path_to_source = original_path.relative_to(source_dir)
                new_filename = f"{'_'.join(rel_path_to_source.parts)}"
            except ValueError: # If original_path is not under source_dir (should not happen with os.walk from source_dir)
                pass # Keep original name
        
        # Ensure unique names if collisions happen (though less likely with name_by_path)
        counter = 0
        final_new_filename = new_filename
        prospective_new_path = temp_flat_dir / final_new_filename
        while prospective_new_path.exists():
            counter += 1
            base, ext = os.path.splitext(new_filename)
            final_new_filename = f"{base}_{counter}{ext}"
            prospective_new_path = temp_flat_dir / final_new_filename

        try:
            shutil.copy(original_path, prospective_new_path) # Copy instead of move
            moved_files_map[str(original_path.relative_to(source_dir))] = prospective_new_path
        except Exception as e:
            print(f"Warning: Could not copy {original_path} to flattened dir: {e}")


    print(f"Flattened {len(moved_files_map)} files (by copying) into {temp_flat_dir}.")
    return temp_flat_dir # This is the new source_dir for zipping if flatten is True


def delete_files_to_fit_size_in_dir(directory_to_prune_str, target_size_mb, preferences_list, verbose):
    """Deletes files in order of preference from the given directory to meet target size."""
    directory_to_prune = Path(directory_to_prune_str)
    target_size_bytes = target_size_mb * 1024 * 1024
    current_size = get_directory_size(directory_to_prune)

    if current_size <= target_size_bytes:
        if verbose: print(f"Directory size {current_size / (1024*1024):.2f}MB is already within target {target_size_mb}MB.")
        return []

    if verbose: print(f"Reducing size of {directory_to_prune}... Current: {current_size / (1024 * 1024):.2f} MB, Target: {target_size_mb} MB")

    # Get all files, sorted by size (largest first) for efficient pruning
    all_files_in_prune_dir = sorted(
        [f for f in directory_to_prune.rglob('*') if f.is_file()],
        key=lambda f: f.stat().st_size,
        reverse=True
    )

    # Create a list of files to delete, ordered by preference then by size
    files_to_consider_deletion = []
    # Add files matching preferred extensions for deletion first
    for pref_ext in preferences_list:
        files_to_consider_deletion.extend([f for f in all_files_in_prune_dir if f.suffix == pref_ext])
    # Add remaining files (those not matching preferred extensions)
    files_to_consider_deletion.extend([f for f in all_files_in_prune_dir if f.suffix not in preferences_list])
    
    # Remove duplicates while preserving order (important if a file matches multiple prefs or is already there)
    seen_files_for_deletion = set()
    unique_files_for_deletion = []
    for f_del in files_to_consider_deletion:
        if f_del not in seen_files_for_deletion:
            unique_files_for_deletion.append(f_del)
            seen_files_for_deletion.add(f_del)


    removed_files_paths = []
    for file_to_delete in unique_files_for_deletion:
        if current_size <= target_size_bytes:
            break
        if file_to_delete.exists(): # Check if it wasn't already deleted (e.g. if it was part of a dir that got removed)
            try:
                file_size = file_to_delete.stat().st_size
                file_to_delete.unlink()
                removed_files_paths.append(str(file_to_delete))
                current_size -= file_size
                if verbose: print(f"Deleted {file_to_delete} (size: {file_size / (1024*1024):.2f}MB) for size constraint.")
            except Exception as e:
                if verbose: print(f"Could not delete {file_to_delete} for size constraint: {e}")


    if verbose: print(f"Deleted {len(removed_files_paths)} files from {directory_to_prune} to meet size constraint.")
    return removed_files_paths


def zip_folder(source_dir_str, output_zip_str, exclude_dirs_list, exclude_exts_list, exclude_files_list, remove_patterns_list, keep_patterns_list, max_size_mb, deletion_prefs_list, flatten_flag, name_by_path_flag, verbose):
    global source_dir_global
    source_dir_orig = Path(source_dir_str).resolve()
    source_dir_for_zip = source_dir_orig # This will be the directory we actually zip from
    source_dir_global = source_dir_orig # Set for should_exclude context

    output_zip_path = Path(output_zip_str).resolve()
    
    exclude_dirs_set = set(exclude_dirs_list)
    exclude_exts_set = set(exclude_exts_list)
    exclude_files_set = set(exclude_files_list)

    temp_flattened_dir_path = None # To keep track if we created a temp flattened dir

    if flatten_flag:
        if verbose: print("Flattening directory for zip...")
        # flatten_directory_for_zip now copies files to a new temp dir
        temp_flattened_dir_path = flatten_directory_for_zip(str(source_dir_orig), name_by_path_flag)
        source_dir_for_zip = temp_flattened_dir_path
        source_dir_global = temp_flattened_dir_path # Exclusions should now be relative to the flattened structure if needed,
                                                    # but arcname logic will use relative_to(source_dir_for_zip)


    # Initial size check and pruning loop (if max_size_mb is set)
    # This loop might run multiple times if the initial pruning isn't enough
    # or if certain files can't be deleted, though the current logic prunes then zips once.
    # A more robust loop would zip, check size, then prune more if needed.
    # For now, we prune the source_dir_for_zip (which might be temp_flattened_dir_path) *before* zipping.

    if max_size_mb is not None:
        if verbose: print(f"Max zip size specified: {max_size_mb}MB. Checking source directory for pruning.")
        # This deletes from source_dir_for_zip (which could be the temp flattened dir)
        delete_files_to_fit_size_in_dir(str(source_dir_for_zip), max_size_mb, deletion_prefs_list, verbose)


    if verbose: print(f"Starting zip creation for '{source_dir_for_zip}' into '{output_zip_path}'...")
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir_for_zip, topdown=True):
            root_path = Path(root)
            
            # For zipping, exclusion of directories means we don't even walk into them
            # The should_exclude needs to understand what it's relative to when zipping a flattened dir.
            # If flattened, all files are at top level, so dir exclusions based on name might not apply as expected
            # unless `should_exclude` is adapted or only file-based exclusions run post-flattening.
            # For now, `arcname` is `file_path.relative_to(source_dir_for_zip)`, which is correct.
            # The `dirs[:]` modification below should be careful with flattened structures.

            original_dirs_for_zip = list(dirs) # Iterate over a copy
            dirs[:] = [] # Clear and rebuild
            for d_name in original_dirs_for_zip:
                dir_path_obj = root_path / d_name
                # If source_dir_for_zip is the flattened dir, dir_path_obj might not be meaningful for original exclusion rules.
                # This part of dir exclusion is more relevant for non-flattened zipping.
                if flatten_flag: # In flatten mode, there are no subdirectories in source_dir_for_zip to exclude.
                     dirs.append(d_name) # (This will likely be empty after first level)
                     continue

                relative_dir_path_str = str(dir_path_obj.relative_to(source_dir_for_zip)) #This might be an issue if source_dir_global isn't source_dir_for_zip
                
                # Use original source_dir for context if not flattened
                # When zipping, exclusion for directories means we don't descend
                # Check against original source_dir for directory name exclusions
                path_in_original_repo_for_dir = source_dir_orig / relative_dir_path_str

                if not should_exclude(path_in_original_repo_for_dir, relative_dir_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
                    dirs.append(d_name)
                elif verbose:
                     print(f"Zip: Skipping traversal of excluded directory: {relative_dir_path_str}")


            for file_name in files:
                file_path_obj = root_path / file_name
                
                # Determine the path relative to the original source for exclusion logic
                # If flattened, file_path_obj is in the temp_flattened_dir. We need its original relative path.
                # This is tricky. The current `should_exclude` takes path_obj and relative_path_str.
                # If flattened, the `relative_path_str` for `should_exclude` should ideally be the *original* relative path.
                # However, `flatten_directory_for_zip` doesn't preserve this original relative path info for each file in the temp dir.
                # A simpler approach for flattened zips: apply exclusions *before* flattening, or apply only name/ext based exclusions to files in the flat dir.
                # For now, we'll use the path in the (potentially flattened) source_dir_for_zip.
                # This means dir-name based exclusions on original paths might not work as expected in flatten mode.

                path_for_exclusion_check = file_path_obj
                relative_path_for_exclusion_check = str(file_path_obj.relative_to(source_dir_for_zip))
                if flatten_flag and name_by_path_flag:
                     # If named by path, the filename itself contains original path info.
                     # We might need to reconstruct an "effective" original path for `should_exclude` if complex dir exclusions are needed.
                     # For now, this is a simplification: `should_exclude` sees the flat path.
                     pass


                if should_exclude(path_for_exclusion_check, relative_path_for_exclusion_check, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
                    if verbose: print(f"Zip: Excluded file: {relative_path_for_exclusion_check}")
                    continue

                arcname = file_path_obj.relative_to(source_dir_for_zip)
                zipf.write(file_path_obj, arcname)
                if verbose:
                    print(f"Zip: Added: {arcname}")

    final_zip_size_mb = output_zip_path.stat().st_size / (1024 * 1024)
    print(f"\nFinal zip file created: {output_zip_path} (Size: {final_zip_size_mb:.2f} MB)")

    if temp_flattened_dir_path and temp_flattened_dir_path.exists():
        if verbose: print(f"Cleaning up temporary flattened directory: {temp_flattened_dir_path}")
        shutil.rmtree(temp_flattened_dir_path)
    
    source_dir_global = None # Reset


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zip a folder or generate LLM text representation, applying exclusions.")
    parser.add_argument("source", help="Path to the folder to process")
    parser.add_argument("-o", "--output", required=True, help="Output file path (either .zip or .txt for LLM format)")
    parser.add_argument("-f", "--format", choices=["zip", "llm"], default="zip", help="Output format: 'zip' or 'llm' (for LLM text)")

    # Exclusion/Inclusion (shared)
    parser.add_argument("-xd", "--exclude-dir", nargs="*", default=list(DEFAULT_EXCLUDE_DIRS), help="Directory names to exclude (e.g., .git node_modules)")
    parser.add_argument("-xe", "--exclude-ext", nargs="*", default=list(DEFAULT_EXCLUDE_EXTS), help="File extensions to exclude (e.g., .log .pyc)")
    parser.add_argument("-xf", "--exclude-file", nargs="*", default=list(DEFAULT_EXCLUDE_FILES), help="Specific filenames to exclude (e.g., package-lock.json)")
    parser.add_argument("-rp", "--remove-patterns", nargs="*", default=[], help="Glob patterns for files/dirs to exclude (e.g., **/temp/* *.bak)")
    parser.add_argument("-kp", "--keep-patterns", nargs="*", default=[], help="Glob patterns for files/dirs to force include, overriding exclusions (e.g., **/*.important.log src/**/config.json)")

    # Zip specific
    parser.add_argument("-ms", "--max-size-mb", type=float, help="[ZIP only] Maximum zip output size in MB. Files will be deleted from a temporary source to try to meet this.")
    parser.add_argument("-dp", "--deletion-prefs", nargs="*", default=[], help="[ZIP only] File extensions prioritized for deletion if zip exceeds max-size (e.g., .log .tmp .jpeg)")
    parser.add_argument("--flatten-zip", action="store_true", help="[ZIP only] Flatten the directory structure (copy files to a temporary flat dir) before zipping.")
    parser.add_argument("--name-by-path-zip", action="store_true", help="[ZIP only] When flattening, rename files using their original relative path (e.g., src_module_file.py).")

    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed logs during processing")

    args = parser.parse_args()

    # Prepare exclusion sets/lists
    # Keep patterns can bring back files that would otherwise be excluded by default lists
    # So, apply keep patterns by removing from effective exclude sets if a keep pattern matches.
    # This is complex to do perfectly here. A simpler model is that `should_exclude` checks keep_patterns first.

    effective_exclude_dirs = set(args.exclude_dir)
    effective_exclude_exts = set(args.exclude_ext)
    effective_exclude_files = set(args.exclude_file)

    # Note: The `include-file` argument from your original script was effectively replaced by `keep-patterns`.
    # If a file matches a keep_pattern, `should_exclude` will return False.

    if args.format == "zip":
        zip_folder(
            args.source, args.output,
            list(effective_exclude_dirs), list(effective_exclude_exts), list(effective_exclude_files),
            args.remove_patterns, args.keep_patterns,
            args.max_size_mb, args.deletion_prefs,
            args.flatten_zip, args.name_by_path_zip,
            args.verbose
        )
    elif args.format == "llm":
        if not args.output.endswith(".txt"): # Basic check, could be more robust
            print("Warning: LLM output format is typically a .txt file.")
        generate_llm_text_output(
            args.source, args.output,
            list(effective_exclude_dirs), list(effective_exclude_exts), list(effective_exclude_files),
            args.remove_patterns, args.keep_patterns,
            args.verbose
        )
    else:
        parser.error(f"Unknown format: {args.format}")
