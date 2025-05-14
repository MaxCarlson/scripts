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

# Global variable to hold the source directory for should_exclude context
source_dir_global = None

def get_directory_size(directory):
    """Returns total size of directory (in bytes)."""
    return sum(f.stat().st_size for f in Path(directory).rglob('*') if f.is_file())

def should_exclude(path_obj: Path, relative_path_str: str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
    """
    Determines if a file or directory should be excluded based on multiple criteria.
    Keep patterns override exclusions. Remove patterns force exclusion unless overridden by keep.
    """
    global source_dir_global
    if source_dir_global is None:
        # This should not happen if source_dir_global is managed correctly
        raise ValueError("source_dir_global is not set in should_exclude")

    # Check if explicitly kept
    if any(fnmatch.fnmatch(relative_path_str, pattern) or fnmatch.fnmatch(path_obj.name, pattern) for pattern in keep_patterns_list):
        return False

    # Check if explicitly removed
    if any(fnmatch.fnmatch(relative_path_str, pattern) or fnmatch.fnmatch(path_obj.name, pattern) for pattern in remove_patterns_list):
        return True

    # Check default dir exclusions based on components of the relative path
    path_parts = Path(relative_path_str).parts
    current_relative_component_path = Path()
    for part_name in path_parts:
        # For a path like "node_modules/lib/file.js", part_name will be "node_modules", then "lib", then "file.js"
        # We are interested if "node_modules" or "lib" (if they are dirs) are in exclude_dirs_set.
        # The last part (filename) is handled by file/extension checks later.
        if part_name == path_parts[-1] and not path_obj.is_dir(): # If it's the file part itself, skip dir check for it
            break
        
        current_relative_component_path = current_relative_component_path / part_name
        absolute_component_path = source_dir_global / current_relative_component_path
        
        if part_name in exclude_dirs_set and absolute_component_path.is_dir():
            return True # Excluded if any path component dir name is in exclude_dirs_set

    # Check if the item itself (if a directory) is an excluded directory name
    if path_obj.is_dir() and path_obj.name in exclude_dirs_set:
        return True
    # Check file extension and specific file name exclusions
    if path_obj.is_file():
        if path_obj.suffix in exclude_exts_set:
            return True
        if path_obj.name in exclude_files_set:
            return True
    
    return False


def generate_directory_tree_string(current_dir_path: Path, base_source_dir: Path, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, max_depth=DEFAULT_MAX_HIERARCHY_DEPTH, prefix="", is_last=True, is_root=True):
    """Generates a string representation of the directory tree."""
    global source_dir_global # Use the global source_dir
    if is_root:
        source_dir_global = base_source_dir # Set it at the beginning of the call for should_exclude

    lines = []
    if is_root:
        lines.append(f"{current_dir_path.name}/")

    if max_depth == 0 and not is_root : return "" # Depth limit reached for non-root

    try:
        entries = sorted(
            [item for item in current_dir_path.iterdir()],
            key=lambda x: (not x.is_dir(), x.name.lower())
        )
    except PermissionError:
        lines.append(f"{prefix}└── [Error: Permission Denied]")
        if is_root: source_dir_global = None
        return "\n".join(lines)

    valid_entries = []
    for entry in entries:
        relative_path_str = str(entry.relative_to(base_source_dir))
        if not should_exclude(entry, relative_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
            valid_entries.append(entry)

    for i, entry in enumerate(valid_entries):
        connector = "└── " if i == len(valid_entries) - 1 else "├── "
        lines.append(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")

        if entry.is_dir(): # Recurse if it's a directory (already passed should_exclude for itself)
            new_prefix = prefix + ("    " if i == len(valid_entries) - 1 else "│   ")
            # Recursive call uses max_depth - 1 (if max_depth is not -1 for infinite)
            next_max_depth = max_depth - 1 if max_depth != -1 else -1
            # Pass base_source_dir consistently
            sub_tree = generate_directory_tree_string(entry, base_source_dir, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, next_max_depth, new_prefix, i == len(valid_entries) -1, is_root=False)
            if sub_tree: # Avoid adding empty strings or just newlines from deeper calls that yield nothing
                 lines.extend(sub_tree.splitlines())


    if is_root:
        source_dir_global = None # Reset global var
    return "\n".join(lines)


def generate_llm_text_output(source_dir_path_str, output_file_path_str, exclude_dirs_list, exclude_exts_list, exclude_files_list, remove_patterns_list, keep_patterns_list, max_tree_depth, verbose):
    global source_dir_global 
    source_dir = Path(source_dir_path_str).resolve()
    output_file_path = Path(output_file_path_str).resolve()

    # Set source_dir_global here for all operations within this function
    source_dir_global = source_dir 

    exclude_dirs_set = set(exclude_dirs_list)
    exclude_exts_set = set(exclude_exts_list)
    exclude_files_set = set(exclude_files_list)

    if verbose: print(f"Using source directory for LLM output: {source_dir}")
    if verbose: print(f"Global source_dir_global set to: {source_dir_global}")

    # 1. Generate directory tree string
    if verbose: print("Generating directory tree...")
    tree_str = generate_directory_tree_string(source_dir, source_dir, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, max_depth=max_tree_depth, is_root=True)

    # 2. Discover files and categorize them
    if verbose: print("Discovering and categorizing files...")
    included_files_content = [] 
    excluded_for_listing = []    

    for root, dirs, files in os.walk(source_dir, topdown=True):
        root_path = Path(root)
        
        # Filter directories based on exclusion rules for traversal
        original_dirs = list(dirs) 
        dirs[:] = [] 
        for d_name in original_dirs:
            dir_path_obj = root_path / d_name
            relative_dir_path_str = str(dir_path_obj.relative_to(source_dir))
            if not should_exclude(dir_path_obj, relative_dir_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
                dirs.append(d_name)
            elif verbose:
                 print(f"LLM Output: Traversal excluded directory: {relative_dir_path_str}")

        for file_name in files:
            file_path_obj = root_path / file_name
            relative_file_path_str = str(file_path_obj.relative_to(source_dir))

            if should_exclude(file_path_obj, relative_file_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
                excluded_for_listing.append((relative_file_path_str, "Excluded by rules (dir, ext, file, or pattern)"))
                if verbose: print(f"LLM Output: File listed as excluded: {relative_file_path_str}")
                continue
            
            try:
                content = file_path_obj.read_text(encoding='utf-8', errors='ignore')
                included_files_content.append((relative_file_path_str, content))
                if verbose: print(f"LLM Output: Included content for: {relative_file_path_str}")
            except Exception as e:
                excluded_for_listing.append((relative_file_path_str, f"Error reading file: {str(e)[:50]}"))
                if verbose: print(f"LLM Output: Could not read/include content for: {relative_file_path_str} due to {e}")
    
    # Reset source_dir_global after all operations that depend on it are done
    source_dir_global = None

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
    output_parts.append(tree_str if tree_str else f"{source_dir.name}/\n└── [No processable content or all items excluded]")
    output_parts.append("\n---\n")

    output_parts.append("**2. Contextual Files (Content Excluded or Unreadable):**")
    if excluded_for_listing:
        for rel_path, reason in sorted(list(set(excluded_for_listing))): 
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

    try:
        output_file_path.write_text("\n".join(output_parts), encoding='utf-8')
        print(f"\nLLM text output generated at: {output_file_path}")
    except Exception as e:
        print(f"\nError writing LLM text output to {output_file_path}: {e}")


def create_flattened_source(original_source_dir: Path, target_flat_dir: Path, name_by_path_flag: bool, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose: bool):
    """
    Copies allowed files from original_source_dir to target_flat_dir, applying exclusions
    and renaming if name_by_path_flag is True.
    `source_dir_global` must be set to `original_source_dir` before calling this.
    """
    if target_flat_dir.exists():
        shutil.rmtree(target_flat_dir)
    target_flat_dir.mkdir(exist_ok=True)
    
    copied_file_count = 0
    for root, dirs, files in os.walk(original_source_dir, topdown=True):
        current_root_path = Path(root)

        # Prune directories for traversal based on original structure
        original_sub_dirs = list(dirs)
        dirs[:] = []
        for d_name in original_sub_dirs:
            dir_path_obj = current_root_path / d_name
            relative_dir_path_str = str(dir_path_obj.relative_to(original_source_dir))
            if not should_exclude(dir_path_obj, relative_dir_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
                dirs.append(d_name)
            elif verbose:
                print(f"Flatten: Skipping traversal of excluded directory: {relative_dir_path_str}")

        for file_name in files:
            original_file_path = current_root_path / file_name
            relative_file_path_str = str(original_file_path.relative_to(original_source_dir))

            if should_exclude(original_file_path, relative_file_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
                if verbose: print(f"Flatten: Excluded file from copy: {relative_file_path_str}")
                continue

            new_filename_str = original_file_path.name
            if name_by_path_flag:
                new_filename_str = "_".join(Path(relative_file_path_str).parts)
            
            counter = 0
            final_new_filename_in_flat_dir = new_filename_str
            prospective_new_path = target_flat_dir / final_new_filename_in_flat_dir
            while prospective_new_path.exists():
                counter += 1
                base, ext = os.path.splitext(new_filename_str)
                final_new_filename_in_flat_dir = f"{base}_{counter}{ext}"
                prospective_new_path = target_flat_dir / final_new_filename_in_flat_dir
            
            try:
                shutil.copy(original_file_path, prospective_new_path)
                copied_file_count +=1
                if verbose: print(f"Flatten: Copied '{relative_file_path_str}' to '{final_new_filename_in_flat_dir}'")
            except Exception as e:
                print(f"Warning: Could not copy {original_file_path} to flattened dir: {e}")
    
    if verbose: print(f"Flattened {copied_file_count} files into {target_flat_dir}.")


def delete_files_to_fit_size_in_dir(directory_to_prune_str, target_size_mb, preferences_list, verbose):
    """Deletes files in order of preference from the given directory to meet target size."""
    directory_to_prune = Path(directory_to_prune_str)
    target_size_bytes = target_size_mb * 1024 * 1024
    current_size = get_directory_size(directory_to_prune)

    if current_size <= target_size_bytes:
        if verbose: print(f"Directory size {current_size / (1024*1024):.2f}MB is already within target {target_size_mb}MB.")
        return []

    if verbose: print(f"Reducing size of {directory_to_prune}... Current: {current_size / (1024 * 1024):.2f} MB, Target: {target_size_mb} MB")

    all_files_in_prune_dir = sorted(
        [f for f in directory_to_prune.rglob('*') if f.is_file()],
        key=lambda f: f.stat().st_size,
        reverse=True
    )

    files_to_consider_deletion = []
    for pref_ext in preferences_list:
        files_to_consider_deletion.extend([f for f in all_files_in_prune_dir if f.suffix == pref_ext])
    files_to_consider_deletion.extend([f for f in all_files_in_prune_dir if f.suffix not in preferences_list])
    
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
        if file_to_delete.exists(): 
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
    output_zip_path = Path(output_zip_str).resolve()
    
    exclude_dirs_set = set(exclude_dirs_list)
    exclude_exts_set = set(exclude_exts_list)
    exclude_files_set = set(exclude_files_list)

    # CRITICAL: Set source_dir_global to the original source for all exclusion decisions
    source_dir_global = source_dir_orig
    if verbose: print(f"Global source_dir_global set to: {source_dir_global} for zip operation")

    temp_flattened_dir_path = None
    source_dir_to_zip_from = source_dir_orig # This is what os.walk will iterate over for zipping

    if flatten_flag:
        if verbose: print("Flattening directory for zip by copying allowed files...")
        # Create a temporary directory for flattened files *outside* source_dir_orig if possible, or make it unique
        # For simplicity, let's use a sub-directory of the output's parent, or a system temp if more robust.
        # Here, using a sub-directory of original source for now, but ensuring it's named uniquely or cleaned.
        temp_flattened_dir_path = source_dir_orig / f"__{output_zip_path.stem}_flatten_temp__"
        
        create_flattened_source(
            original_source_dir=source_dir_orig,
            target_flat_dir=temp_flattened_dir_path,
            name_by_path_flag=name_by_path_flag,
            exclude_dirs_set=exclude_dirs_set,
            exclude_exts_set=exclude_exts_set,
            exclude_files_set=exclude_files_set,
            keep_patterns_list=keep_patterns_list,
            remove_patterns_list=remove_patterns_list,
            verbose=verbose
        )
        source_dir_to_zip_from = temp_flattened_dir_path
        # From now on, source_dir_to_zip_from contains only files that should be in the zip.
        # No further should_exclude checks needed when iterating source_dir_to_zip_from.

    if max_size_mb is not None:
        # Pruning is done on the directory that will be zipped.
        # If flattening, this is the temp_flattened_dir_path. Otherwise, it's a copy or the original (risky).
        # For safety, if not flattening, deletion should ideally happen on a temporary copy of the source.
        # Current `delete_files_to_fit_size_in_dir` modifies in-place.
        # If not flattening, this is destructive to source_dir_orig if not handled carefully.
        # Let's assume for now if not flattening, user accepts source modification for sizing,
        # or that source_dir_str is already a temporary copy if this is a concern.
        # A safer approach would be to always copy to a temp processing dir if max_size_mb is set and not flattening.
        dir_to_prune = source_dir_to_zip_from # This is temp_flattened_dir_path if flatten_flag, else source_dir_orig
        if verbose: print(f"Max zip size specified: {max_size_mb}MB. Checking directory '{dir_to_prune}' for pruning.")
        delete_files_to_fit_size_in_dir(str(dir_to_prune), max_size_mb, deletion_prefs_list, verbose)

    if verbose: print(f"Starting zip creation for '{source_dir_to_zip_from}' into '{output_zip_path}'...")
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir_to_zip_from, topdown=True):
            current_root_path = Path(root)
            
            if not flatten_flag: # Only apply dir-level traversal exclusions if not already flattened
                original_sub_dirs_for_zip = list(dirs)
                dirs[:] = []
                for d_name in original_sub_dirs_for_zip:
                    dir_path_obj = current_root_path / d_name
                    # Relative path for should_exclude must be from original source perspective
                    relative_dir_path_str = str(dir_path_obj.relative_to(source_dir_orig if not temp_flattened_dir_path else temp_flattened_dir_path )) # Adjust if source_dir_to_zip_from is base
                    
                    # If source_dir_to_zip_from is source_dir_orig, then use source_dir_orig for relative path calculation.
                    # source_dir_global is already source_dir_orig.
                    if not should_exclude(dir_path_obj, str(dir_path_obj.relative_to(source_dir_orig)), exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
                        dirs.append(d_name)
                    elif verbose:
                        print(f"Zip: Skipping traversal of excluded directory: {relative_dir_path_str}")
            # If flatten_flag is True, dirs list will be empty after the first level of source_dir_to_zip_from (the temp flat dir)

            for file_name in files:
                file_path_to_add = current_root_path / file_name
                
                # Arcname is relative to the directory being zipped
                arcname = file_path_to_add.relative_to(source_dir_to_zip_from)

                if not flatten_flag: # If not flattened, apply final check (though create_flattened_source should handle most)
                    relative_file_path_for_check = str(file_path_to_add.relative_to(source_dir_orig))
                    if should_exclude(file_path_to_add, relative_file_path_for_check, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list):
                        if verbose: print(f"Zip: Excluded file: {relative_file_path_for_check}")
                        continue
                
                zipf.write(file_path_to_add, arcname)
                if verbose:
                    print(f"Zip: Added: {arcname}")

    final_zip_size_mb = output_zip_path.stat().st_size / (1024 * 1024)
    print(f"\nFinal zip file created: {output_zip_path} (Size: {final_zip_size_mb:.2f} MB)")

    if temp_flattened_dir_path and temp_flattened_dir_path.exists():
        if verbose: print(f"Cleaning up temporary flattened directory: {temp_flattened_dir_path}")
        shutil.rmtree(temp_flattened_dir_path)
    
    source_dir_global = None # Reset


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process a repository: Zip it or generate a textual representation for LLMs, applying inclusion/exclusion rules.")
    parser.add_argument("source", help="Path to the source folder to process.")
    parser.add_argument("-o", "--output", required=True, help="Path for the output file (e.g., archive.zip or analysis.txt).")
    parser.add_argument("-f", "--format", choices=["zip", "llm"], default="zip", help="Output format: 'zip' for a ZIP archive, 'llm' for a textual analysis.")

    # Exclusion/Inclusion Arguments
    parser.add_argument("-xd", "--exclude-dirs", nargs="*", default=list(DEFAULT_EXCLUDE_DIRS), metavar="DIRNAME", help=f"Directory names to exclude (e.g., .git node_modules). Defaults: {', '.join(DEFAULT_EXCLUDE_DIRS)}.")
    parser.add_argument("-xe", "--exclude-exts", nargs="*", default=list(DEFAULT_EXCLUDE_EXTS), metavar=".EXT", help=f"File extensions to exclude (e.g., .log .pyc). Defaults: {', '.join(DEFAULT_EXCLUDE_EXTS)}.")
    parser.add_argument("-xf", "--exclude-files", nargs="*", default=list(DEFAULT_EXCLUDE_FILES), metavar="FILENAME", help=f"Specific filenames to exclude (e.g., package-lock.json). Defaults: {', '.join(DEFAULT_EXCLUDE_FILES)}.")
    parser.add_argument("-rp", "--remove-patterns", nargs="*", default=[], metavar="PATTERN", help="Glob patterns for files/dirs to forcibly exclude (e.g., '**/temp/*' '*.bak'). Applied after defaults unless overridden by a keep-pattern.")
    parser.add_argument("-kp", "--keep-patterns", nargs="*", default=[], metavar="PATTERN", help="Glob patterns for files/dirs to forcibly include, overriding other exclusions (e.g., '**/*.important.log' 'src/**/config.json').")

    # ZIP Specific Arguments
    zip_group = parser.add_argument_group('ZIP Specific Options')
    zip_group.add_argument("-ms", "--max-size-mb", type=float, metavar="MB", help="Maximum output ZIP file size in Megabytes. If exceeded, files are deleted (from a temporary copy if flattening) based on deletion-prefs to meet the size.")
    zip_group.add_argument("-dp", "--deletion-prefs", nargs="*", default=[], metavar=".EXT", help="File extensions prioritized for deletion if ZIP output exceeds max-size (e.g., .log .tmp .jpeg). Largest files with these extensions are removed first.")
    zip_group.add_argument("--flatten-zip", action="store_true", help="Flatten the directory structure in the ZIP. All included files are copied to the root of the archive, potentially renamed by path.")
    zip_group.add_argument("--name-by-path-zip", action="store_true", help="When --flatten-zip is used, rename files in the archive using their original relative path (e.g., 'src_module_file.py').")

    # LLM Text Output Specific Arguments
    llm_group = parser.add_argument_group('LLM Text Output Specific Options')
    llm_group.add_argument("-md", "--max-tree-depth", type=int, default=DEFAULT_MAX_HIERARCHY_DEPTH, metavar="DEPTH", help=f"Maximum depth for the directory tree in LLM output. -1 for infinite. Default: {DEFAULT_MAX_HIERARCHY_DEPTH}.")
    
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging to print detailed processing steps.")

    args = parser.parse_args()

    effective_exclude_dirs = set(args.exclude_dirs)
    effective_exclude_exts = set(args.exclude_exts)
    effective_exclude_files = set(args.exclude_files)

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
        if not args.output.endswith(".txt") and Path(args.output).suffix == '':
            print(f"Warning: LLM output is '{args.output}'. Consider using a .txt extension for clarity.")
        generate_llm_text_output(
            args.source, args.output,
            list(effective_exclude_dirs), list(effective_exclude_exts), list(effective_exclude_files),
            args.remove_patterns, args.keep_patterns,
            args.max_tree_depth,
            args.verbose
        )
    else:
        parser.error(f"Unknown format: {args.format}")

