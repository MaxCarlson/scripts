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

def should_exclude(path_obj: Path, relative_path_str: str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose_debug=False):
    """
    Determines if a file or directory should be excluded based on multiple criteria.
    Keep patterns override exclusions. Remove patterns force exclusion unless overridden by keep.
    """
    global source_dir_global
    if source_dir_global is None:
        raise ValueError("source_dir_global is not set in should_exclude context.")

    # 1. Check if explicitly kept (overrides all exclusions)
    for pattern in keep_patterns_list:
        if fnmatch.fnmatch(relative_path_str, pattern) or fnmatch.fnmatch(path_obj.name, pattern):
            if verbose_debug: print(f"DEBUG: Kept '{relative_path_str}' by pattern '{pattern}'")
            return False # Not excluded

    # 2. Check if explicitly removed (unless kept by a pattern above)
    for pattern in remove_patterns_list:
        is_rel_match = fnmatch.fnmatch(relative_path_str, pattern)
        is_name_match = fnmatch.fnmatch(path_obj.name, pattern)
        
        if verbose_debug and "temp_files/a.bak" in relative_path_str and "**/temp_files/*" == pattern : # Specific debug for the problematic case
             print(f"DEBUG: remove_check: rel_path='{relative_path_str}', name='{path_obj.name}', pattern='{pattern}'")
             print(f"DEBUG: fnmatch('{relative_path_str}', '{pattern}') = {is_rel_match}")
             print(f"DEBUG: fnmatch('{path_obj.name}', '{pattern}') = {is_name_match}")

        if is_rel_match or is_name_match:
            if verbose_debug: print(f"DEBUG: Removed '{relative_path_str}' by pattern '{pattern}'")
            return True # Excluded

    # 3. Check default directory exclusions (path components)
    path_parts = Path(relative_path_str).parts
    current_relative_component_path = Path()
    for idx, part_name in enumerate(path_parts):
        current_relative_component_path = current_relative_component_path / part_name
        # Check if this component, when resolved, is actually a directory on disk
        absolute_component_path = source_dir_global / current_relative_component_path
        
        if part_name in exclude_dirs_set and absolute_component_path.is_dir():
            # If an excluded directory component is found in the path.
            # Example: relative_path_str = "node_modules/lib/file.js", part_name = "node_modules"
            # This rule excludes items if any of their path components (that are dirs) are in exclude_dirs_set.
            if verbose_debug: print(f"DEBUG: Excluded '{relative_path_str}' because component '{part_name}' ({absolute_component_path}) is an excluded dir.")
            return True 

    # 4. Check if the item itself (if a directory) is an excluded directory name
    if path_obj.is_dir() and path_obj.name in exclude_dirs_set:
        if verbose_debug: print(f"DEBUG: Excluded dir '{relative_path_str}' by its name '{path_obj.name}'.")
        return True

    # 5. Check file extension and specific file name exclusions for files
    if path_obj.is_file():
        if path_obj.suffix in exclude_exts_set:
            if verbose_debug: print(f"DEBUG: Excluded file '{relative_path_str}' by extension '{path_obj.suffix}'.")
            return True
        if path_obj.name in exclude_files_set:
            if verbose_debug: print(f"DEBUG: Excluded file '{relative_path_str}' by name '{path_obj.name}'.")
            return True
    
    if verbose_debug: print(f"DEBUG: Not excluding '{relative_path_str}'.")
    return False


def _is_dir_skippable_for_traversal(dir_path_obj: Path, relative_dir_path_str: str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose_debug=False):
    """
    Helper to decide if a directory should be skipped for traversal (os.walk, tree).
    A directory is skipped if it's normally excluded UNLESS a keep_pattern targets its children.
    """
    # Check if the directory itself would be excluded by any rule (ignoring children for now)
    is_normally_excluded = should_exclude(dir_path_obj, relative_dir_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose_debug)

    if not is_normally_excluded:
        return False # Not excluded, so don't skip traversal

    # If normally excluded, check if this exclusion was due to a directory naming rule
    # (either its own name or a parent component's name being in exclude_dirs_set).
    # We only want to override for traversal if it's this kind of exclusion.
    # A remove_pattern on the directory itself should still cause it to be skipped.

    # Check if a remove_pattern specifically targets this directory path or name.
    # If so, it should be skipped regardless of keep_patterns for children.
    for rp_pattern in remove_patterns_list:
        if fnmatch.fnmatch(relative_dir_path_str, rp_pattern) or fnmatch.fnmatch(dir_path_obj.name, rp_pattern):
            if verbose_debug: print(f"DEBUG _is_dir_skippable: Dir '{relative_dir_path_str}' explicitly removed by pattern '{rp_pattern}', skipping traversal.")
            return True # Force skip due to remove_pattern on dir

    # Now, check if exclusion was due to a dir name rule from exclude_dirs_set
    is_excluded_by_a_dir_name_rule = False
    path_parts = Path(relative_dir_path_str).parts
    current_rel_path_check = Path()
    for part in path_parts:
        current_rel_path_check = current_rel_path_check / part
        if part in exclude_dirs_set and (source_dir_global / current_rel_path_check).is_dir():
            is_excluded_by_a_dir_name_rule = True
            break
    # Redundant with above, but direct check on the dir object's name
    if not is_excluded_by_a_dir_name_rule and dir_path_obj.name in exclude_dirs_set:
         is_excluded_by_a_dir_name_rule = True


    if is_excluded_by_a_dir_name_rule:
        # It's excluded by a dir name rule. Check if any keep_pattern targets its children.
        # Path(relative_dir_path_str) gives the relative path to the directory.
        # Path(relative_dir_path_str) / "" ensures it ends with a separator for startswith.
        dir_prefix_for_child_check = str(Path(relative_dir_path_str) / "") # e.g., ".git/" or "node_modules/"

        for kp in keep_patterns_list:
            # If keep_pattern starts with this directory's path and is longer, it implies a child.
            # e.g. dir_prefix = ".git/", kp = ".git/config"
            if kp.startswith(dir_prefix_for_child_check) and len(kp) > len(dir_prefix_for_child_check):
                if verbose_debug: print(f"DEBUG _is_dir_skippable: Dir '{relative_dir_path_str}' normally excluded by name, but kept for traversal due to child keep_pattern '{kp}'.")
                return False # Don't skip, a child is kept, so we need to traverse.
            # Also consider glob keep_patterns that might match deeper children, e.g. dir_path/**/file.txt
            # This gets complex. The startswith is a primary heuristic.
            # If kp = ".git/**/*config" and dir_prefix_for_child_check = ".git/"
            # fnmatch.fnmatch(".git/foo/bar/config", ".git/**/*config") is True.
            # We are checking if the pattern *itself* implies a child.
            if fnmatch.fnmatch(dir_prefix_for_child_check + "some_child", kp) or \
               fnmatch.fnmatch(dir_prefix_for_child_check + "some_dir/some_child", kp):
                if verbose_debug: print(f"DEBUG _is_dir_skippable: Dir '{relative_dir_path_str}' normally excluded by name, but kept for traversal due to glob child keep_pattern '{kp}'.")
                return False # Don't skip


    # If it was normally_excluded and not overridden by a child keep_pattern for traversal, then skip.
    if verbose_debug and is_normally_excluded: print(f"DEBUG _is_dir_skippable: Dir '{relative_dir_path_str}' is skippable (is_normally_excluded={is_normally_excluded}).")
    return is_normally_excluded # Skip if it's normally_excluded and no child keep_pattern forced traversal


def generate_directory_tree_string(current_dir_path: Path, base_source_dir_for_rel_paths: Path, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, max_depth=DEFAULT_MAX_HIERARCHY_DEPTH, prefix="", is_last_in_parent=True, is_root_call=True, verbose_debug=False):
    lines = []
    if is_root_call:
        lines.append(f"{current_dir_path.name}/")

    if max_depth == 0 and not is_root_call: return "" 

    try:
        entries = sorted(
            [item for item in current_dir_path.iterdir()],
            key=lambda x: (not x.is_dir(), x.name.lower())
        )
    except PermissionError:
        lines.append(f"{prefix}└── [Error: Permission Denied]")
        return "\n".join(lines)

    valid_entries = []
    for entry in entries:
        relative_path_str = str(entry.relative_to(base_source_dir_for_rel_paths))
        if entry.is_dir():
            if not _is_dir_skippable_for_traversal(entry, relative_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose_debug):
                valid_entries.append(entry)
        elif not should_exclude(entry, relative_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose_debug):
            valid_entries.append(entry)
    
    for i, entry in enumerate(valid_entries):
        is_last_entry_in_current_level = (i == len(valid_entries) - 1)
        connector = "└── " if is_last_entry_in_current_level else "├── "
        lines.append(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")

        if entry.is_dir(): 
            new_prefix = prefix + ("    " if is_last_entry_in_current_level else "│   ")
            next_max_depth = max_depth - 1 if max_depth != -1 else -1
            
            sub_tree_lines = generate_directory_tree_string(
                entry, 
                base_source_dir_for_rel_paths, 
                exclude_dirs_set, exclude_exts_set, exclude_files_set, 
                keep_patterns_list, remove_patterns_list, 
                next_max_depth, new_prefix, 
                is_last_entry_in_current_level, 
                is_root_call=False,
                verbose_debug=verbose_debug
            ).splitlines()
            lines.extend(sub_tree_lines)

    if is_root_call and not valid_entries and not any("[Error: Permission Denied]" in l for l in lines):
        # Only add placeholder if no entries were processed under root.
        # If lines only contains the root name, it means no valid entries.
        if len(lines) == 1 and lines[0] == f"{current_dir_path.name}/":
             lines.append(f"└── [No processable content or all items excluded]")
        elif not lines and current_dir_path.name : # Should not happen if root_call appends root name
             lines.append(f"{current_dir_path.name}/")
             lines.append(f"└── [No processable content or all items excluded]")


        
    return "\n".join(lines)


def generate_llm_text_output(source_dir_path_str, output_file_path_str, exclude_dirs_list, exclude_exts_list, exclude_files_list, remove_patterns_list, keep_patterns_list, max_tree_depth, verbose):
    global source_dir_global 
    original_global_val = source_dir_global 
    
    source_dir = Path(source_dir_path_str).resolve()
    output_file_path = Path(output_file_path_str).resolve()
    source_dir_global = source_dir 

    exclude_dirs_set = set(exclude_dirs_list)
    exclude_exts_set = set(exclude_exts_list)
    exclude_files_set = set(exclude_files_list)

    verbose_debug_flag = verbose 

    if verbose: print(f"Using source directory for LLM output: {source_dir}")
    if verbose: print(f"Global source_dir_global set to: {source_dir_global} for generate_llm_text_output")

    tree_str = generate_directory_tree_string(source_dir, source_dir, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, max_depth=max_tree_depth, is_root_call=True, verbose_debug=verbose_debug_flag)

    included_files_content = [] 
    excluded_for_listing = []    

    for root, dirs, files in os.walk(source_dir, topdown=True): 
        root_path = Path(root)
        
        original_dirs = list(dirs) 
        dirs[:] = [] 
        for d_name in original_dirs:
            dir_path_obj = root_path / d_name
            relative_dir_path_str = str(dir_path_obj.relative_to(source_dir))
            if not _is_dir_skippable_for_traversal(dir_path_obj, relative_dir_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose_debug_flag):
                dirs.append(d_name)
            elif verbose: 
                 print(f"LLM Output: Traversal excluded directory: {relative_dir_path_str} (skipped by _is_dir_skippable_for_traversal)")

        for file_name in files:
            file_path_obj = root_path / file_name
            relative_file_path_str = str(file_path_obj.relative_to(source_dir))
            if should_exclude(file_path_obj, relative_file_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose_debug_flag):
                excluded_for_listing.append((relative_file_path_str, "Excluded by rules (dir, ext, file, or pattern)"))
                if verbose and not verbose_debug_flag: print(f"LLM Output: File listed as excluded: {relative_file_path_str}")
                continue
            
            try:
                content = file_path_obj.read_text(encoding='utf-8', errors='ignore')
                included_files_content.append((relative_file_path_str, content))
                if verbose: print(f"LLM Output: Included content for: {relative_file_path_str}")
            except Exception as e:
                excluded_for_listing.append((relative_file_path_str, f"Error reading file: {str(e)[:50]}"))
                if verbose: print(f"LLM Output: Could not read/include content for: {relative_file_path_str} due to {e}")
    
    source_dir_global = original_global_val 

    output_parts = []
    output_parts.append(f"=== Repository Analysis: {source_dir.name} ===")
    output_parts.append(f"Date Processed: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output_parts.append(f"Root Path: {source_dir}")
    output_parts.append(f"\nSummary:")
    output_parts.append(f"* Files with content included: {len(included_files_content)}")
    output_parts.append(f"* Files listed (content excluded or unreadable): {len(excluded_for_listing)}")
    output_parts.append("\n---\n")
    output_parts.append("**1. Full Directory Structure (filtered):**")
    
    tree_lines_check = tree_str.splitlines()
    if (len(tree_lines_check) == 1 and tree_lines_check[0] == f"{source_dir.name}/") or \
       (len(tree_lines_check) == 2 and tree_lines_check[0] == f"{source_dir.name}/" and "No processable content" in tree_lines_check[1]):
        # Tree is effectively empty or shows the placeholder.
        # If there *are* included files, the tree should show them, so don't use generic placeholder.
        # This placeholder is primarily for when the repo itself is empty of listable items.
        if not included_files_content and not excluded_for_listing and not any(any(ve.name for ve_l in tree_lines_check if isinstance(ve_l, list) for ve in ve_l) for l_idx, ve_l in enumerate(tree_lines_check) if l_idx >0): # complex check, simplify
            # If no files processed and tree only shows root, then use placeholder
            if tree_lines_check[0] == f"{source_dir.name}/" and "No processable content" not in tree_str:
                 output_parts.append(f"{source_dir.name}/\n└── [No processable content or all items excluded]")
            else:
                 output_parts.append(tree_str) # Use tree_str if it already has the placeholder
        else:
            output_parts.append(tree_str) # Actual tree, even if minimal
    elif not tree_str.strip() : 
        output_parts.append(f"{source_dir.name}/\n└── [No processable content or all items excluded]")
    else:
        output_parts.append(tree_str)

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
    if target_flat_dir.exists():
        shutil.rmtree(target_flat_dir)
    target_flat_dir.mkdir(exist_ok=True)
    copied_file_count = 0
    verbose_debug_flag = verbose

    for root, dirs, files in os.walk(original_source_dir, topdown=True):
        current_root_path = Path(root)
        original_sub_dirs = list(dirs)
        dirs[:] = []
        for d_name in original_sub_dirs:
            dir_path_obj = current_root_path / d_name
            relative_dir_path_str = str(dir_path_obj.relative_to(original_source_dir))
            if not _is_dir_skippable_for_traversal(dir_path_obj, relative_dir_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose_debug_flag):
                dirs.append(d_name)
            elif verbose:
                print(f"Flatten: Skipping traversal of excluded directory: {relative_dir_path_str}")

        for file_name in files:
            original_file_path = current_root_path / file_name
            relative_file_path_str = str(original_file_path.relative_to(original_source_dir))
            if should_exclude(original_file_path, relative_file_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose_debug_flag):
                if verbose and not verbose_debug_flag: print(f"Flatten: Excluded file from copy: {relative_file_path_str}")
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
    original_global_val = source_dir_global 
    source_dir_orig = Path(source_dir_str).resolve()
    output_zip_path = Path(output_zip_str).resolve()
    source_dir_global = source_dir_orig 
    if verbose: print(f"Global source_dir_global set to: {source_dir_global} for zip_folder operation")

    exclude_dirs_set = set(exclude_dirs_list)
    exclude_exts_set = set(exclude_exts_list)
    exclude_files_set = set(exclude_files_list)
    verbose_debug_flag = verbose

    temp_flattened_dir_path = None
    source_dir_to_zip_from = source_dir_orig 

    if flatten_flag:
        if verbose: print("Flattening directory for zip by copying allowed files...")
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

    if max_size_mb is not None:
        dir_to_prune = source_dir_to_zip_from
        if verbose: print(f"Max zip size specified: {max_size_mb}MB. Checking directory '{dir_to_prune}' for pruning.")
        delete_files_to_fit_size_in_dir(str(dir_to_prune), max_size_mb, deletion_prefs_list, verbose)

    if verbose: print(f"Starting zip creation for '{source_dir_to_zip_from}' into '{output_zip_path}'...")
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir_to_zip_from, topdown=True):
            current_root_path = Path(root)
            if not flatten_flag: 
                original_sub_dirs_for_zip = list(dirs)
                dirs[:] = []
                for d_name in original_sub_dirs_for_zip:
                    dir_path_obj = current_root_path / d_name
                    relative_dir_path_str = str(dir_path_obj.relative_to(source_dir_orig))
                    if not _is_dir_skippable_for_traversal(dir_path_obj, relative_dir_path_str, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose_debug_flag):
                        dirs.append(d_name)
                    elif verbose:
                        print(f"Zip: Skipping traversal of excluded directory: {relative_dir_path_str}")
            
            for file_name in files:
                file_path_to_add = current_root_path / file_name
                arcname = file_path_to_add.relative_to(source_dir_to_zip_from)
                if not flatten_flag: 
                    relative_file_path_for_check = str(file_path_to_add.relative_to(source_dir_orig))
                    if should_exclude(file_path_to_add, relative_file_path_for_check, exclude_dirs_set, exclude_exts_set, exclude_files_set, keep_patterns_list, remove_patterns_list, verbose_debug_flag):
                        if verbose and not verbose_debug_flag: print(f"Zip: Excluded file: {relative_file_path_for_check}")
                        continue
                zipf.write(file_path_to_add, arcname)
                if verbose: print(f"Zip: Added: {arcname}")

    final_zip_size_mb = output_zip_path.stat().st_size / (1024 * 1024)
    print(f"\nFinal zip file created: {output_zip_path} (Size: {final_zip_size_mb:.2f} MB)")
    if temp_flattened_dir_path and temp_flattened_dir_path.exists():
        if verbose: print(f"Cleaning up temporary flattened directory: {temp_flattened_dir_path}")
        shutil.rmtree(temp_flattened_dir_path)
    source_dir_global = original_global_val


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process a repository: Zip it or generate a textual representation for LLMs, applying inclusion/exclusion rules.")
    parser.add_argument("source", help="Path to the source folder to process.")
    parser.add_argument("-o", "--output", required=True, help="Path for the output file (e.g., archive.zip or analysis.txt).")
    parser.add_argument("-f", "--format", choices=["zip", "llm"], default="zip", help="Output format: 'zip' for a ZIP archive, 'llm' for a textual analysis.")
    parser.add_argument("-xd", "--exclude-dirs", nargs="*", default=list(DEFAULT_EXCLUDE_DIRS), metavar="DIRNAME", help=f"Directory names to exclude (e.g., .git node_modules). Defaults: {', '.join(DEFAULT_EXCLUDE_DIRS)}.")
    parser.add_argument("-xe", "--exclude-exts", nargs="*", default=list(DEFAULT_EXCLUDE_EXTS), metavar=".EXT", help=f"File extensions to exclude (e.g., .log .pyc). Defaults: {', '.join(DEFAULT_EXCLUDE_EXTS)}.")
    parser.add_argument("-xf", "--exclude-files", nargs="*", default=list(DEFAULT_EXCLUDE_FILES), metavar="FILENAME", help=f"Specific filenames to exclude (e.g., package-lock.json). Defaults: {', '.join(DEFAULT_EXCLUDE_FILES)}.")
    parser.add_argument("-rp", "--remove-patterns", nargs="*", default=[], metavar="PATTERN", help="Glob patterns for files/dirs to forcibly exclude (e.g., '**/temp/*' '*.bak'). Applied after defaults unless overridden by a keep-pattern.")
    parser.add_argument("-kp", "--keep-patterns", nargs="*", default=[], metavar="PATTERN", help="Glob patterns for files/dirs to forcibly include, overriding other exclusions (e.g., '**/*.important.log' 'src/**/config.json').")
    zip_group = parser.add_argument_group('ZIP Specific Options')
    zip_group.add_argument("-ms", "--max-size-mb", type=float, metavar="MB", help="Maximum output ZIP file size in Megabytes. If exceeded, files are deleted (from a temporary copy if flattening) based on deletion-prefs to meet the size.")
    zip_group.add_argument("-dp", "--deletion-prefs", nargs="*", default=[], metavar=".EXT", help="File extensions prioritized for deletion if ZIP output exceeds max-size (e.g., .log .tmp .jpeg). Largest files with these extensions are removed first.")
    zip_group.add_argument("--flatten-zip", action="store_true", help="Flatten the directory structure in the ZIP. All included files are copied to the root of the archive, potentially renamed by path.")
    zip_group.add_argument("--name-by-path-zip", action="store_true", help="When --flatten-zip is used, rename files in the archive using their original relative path (e.g., 'src_module_file.py').")
    llm_group = parser.add_argument_group('LLM Text Output Specific Options')
    llm_group.add_argument("-md", "--max-tree-depth", type=int, default=DEFAULT_MAX_HIERARCHY_DEPTH, metavar="DEPTH", help=f"Maximum depth for the directory tree in LLM output. -1 for infinite. Default: {DEFAULT_MAX_HIERARCHY_DEPTH}.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging to print detailed processing steps, including exclusion rule evaluations if issues persist.")
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
